import redis.asyncio as aioredis
from config.settings import settings

_redis = aioredis.from_url(settings.redis_url)

async def is_duplicate(message_id: str) -> bool:
    key = f"dedup:{message_id}"
    return bool(await _redis.exists(key))

async def mark_processed(message_id: str):
    key = f"dedup:{message_id}"
    await _redis.setex(key, 86400 * 30, "1")