"""tools/crawler.py — 링크 본문 추출 + paywall 감지"""
import httpx
import redis.asyncio as aioredis
import json
from bs4 import BeautifulSoup
from config.settings import settings

_redis = aioredis.from_url(settings.redis_url)

PAYWALL_SIGNALS = [
    "subscribe to read", "sign in to read", "premium content",
    "구독이 필요", "로그인이 필요", "전체 기사는 유료",
]


async def crawl_url(url: str) -> dict:
    """URL 크롤링. Redis에 24시간 캐시."""
    cache_key = f"crawl:{url}"
    cached = await _redis.get(cache_key)
    if cached:
        return json.loads(cached)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            html = resp.text
    except Exception as e:
        return {"text": "", "paywall": False, "error": str(e)}

    soup = BeautifulSoup(html, "html.parser")

    # 불필요한 태그 제거
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)

    # Paywall 감지
    paywall = any(signal in text.lower() for signal in PAYWALL_SIGNALS)
    # 본문이 너무 짧으면 paywall 의심
    if len(text) < 300:
        paywall = True

    result = {"text": text[:15000], "paywall": paywall}

    # 캐시 저장 (TTL 24시간)
    await _redis.setex(cache_key, 86400, json.dumps(result))
    return result


# ─────────────────────────────────────────────────────────────────────────────
"""tools/dedup.py — Redis 기반 중복 메일 처리 방지"""


async def is_duplicate(message_id: str) -> bool:
    key = f"dedup:{message_id}"
    return bool(await _redis.exists(key))


async def mark_processed(message_id: str):
    key = f"dedup:{message_id}"
    await _redis.setex(key, 86400 * 30, "1")  # 30일 보존


# ─────────────────────────────────────────────────────────────────────────────
"""tools/telegram.py — Telegram Bot 메시지 전송"""
from telegram import Bot
from config.settings import settings

_bot = Bot(token=settings.telegram_bot_token)


async def send_messages(messages: list[str]):
    for msg in messages:
        await _bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=msg,
            parse_mode="Markdown",
        )
