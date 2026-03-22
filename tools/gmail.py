
"""tools/gmail.py — Gmail API 연동"""
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from agents.state import MailItem
from config.settings import settings
import base64, email


async def fetch_unread_gmail() -> list[MailItem]:
    creds = Credentials(
        token=None,
        refresh_token=settings.gmail_refresh_token,
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    service = build("gmail", "v1", credentials=creds)

    # 읽지 않은 메일 + 뉴스레터 레이블
    # - fetch_limit: 이번 실행에서 처리할 최대 메일 수 (스케줄이 하루 1회면 사실상 '하루 처리량')
    # - query: Gmail 검색 쿼리 (예: is:unread (category:updates OR label:newsletters))
    fetch_limit = int(settings.gmail_fetch_limit)
    query = settings.gmail_query

    messages: list[dict] = []
    page_token: str | None = None
    per_page = min(500, fetch_limit)

    while len(messages) < fetch_limit:
        req = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=per_page,
            pageToken=page_token,
        )
        results = req.execute()
        messages.extend(results.get("messages", []))
        page_token = results.get("nextPageToken")
        if not page_token:
            break

    messages = messages[:fetch_limit]
    items: list[MailItem] = []

    for msg_ref in messages:
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()
        item = _parse_gmail_message(msg)
        items.append(item)

        # 처리 완료 후 읽음 처리
        service.users().messages().modify(
            userId="me", id=msg_ref["id"],
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    return items


def _parse_gmail_message(msg: dict) -> MailItem:
    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    body_text, body_html, image_urls, links = _extract_parts(msg["payload"])

    return MailItem(
        message_id=headers.get("Message-ID", msg["id"]),
        source="gmail",
        subject=headers.get("Subject", ""),
        sender=headers.get("From", ""),
        received_at=headers.get("Date", ""),
        body_text=body_text,
        body_html=body_html,
        image_urls=image_urls,
        links=links,
        content_type="unknown",
        importance="medium",
        newsletter_source="unknown",
        extracted_text="",
        summary="",
        embedding=[],
        error=None,
        retry_count=0,
    )


def _extract_parts(payload: dict) -> tuple:
    """재귀적으로 MIME 파트에서 텍스트·이미지·링크 추출"""
    body_text, body_html, image_urls, links = "", "", [], []

    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        body_text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    elif payload.get("mimeType") == "text/html":
        data = payload.get("body", {}).get("data", "")
        body_html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(body_html, "html.parser")
        body_text = soup.get_text(separator=" ", strip=True)
        links = [a["href"] for a in soup.find_all("a", href=True)]
        image_urls = [img["src"] for img in soup.find_all("img", src=True)]

    for part in payload.get("parts", []):
        t, h, i, l = _extract_parts(part)
        body_text = body_text or t
        body_html = body_html or h
        image_urls.extend(i)
        links.extend(l)

    return body_text, body_html, image_urls, links
