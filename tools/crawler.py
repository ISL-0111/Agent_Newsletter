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
    cache_key = f"crawl:{url}"
    try:
        cached = await _redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            html = resp.text
    except Exception as e:
        return {"text": "", "paywall": False, "error": str(e)}

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    paywall = any(signal in text.lower() for signal in PAYWALL_SIGNALS)
    if len(text) < 300:
        paywall = True

    result = {"text": text[:15000], "paywall": paywall}
    try:
        await _redis.setex(cache_key, 86400, json.dumps(result))
    except Exception:
        pass
    return result