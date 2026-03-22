"""
LangGraph 노드 정의
각 노드는 AgentState를 받아 업데이트된 dict를 반환한다.
"""
import json
import base64
import structlog
from typing import Any
from tenacity import retry, stop_after_attempt, wait_exponential

from langchain_core.messages import HumanMessage
from agents.state import AgentState, MailItem, UserIntent
from config.llm import get_flash_llm, get_pro_llm, get_embeddings
from tools.gmail import fetch_unread_gmail
# from tools.outlook import fetch_unread_outlook
from tools.crawler import crawl_url
from tools.dedup import is_duplicate, mark_processed
from tools.telegram import send_messages
from db.repository import save_summary, search_similar

log = structlog.get_logger()


# ── 1. Ingest Node ───────────────────────────────────────────────────────────

async def ingest_node(state: AgentState) -> dict:
    """
    Gmail + Outlook에서 읽지 않은 메일 수집
    Dedup 체크 후 중복 제거, 처리 후 mark as read
    """
    log.info("ingest_node.start")
    raw_items: list[MailItem] = []

    # Gmail 수집
    try:
        gmail_items = await fetch_unread_gmail()
        raw_items.extend(gmail_items)
        log.info("ingest_node.gmail", count=len(gmail_items))
    except Exception as e:
        log.error("ingest_node.gmail_failed", error=str(e))

    # # Outlook 수집
    # try:
    #     outlook_items = await fetch_unread_outlook()
    #     raw_items.extend(outlook_items)
    #     log.info("ingest_node.outlook", count=len(outlook_items))
    # except Exception as e:
    #     log.error("ingest_node.outlook_failed", error=str(e))

    # Dedup 필터링 (Redis Message-ID 체크)
    deduped: list[MailItem] = []
    for item in raw_items:
        if not await is_duplicate(item["message_id"]):
            deduped.append(item)
            await mark_processed(item["message_id"])

    log.info("ingest_node.done", total=len(raw_items), after_dedup=len(deduped))

    return {
        "mail_items": deduped,
        "stats": {"ingested": len(deduped), "deduped_out": len(raw_items) - len(deduped)},
    }


# ── 2. Command Router Node ───────────────────────────────────────────────────

async def command_router_node(state: AgentState) -> dict:
    """
    트리거 종류에 따라 라우팅 결정
    - schedule: Ingest로
    - telegram_command: 자연어/슬래시 파싱 후 적절한 액션으로
    """
    if state["trigger"] == "schedule":
        return {}  # 그대로 Ingest → Classifier 흐름

    # Telegram 자연어 명령 파싱
    raw = state.get("user_intent", {}).get("raw_text", "")
    if not raw:
        return {"user_intent": {"action": "unknown", "params": {}, "raw_text": ""}}

    # /슬래시 명령은 정규식으로 즉시 처리
    if raw.startswith("/"):
        intent = _parse_slash_command(raw)
    else:
        # 자연어는 Gemini Flash로 파싱 (비용 최소화)
        intent = await _parse_natural_language(raw)

    log.info("command_router.parsed", action=intent["action"], params=intent["params"])
    return {"user_intent": intent}


def _parse_slash_command(text: str) -> UserIntent:
    """슬래시 명령 정규식 파싱"""
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    mapping = {
        "/summary": ("summary", {"date": arg or "today"}),
        "/search":  ("search",  {"query": arg}),
        "/skip":    ("skip",    {"source": arg}),
        "/settings":("settings",{"raw": arg}),
        "/resend":  ("resend",  {"query": arg}),
        "/status":  ("status",  {}),
    }
    action, params = mapping.get(cmd, ("unknown", {}))
    return {"action": action, "params": params, "raw_text": text}


async def _parse_natural_language(text: str) -> UserIntent:
    """Gemini Flash로 자연어 intent 추출"""
    llm = get_flash_llm()
    prompt = f"""다음 메시지의 의도와 파라미터를 JSON으로만 반환하세요.
action은 반드시 summary/search/skip/settings/resend/status/unknown 중 하나.

메시지: "{text}"

반환 형식:
{{"action": "...", "params": {{...}}}}"""

    response = await llm.ainvoke(prompt)
    try:
        parsed = json.loads(response.content)
        return {"action": parsed["action"], "params": parsed.get("params", {}), "raw_text": text}
    except Exception:
        return {"action": "unknown", "params": {}, "raw_text": text}


# ── 3. Pre-filter Node ───────────────────────────────────────────────────────

async def prefilter_node(state: AgentState) -> dict:
    """
    LLM 호출 전 규칙 기반으로 스킵 처리 (토큰 절감 핵심)
    - 광고/마케팅 발신자 패턴
    - User Preference의 스킵 목록
    - 제목 패턴 (구독 확인, 영수증 등)
    """
    from db.repository import get_skip_list
    skip_senders = await get_skip_list()

    filtered, skipped = [], []
    for item in state["mail_items"]:
        if _should_skip(item, skip_senders):
            skipped.append(item["message_id"])
        else:
            filtered.append(item)

    log.info("prefilter.done", kept=len(filtered), skipped=len(skipped))
    return {
        "mail_items": filtered,
        "stats": {"prefilter_skipped": len(skipped)},
    }


def _should_skip(item: MailItem, skip_senders: list[str]) -> bool:
    skip_keywords = ["unsubscribe confirm", "receipt", "invoice", "구독 확인"]
    subject_lower = item["subject"].lower()
    return (
        item["sender"] in skip_senders
        or any(k in subject_lower for k in skip_keywords)
    )


# ── 4. Classifier Node ───────────────────────────────────────────────────────

async def classifier_node(state: AgentState) -> dict:
    """
    Gemini Flash로 각 메일 분류:
    - content_type: text / image_only / excerpt_with_link / mixed
    - importance: high / medium / low / skip
    - newsletter_source: 발행처 식별
    """
    llm = get_flash_llm()
    classified = []

    for item in state["mail_items"]:
        try:
            result = await _classify_mail(llm, item)
            item.update(result)
        except Exception as e:
            item["error"] = f"classify_failed: {e}"
            item["content_type"] = "unknown"
            item["importance"] = "low"
        classified.append(item)

    return {"mail_items": classified}


async def _classify_mail(llm, item: MailItem) -> dict:
    prompt = f"""다음 이메일을 분석하고 JSON으로만 반환하세요. 절대 다른 텍스트 없이 JSON만 반환하세요.

발신자: {item['sender']}
제목: {item['subject']}
본문 앞 300자: {item['body_text'][:300]}
이미지 수: {len(item['image_urls'])}
링크 수: {len(item['links'])}

newsletter_source 결정 규칙:
- 발신자 이름 또는 이메일 도메인에서 발행처를 추출하세요
- 예: "TLDR Dev <dan@tldrnewsletter.com>" → "TLDR Dev"
- 예: "McKinsey <newsletter@mckinsey.com>" → "McKinsey"
- 예: "dan@tldrnewsletter.com" → "TLDR"
- 도메인에서 추출: substack.com → 제목이나 발신자 이름 사용
- 정말 알 수 없을 때만 "unknown" 사용

importance 결정 규칙:
- high: 비즈니스/전략/기술 인사이트가 담긴 McKinsey, HBR, MIT, 주요 리서치 기관
- medium: TLDR, 일반 기술 뉴스레터, LinkedIn 뉴스레터
- low: 마케팅, 프로모션, 일반 업데이트
- skip: 구독 확인, 영수증, 광고, 이벤트 초대

반환 형식 (JSON만, 다른 텍스트 없음):
{{
  "content_type": "text|image_only|excerpt_with_link|mixed",
  "importance": "high|medium|low|skip",
  "newsletter_source": "발행처명"
}}"""

    resp = await llm.ainvoke(prompt)
    
    # JSON 파싱 — Gemini가 마크다운 코드블록으로 감쌀 때 처리
    content = resp.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    
    return json.loads(content.strip())


# ── 5. Vision Node ───────────────────────────────────────────────────────────

async def vision_node(state: AgentState) -> dict:
    """
    이미지 전용 뉴스레터 처리
    Gemini 2.5 Pro Vision으로 이미지에서 텍스트 추출
    """
    llm = get_pro_llm()
    updated = []

    for item in state["mail_items"]:
        if item["content_type"] != "image_only":
            updated.append(item)
            continue

        try:
            extracted = await _extract_from_images(llm, item["image_urls"])
            item["extracted_text"] = extracted
        except Exception as e:
            item["error"] = f"vision_failed: {e}"
            item["extracted_text"] = ""

        updated.append(item)

    return {"mail_items": updated}


async def _extract_from_images(llm, image_urls: list[str]) -> str:
    """이미지 URL 목록을 Gemini Vision으로 텍스트 추출"""
    content = [{"type": "text", "text": "이 뉴스레터 이미지들의 핵심 내용을 텍스트로 추출해주세요."}]

    for url in image_urls[:5]:  # 최대 5장 처리
        content.append({
            "type": "image_url",
            "image_url": {"url": url},
        })

    msg = HumanMessage(content=content)
    resp = await llm.ainvoke([msg])
    return resp.content


# ── 6. Crawler Node ──────────────────────────────────────────────────────────

async def crawler_node(state: AgentState) -> dict:
    """
    excerpt_with_link 타입: 링크 접속 → 본문 추출
    - Paywall 감지 시 발췌본으로 폴백
    - Redis URL 캐시로 중복 크롤링 방지 (토큰 절감)
    """
    updated = []

    for item in state["mail_items"]:
        if item["content_type"] != "excerpt_with_link":
            updated.append(item)
            continue

        # 가장 유력한 링크 1개 선택 (첫 번째 본문 링크)
        target_url = item["links"][0] if item["links"] else None
        if not target_url:
            item["extracted_text"] = item["body_text"]
            updated.append(item)
            continue

        try:
            result = await crawl_url(target_url)
            if result["paywall"]:
                item["extracted_text"] = item["body_text"]  # 발췌본으로 폴백
                item["error"] = "paywall_detected"
                log.info("crawler.paywall", url=target_url)
            else:
                item["extracted_text"] = result["text"]
        except Exception as e:
            item["extracted_text"] = item["body_text"]
            item["error"] = f"crawl_failed: {e}"

        updated.append(item)

    return {"mail_items": updated}


# ── 7. Summarizer Node ───────────────────────────────────────────────────────

async def summarizer_node(state: AgentState) -> dict:
    """
    Gemini 2.5 Pro로 최종 요약 생성
    중요도별 요약 길이 조정
    """
    llm = get_pro_llm()
    summaries = []

    for item in state["mail_items"]:
        if item["importance"] == "skip":
            continue

        content = item.get("extracted_text") or item.get("body_text", "")
        if not content.strip():
            continue

        try:
            summary_text = await _summarize(llm, item, content)
            item["summary"] = summary_text
            summaries.append({
                "message_id": item["message_id"],
                "source": item["newsletter_source"],
                "importance": item["importance"],
                "summary": summary_text,
                "subject": item["subject"],
                "received_at": item["received_at"],
                "url": item["links"][0] if item.get("links") else "",  # 첫 번째 링크
            })
        except Exception as e:
            log.error("summarizer.failed", id=item["message_id"], error=str(e))

    return {"mail_items": state["mail_items"], "summaries": summaries}


async def _summarize(llm, item: MailItem, content: str) -> str:
    length_guide = {
        "high": "5-7문장으로 상세하게",
        "medium": "3-4문장으로",
        "low": "1-2문장으로 간략하게",
    }
    guide = length_guide.get(item["importance"], "3문장으로")

    # 긴 본문은 앞 8000자만 (토큰 절감)
    content_trimmed = content[:8000]

    prompt = f"""다음 뉴스레터를 한국어로 {guide} 요약해주세요.
발행처: {item['newsletter_source']}
제목: {item['subject']}

본문:
{content_trimmed}

요약:"""

    resp = await llm.ainvoke(prompt)
    return resp.content.strip()


# ── 8. Embed Node ────────────────────────────────────────────────────────────

async def embed_node(state: AgentState) -> dict:
    """
    요약문을 벡터로 변환해 PostgreSQL pgvector에 저장
    나중에 "AI 규제 관련 아티클 찾아줘" 같은 의미 검색에 활용
    """
    embeddings = get_embeddings()
    texts = [s["summary"] for s in state["summaries"] if s.get("summary")]

    if not texts:
        return {}

    vectors = await embeddings.aembed_documents(texts)

    # DB 저장 (요약 + 벡터 함께)
    for summary, vector in zip(state["summaries"], vectors):
        await save_summary({**summary, "embedding": vector})

    log.info("embed_node.done", count=len(texts))
    return {}


# ── 9. Formatter Node ────────────────────────────────────────────────────────

async def formatter_node(state: AgentState) -> dict:
    """
    Telegram 메시지 포맷팅
    - 중요도 순 정렬
    - Telegram Markdown 형식
    - 긴 메시지는 분할 (Telegram 4096자 제한)
    """
    summaries = sorted(
        state["summaries"],
        key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["importance"], 3)
    )

    if not summaries:
        return {"telegram_messages": ["오늘은 처리할 뉴스레터가 없습니다."]}

    messages = []
    current = f"📬 *뉴스레터 요약* — {_today_str()}\n총 {len(summaries)}건\n\n"

    for s in summaries:
        icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(s["importance"], "⚪")
        
        # 원문 링크 추가
        url = s.get("url", "")
        link_line = f"\n🔗 [원문 보기]({url})" if url else ""
        
        block = (
            f"{icon} *{s['source']}*\n"
            f"_{s['subject']}_\n"
            f"{s['summary']}"
            f"{link_line}\n\n"
        )

        # 4096자 초과 시 분할
        if len(current) + len(block) > 4000:
            messages.append(current)
            current = block
        else:
            current += block

    if current:
        messages.append(current)

    # 처리 통계 추가
    stats = state.get("stats", {})
    messages.append(
        f"📊 처리 현황: 수집 {stats.get('ingested', 0)}건 | "
        f"요약 {len(summaries)}건 | "
        f"스킵 {stats.get('prefilter_skipped', 0)}건"
    )

    return {"telegram_messages": messages}


def _today_str() -> str:
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d")


# ── 10. Telegram Sender Node ─────────────────────────────────────────────────

async def telegram_sender_node(state: AgentState) -> dict:
    """
    Telegram Bot API로 메시지 전송
    """
    from tools.telegram import send_messages
    messages = state.get("telegram_messages", [])

    if not messages:
        return {}

    await send_messages(messages)
    log.info("telegram_sender.done", count=len(messages))
    return {}


# ── 11. Search Handler Node ──────────────────────────────────────────────────

async def search_handler_node(state: AgentState) -> dict:
    """
    Telegram 검색 명령 처리
    pgvector 의미 검색 → 결과 포맷 → Telegram 전송
    """
    intent = state.get("user_intent", {})
    query = intent.get("params", {}).get("query", "")

    if not query:
        return {"telegram_messages": ["검색어를 입력해주세요."]}

    # 쿼리를 임베딩으로 변환 후 유사도 검색
    embeddings = get_embeddings()
    query_vector = await embeddings.aembed_query(query)
    results = await search_similar(query_vector, top_k=5)

    if not results:
        return {"telegram_messages": [f"'{query}' 관련 아티클을 찾지 못했습니다."]}

    msg = f"🔍 *'{query}' 검색 결과* ({len(results)}건)\n\n"
    for r in results:
        msg += f"• *{r['source']}* ({r['received_at'][:10]})\n{r['summary'][:200]}...\n\n"

    return {"telegram_messages": [msg]}


# ── 12. Error Handler Node ───────────────────────────────────────────────────

async def error_handler_node(state: AgentState) -> dict:
    """
    치명적 오류 발생 시 Telegram으로 알림
    """
    error = state.get("fatal_error", "알 수 없는 오류")
    log.error("error_handler", error=error)
    return {
        "telegram_messages": [f"⚠️ 에이전트 오류 발생\n```{error}```\n확인이 필요합니다."]
    }
