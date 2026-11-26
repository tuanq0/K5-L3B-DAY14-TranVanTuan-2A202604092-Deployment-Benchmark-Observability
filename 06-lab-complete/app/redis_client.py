"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • Không ping Redis lúc import — app vẫn khởi động được khi Redis chưa sẵn sàng.
  • redis_healthy() dùng cho GET /ready: Redis không kết nối được → False.
"""
import logging

import redis

from app.config import settings

logger = logging.getLogger("agent.redis")

r = None
if settings.redis_url:
    try:
        r = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    except ValueError:
        logger.error("invalid REDIS_URL", extra={"event": "config_error"})
        r = None


def redis_healthy() -> bool:
    if r is None:
        return False
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
