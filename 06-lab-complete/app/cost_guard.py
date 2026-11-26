"""
Cost guard (tiêu chí 8).

  • Chi phí LLM (tính theo token) được cộng dồn vào Redis theo API key và theo ngày (UTC).
  • check_budget() gọi TRƯỚC khi gọi LLM: đã vượt DAILY_BUDGET_USD → HTTP 402.
  • record_cost() gọi SAU khi gọi LLM.
"""
import hashlib
import time

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_TTL_SECONDS = 2 * 24 * 3600  # giữ 2 ngày để không phình Redis


def _budget_key(api_key: str) -> str:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    digest = hashlib.sha256(api_key.encode()).hexdigest()[:32]
    return f"cost:{digest}:{day}"


def check_budget(api_key: str) -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → HTTP 402."""
    if r is None:
        raise HTTPException(status_code=503, detail="Cost guard unavailable (no Redis)")
    try:
        spent = float(r.get(_budget_key(api_key)) or 0)
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Cost guard unavailable (Redis down)")

    budget = settings.daily_budget_usd
    if spent >= budget:
        raise HTTPException(
            status_code=402,
            detail={"error": "Daily budget exceeded", "spent_usd": spent, "budget_usd": budget},
        )


def record_cost(api_key: str, input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí request vào tổng và trả về chi phí request."""
    cost = (input_tokens / 1000 * PRICE_INPUT_PER_1K
            + output_tokens / 1000 * PRICE_OUTPUT_PER_1K)
    key = _budget_key(api_key)
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, _TTL_SECONDS)
        pipe.execute()
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Cost guard unavailable (Redis down)")
    return cost
