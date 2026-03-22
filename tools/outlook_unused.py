"""tools/outlook.py — Microsoft Graph API 연동"""
import httpx
from agents.state import MailItem
from config.settings import settings


async def fetch_unread_outlook() -> list[MailItem]:
    token = await _get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://graph.microsoft.com/v1.0/me/messages",
            headers=headers,
            params={
                "$filter": "isRead eq false",
                "$top": 50,
                "$select": "id,subject,from,receivedDateTime,body,internetMessageId",
            },
        )
        resp.raise_for_status()
        messages = resp.json().get("value", [])

    items = []
    for msg in messages:
        item = _parse_outlook_message(msg)
        items.append(item)
        # 읽음 처리
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"https://graph.microsoft.com/v1.0/me/messages/{msg['id']}",
                headers=headers,
                json={"isRead": True},
            )

    return items


async def _get_access_token() -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{settings.outlook_tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": settings.outlook_refresh_token,
                "client_id": settings.outlook_client_id,
                "client_secret": settings.outlook_client_secret,
                "scope": "https://graph.microsoft.com/Mail.ReadWrite",
            },
        )
        return resp.json()["access_token"]


def _parse_outlook_message(msg: dict) -> MailItem:
    from bs4 import BeautifulSoup
    html = msg.get("body", {}).get("content", "")
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    links = [a["href"] for a in soup.find_all("a", href=True)]
    images = [img["src"] for img in soup.find_all("img", src=True)]

    return MailItem(
        message_id=msg.get("internetMessageId", msg["id"]),
        source="outlook",
        subject=msg.get("subject", ""),
        sender=msg.get("from", {}).get("emailAddress", {}).get("address", ""),
        received_at=msg.get("receivedDateTime", ""),
        body_text=text,
        body_html=html,
        image_urls=images,
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
