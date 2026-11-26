"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis (sorted set) để mọi worker / instance dùng chung
    và vẫn còn sau khi restart agent.

Toàn bộ bước "dọn → đếm → thêm" chạy trong một Lua script nên atomic,
hai request đồng thời không thể cùng lọt qua khi còn đúng 1 slot.
"""
import hashlib
import math
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60

_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, oldest[2]}
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window)
return {1, 0}
"""

_script = r.register_script(_SLIDING_WINDOW) if r is not None else None


def _bucket(api_key: str) -> str:
    # Không lưu API key thật trong Redis — chỉ lưu hash.
    return "rl:" + hashlib.sha256(api_key.encode()).hexdigest()[:32]


def check_rate_limit(key: str) -> None:
    if _script is None:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable (no Redis)")

    now = time.time()
    limit = settings.rate_limit_per_minute
    try:
        allowed, oldest = _script(
            keys=[_bucket(key)],
            args=[now, WINDOW_SECONDS, limit, f"{now}:{uuid.uuid4().hex}"],
        )
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable (Redis down)")

    if int(allowed) == 1:
        return

    retry_after = max(1, math.ceil(float(oldest) + WINDOW_SECONDS - now))
    raise HTTPException(
        status_code=429,
        detail={"error": "Rate limit exceeded", "limit_per_minute": limit},
        headers={"Retry-After": str(retry_after)},
    )
