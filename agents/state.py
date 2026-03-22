"""
AgentState — LangGraph 전체 노드가 공유하는 상태 객체
모든 노드는 이 State를 읽고 업데이트한다.
"""
from typing import TypedDict, Literal, Optional


# ── 개별 메일 아이템 ─────────────────────────────────────────────────────────

class MailItem(TypedDict):
    # 식별
    message_id: str
    source: Literal["gmail", "outlook"]
    subject: str
    sender: str
    received_at: str

    # 원본 콘텐츠
    body_text: str
    body_html: str
    image_urls: list[str]
    links: list[str]

    # 분류 결과
    content_type: Literal["text", "image_only", "excerpt_with_link", "mixed", "unknown"]
    importance: Literal["high", "medium", "low", "skip"]
    newsletter_source: str

    # 처리 결과
    extracted_text: str
    summary: str
    embedding: list[float]

    # 오류 추적
    error: Optional[str]
    retry_count: int


# ── 사용자 명령 ──────────────────────────────────────────────────────────────

class UserIntent(TypedDict):
    action: Literal[
        "summary",
        "search",
        "skip",
        "settings",
        "resend",
        "status",
        "unknown",
    ]
    params: dict
    raw_text: str


# ── 전체 Agent State ─────────────────────────────────────────────────────────

class AgentState(TypedDict):
    trigger: Literal["schedule", "telegram_command"]
    user_intent: Optional[UserIntent]
    mail_items: list[MailItem]        # Annotated 제거 → 중복 누적 방지
    summaries: list[dict]             # Annotated 제거 → 중복 누적 방지
    telegram_messages: list[str]      # Annotated 제거
    fatal_error: Optional[str]
    stats: dict