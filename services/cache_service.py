import hashlib
import json
import logging
import re
from typing import Optional, Dict, Any
from config import settings
from db.database import get_cached_essay_by_hash

logger = logging.getLogger(__name__)

# Optional Redis connection
_redis_client = None

async def get_redis():
    global _redis_client
    if settings.REDIS_URL and _redis_client is None:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await _redis_client.ping()
            logger.info("Connected to Redis cache successfully.")
        except Exception as e:
            logger.warning(f"Could not connect to Redis at {settings.REDIS_URL}: {e}. Falling back to DB cache.")
            _redis_client = None
    return _redis_client


def compute_essay_hash(text: str) -> str:
    """
    Normalizes text (lowercased, excess whitespace stripped) and computes SHA-256 hash.
    Ensures identical essays get the exact same hash.
    """
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def get_cached_evaluation(essay_hash: str) -> Optional[Dict[str, Any]]:
    """
    Checks Redis first, then Database. Returns parsed feedback dict if found.
    """
    r = await get_redis()
    if r:
        try:
            cached_data = await r.get(f"essay_cache:{essay_hash}")
            if cached_data:
                logger.info(f"Cache HIT (Redis) for hash: {essay_hash[:10]}...")
                return json.loads(cached_data)
        except Exception as e:
            logger.warning(f"Redis get error: {e}")

    # Fallback to Database cache
    db_essay = await get_cached_essay_by_hash(essay_hash)
    if db_essay and db_essay.feedback_json:
        logger.info(f"Cache HIT (Database) for hash: {essay_hash[:10]}...")
        try:
            feedback = json.loads(db_essay.feedback_json)
            # Write back to Redis if available
            if r:
                await r.setex(f"essay_cache:{essay_hash}", settings.CACHE_TTL_SECONDS, db_essay.feedback_json)
            return feedback
        except Exception as e:
            logger.warning(f"Error parsing cached feedback JSON from DB: {e}")

    return None


async def save_cached_evaluation(essay_hash: str, feedback: Dict[str, Any]):
    """
    Caches evaluation in Redis for CACHE_TTL_SECONDS.
    """
    r = await get_redis()
    if r:
        try:
            await r.setex(
                f"essay_cache:{essay_hash}",
                settings.CACHE_TTL_SECONDS,
                json.dumps(feedback, ensure_ascii=False),
            )
            logger.info(f"Cached result in Redis for hash: {essay_hash[:10]}...")
        except Exception as e:
            logger.warning(f"Redis set error: {e}")
