# MISSION_ANSWERS — Part 6: Final Project

## Kết quả `check_production_ready.py`

Chạy đầy đủ (có Docker) ngày 2026-11-26, Windows 10, Docker Desktop 29.9.3:

```
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅  Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 40/40 checks passed
```

## Thiết kế theo từng tiêu chí

| # | Tiêu chí | Cách làm |
|---|----------|----------|
| 1 | Dockerfile | Hai stage: `builder` cài dependencies vào `/install`; `runtime` (python:3.11-slim) chỉ copy kết quả, chạy bằng user `app`, có `HEALTHCHECK` gọi `/health`. CMD dùng `sh -c "exec uvicorn ... --port ${PORT:-8000}"` để uvicorn là PID 1 và nhận SIGTERM. Image 238 MB. |
| 2 | docker-compose | Service `agent` (build từ Dockerfile, `REDIS_URL=redis://redis:6379/0`, `depends_on` redis healthy) và `redis:7-alpine` có healthcheck. `.env` được nạp với `required: false`. |
| 3 | .dockerignore | Loại `.env`, `.env.*` (giữ `.env.example`), `__pycache__`, `venv`, `.git`, `*.md`, `benchmark-observability/`. |
| 4 | `/health` | Luôn 200 khi process chạy, không phụ thuộc Redis (liveness). |
| 5 | `/ready` | Gọi `redis_healthy()` (ping, timeout 1 s): Redis không kết nối được → 503. |
| 6 | API key | `APIKeyHeader` + `hmac.compare_digest`. Thiếu hoặc sai → 401. Không có `AGENT_API_KEY` thì mọi request bị 401. |
| 7 | Rate limit | Sliding window trên Redis sorted set, chạy trong **một Lua script** nên atomic. Vượt giới hạn → 429 + `Retry-After`. Redis lưu hash của key (không lưu key thật), nên restart agent vẫn giữ state. |
| 8 | Cost guard | Chi phí token cộng dồn vào Redis theo key và ngày UTC (`INCRBYFLOAT`, TTL 2 ngày). `check_budget()` trước LLM → 402 nếu đã vượt `DAILY_BUDGET_USD`; `record_cost()` sau LLM. |
| 9 | Config | `app/config.py` đọc mọi biến từ env (`load_dotenv` chỉ nạp khi có `.env`, biến môi trường thật vẫn được ưu tiên). `.env.example` liệt kê đủ biến, không có secret thật. |
| 10 | Log JSON | `JsonFormatter` xuất mỗi dòng log thành một JSON object; access log có `method`, `path`, `status`, `ms`. Không log API key hay nội dung câu hỏi. |
| 11 | Graceful shutdown | Không đăng ký SIGTERM handler riêng (để không đè handler của uvicorn). Uvicorn ngừng nhận kết nối mới, chờ request đang chạy xong, rồi chạy phần shutdown trong `lifespan`. |
| 12 | Deploy config | `railway.toml`: `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`. Port đọc từ `PORT` trong CMD. |

## Vì sao `/health` trả 200 còn `/ready` trả 503 khi Redis chết?

- **`/health` (liveness)** trả lời "process còn sống không?". Nếu Redis chết mà `/health` trả non-200, platform sẽ **restart container** — việc này không sửa được Redis và còn làm mất request đang chạy. Vì vậy `/health` không kiểm tra dependency bên ngoài.
- **`/ready` (readiness)** trả lời "có nên gửi traffic vào instance này không?". Khi Redis chết, instance không rate limit và không tính cost được, nên không nên nhận request mới. 503 làm load balancer tạm ngừng route vào instance, trong khi container vẫn chạy và sẽ có lại khi Redis trở về.

## AI log

- **Hỏi:** nhờ AI hoàn thành các TODO trong `app/` (config, auth, rate limiter, cost guard, redis client, main), Dockerfile, docker-compose, `.dockerignore`, `.env.example`, `railway.toml` theo đúng yêu cầu của `check_production_ready.py`.
- **Nhận:** code cho các file trên và giải thích thiết kế.
- **Tự sửa và tự kiểm tra:** đọc toàn bộ phần kiểm tra trong checker để biết chính xác nó cần gì; chạy `--static-only` (26/26 checks) và chạy đầy đủ (40/40 checks, 11/12 tiêu chí). Kiểm tra SIGTERM bằng script tay trong Linux container. Lưu ý: khi cài `requirements.txt` vào Python toàn cục, pip báo xung đột phiên bản (`pydantic`, `python-dotenv`) với `pydantic-graph` và `pydantic-settings` đã cài sẵn; nên dùng virtualenv riêng cho lab.
