import asyncio
import json
import logging
from typing import Optional, Dict, Any
from config import settings
from services.cache_service import get_redis

logger = logging.getLogger(__name__)

REDIS_QUEUE_KEY = "essay_queue:pending"

# Fallback in-memory queue for zero-dependency local development
_memory_queue = asyncio.Queue()


class QueueService:
    @staticmethod
    async def enqueue(payload: Dict[str, Any]) -> int:
        """
        Pushes a new essay evaluation job to the queue.
        Returns the current position/length of the queue.
        """
        r = await get_redis()
        if r:
            try:
                length = await r.rpush(REDIS_QUEUE_KEY, json.dumps(payload, ensure_ascii=False))
                logger.info(f"Task enqueued to Redis. Queue length: {length}")
                return length
            except Exception as e:
                logger.warning(f"Failed to enqueue to Redis: {e}. Falling back to memory queue.")

        await _memory_queue.put(payload)
        length = _memory_queue.qsize()
        logger.info(f"Task enqueued to in-memory queue. Queue size: {length}")
        return length

    @staticmethod
    async def dequeue(timeout: int = 2) -> Optional[Dict[str, Any]]:
        """
        Pulls a job from the queue (blocking with timeout).
        """
        r = await get_redis()
        if r:
            try:
                # blpop returns tuple (key, value) or None
                item = await r.blpop(REDIS_QUEUE_KEY, timeout=timeout)
                if item:
                    _, raw_data = item
                    return json.loads(raw_data)
            except Exception as e:
                logger.warning(f"Redis dequeue error: {e}")

        # Fallback to memory queue
        try:
            return await asyncio.wait_for(_memory_queue.get(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return None

    @staticmethod
    async def get_queue_size() -> int:
        r = await get_redis()
        if r:
            try:
                return await r.llen(REDIS_QUEUE_KEY)
            except Exception:
                pass
        return _memory_queue.qsize()


queue_service = QueueService()
