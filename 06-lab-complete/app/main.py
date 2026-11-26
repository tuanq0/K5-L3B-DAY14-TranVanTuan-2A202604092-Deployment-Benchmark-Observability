"""
Production AI Agent — Part 6 Final Project.

Chạy:  uvicorn app.main:app --workers 2   (từ thư mục 06-lab-complete)
Chấm:  python check_production_ready.py
"""
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ──────────────────────────────────────────────────────────
# Structured logging: mỗi dòng log là 1 JSON object
# ──────────────────────────────────────────────────────────
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Field truyền qua extra={...} được đưa vào JSON
        for k, v in record.__dict__.items():
            if k not in _STANDARD_ATTRS and not k.startswith("_"):
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
logger = logging.getLogger("agent")


# ──────────────────────────────────────────────────────────
# Lifecycle — graceful shutdown
# uvicorn bắt SIGTERM, ngừng nhận kết nối mới, chờ request đang chạy xong,
# rồi mới chạy phần shutdown ở đây và thoát với exit code 0.
# (Không đăng ký signal handler riêng để không đè lên handler của uvicorn.)
# ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", extra={"event": "startup", "env": settings.environment, "port": settings.port})
    yield
    logger.info("shutdown", extra={"event": "shutdown"})


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    logger.info(
        "request",
        extra={
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


# ──────────────────────────────────────────────────────────
# Health & readiness
# ──────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy, kể cả khi Redis chết."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: 503 khi Redis không kết nối được — load balancer ngừng gửi traffic."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not reachable")
    return {"ready": True}


# ──────────────────────────────────────────────────────────
# Agent endpoint: auth → rate limit → cost guard → LLM → ghi cost
# ──────────────────────────────────────────────────────────
@app.post("/ask")
def ask_agent(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget(api_key)

    answer = llm_ask(body.question)

    # Mock token count (≈ 2 token mỗi từ)
    input_tokens = len(body.question.split()) * 2
    output_tokens = len(answer.split()) * 2
    cost = record_cost(api_key, input_tokens, output_tokens)

    return {"question": body.question, "answer": answer, "cost_usd": round(cost, 8)}
