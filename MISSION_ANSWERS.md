### 1. Mission Answers (40 points)

Create a file `MISSION_ANSWERS.md` with your answers to all exercises:

```markdown
# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found
Tìm được 9 vấn đề (yêu cầu tối thiểu 5):

| # | Anti-pattern | Dòng trong `develop/app.py` | Vì sao nguy hiểm |
|---|--------------|-----------------------------|------------------|
| 1 | API key hardcode | L17: `OPENAI_API_KEY = "sk-..."` | Push lên Git là lộ key ngay, và key nằm trong lịch sử commit dù sau này có xóa |
| 2 | Database URL có mật khẩu | L18: `postgresql://admin:password123@...` | Lộ thông tin đăng nhập DB; ai đọc code cũng vào được DB |
| 3 | Debug bật cứng | L21: `DEBUG = True` | Production chạy ở chế độ debug, lộ thông tin nội bộ |
| 4 | Config cứng, không đổi được | L22: `MAX_TOKENS = 500` | Muốn đổi phải sửa code và deploy lại |
| 5 | Log ra secret | L34: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | Secret nằm trong log, log thường được gửi đi nhiều nơi |
| 6 | Dùng `print` thay vì logging | L33, L38 | Không có level, không có timestamp, không parse được bằng Datadog/Loki |
| 7 | Không có health check | L42–43 | Platform không biết agent đã chết để restart |
| 8 | Port cố định, không đọc `PORT` | L45–46, L52 | Railway/Render inject `PORT` khác 8000 nên app không nhận được traffic |
| 9 | Host `localhost`, reload bật | L51, L53 | `localhost` không nhận kết nối từ ngoài container; `reload=True` làm chậm và không ổn định trong production |

Ngoài ra, không có xử lý SIGTERM/graceful shutdown: khi platform tắt container, request đang chạy bị cắt ngang.


### Exercise 1.3: Comparison table
Bảng so sánh (đọc từ `production/app.py`, `production/config.py`, `production/.env.example`):

| Feature | Develop | Production | Why Important? |
|---------|--------------------|--------------------------|---------------------|
| Config | Hardcode trong code (`DEBUG = True`, `MAX_TOKENS = 500`) | Tập trung trong `config.py`, mỗi giá trị đọc từ env var (`PORT`, `DEBUG`, `OPENAI_API_KEY`, `MAX_TOKENS`, `AGENT_API_KEY`, `ALLOWED_ORIGINS`...) với giá trị mặc định | Cùng một image chạy được dev, staging, production chỉ bằng cách đổi env var; không phải build lại |
| Secrets | `OPENAI_API_KEY` và `DATABASE_URL` có sẵn trong code | Không có secret trong code; `config.py` để trống `OPENAI_API_KEY` và `AGENT_API_KEY` mặc định | Code có thể public mà không lộ key. Key bị lộ thì xoay key được mà không cần sửa code |
| Validation | Không có | `Settings.validate()` cảnh báo khi thiếu `OPENAI_API_KEY`, và **từ chối khởi động** nếu `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` | Fail fast: lỗi cấu hình lộ ra ngay lúc deploy, không để agent chạy ngầm với cấu hình sai |
| Port / host | Cố định `localhost:8000` | `host` mặc định `0.0.0.0`, `port` lấy từ `PORT` | Container chỉ nhận traffic từ ngoài khi bind `0.0.0.0`; Railway/Render chọn port qua `PORT` |
| Debug / reload | `DEBUG = True`, `reload=True` cứng | `DEBUG` đọc từ env (mặc định `false`); `reload=settings.debug` | Reload và log debug trong production làm chậm và lộ thông tin |
| Health check | Không có | `GET /health` (liveness: trả uptime, version), `GET /ready` (readiness: 503 khi chưa sẵn sàng), `GET /metrics` | Platform dùng `/health` để restart container chết; load balancer dùng `/ready` để chỉ route traffic vào instance đã sẵn sàng |
| Logging | `print()`, có log ra secret | `logging` với format, log dạng JSON (`event`, `question_length`, `client_ip`...); **không log secret** | Log JSON search và lọc được trong Datadog/Loki; không lộ secret trong log |
| Shutdown | Tắt đột ngột, không xử lý signal | `lifespan` đánh dấu `is_ready = False` khi tắt và log; có handler SIGTERM | Platform báo SIGTERM trước khi kill; agent ngừng nhận request mới và có cơ hội hoàn thành request đang chạy |
| CORS | Không có | `CORSMiddleware` với `allow_origins` lấy từ `ALLOWED_ORIGINS` | Chỉ cho frontend được phép gọi API từ trình duyệt |


## Part 2: Docker

### Exercise 2.1: Dockerfile questions
1. Base image: `python:3.11` — image Python đầy đủ (full distribution, khoảng 1 GB). Nó chứa cả compiler, tool build và nhiều package không cần cho lúc chạy.
2. Working directory: `/app` (dòng `WORKDIR /app`). Mọi lệnh `COPY` và `RUN` sau đó chạy trong thư mục này, và process khi start cũng bắt đầu ở đây.
3. **Tại sao `COPY requirements.txt` trước?** Docker cache từng layer theo nội dung đầu vào. Nếu chỉ `app.py` đổi, layer `pip install` vẫn được dùng lại từ cache vì `requirements.txt` không đổi, nên build nhanh hơn nhiều. Nếu copy cả source trước, mỗi lần sửa code sẽ cài lại toàn bộ dependencies.
4. **CMD vs ENTRYPOINT khác nhau thế nào?**
   - `CMD` là lệnh mặc định, và `docker run <image> <lệnh khác>` sẽ **thay thế** hoàn toàn nó (ví dụ `docker run -it my-agent bash`).
   - `ENTRYPOINT` là executable cố định; tham số truyền vào `docker run` sẽ được **nối thêm** vào sau nó, không thay thế.
   - Thường dùng: `ENTRYPOINT ["python"]` + `CMD ["app.py"]` để có một lệnh cố định và có thể đổi tham số mặc định.

### Exercise 2.3: Image size comparison
- Develop: 1.67 GB
- Production: 240 MB
- Difference: 85.6%

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment
- URL: https://magnificent-magic-production-d94b4ced.up.railway.app/
- Screenshot: [Service running](screenshots/running.png)

### So sánh `railway.toml` và `render.yaml`

Lưu ý: `render.yaml` trong `06-lab-complete/` vẫn là bản TODO, nên phần so sánh dùng `03-cloud-deployment/render/render.yaml` làm mẫu Render. `railway.toml` là file đang dùng để deploy agent Part 6.

| Mục | `railway.toml` (06) | `render.yaml` (03) | Khác nhau ở đâu |
|-----|---------------------|--------------------|-----------------|
| Cách build | `builder = "DOCKERFILE"`, dùng `Dockerfile` multi-stage | `runtime: python`, `buildCommand: pip install ...` | Railway đóng gói bằng Docker, Render sample build trực tiếp không qua image |
| Lệnh chạy | Lấy từ `CMD` của Dockerfile (`exec uvicorn ... $PORT`) | `startCommand` khai báo trong file | Railway không cần khai báo lệnh chạy vì Dockerfile đã có |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 30` | `healthCheckPath: /health` | Tương đương; tên khóa khác nhau |
| Restart | `restartPolicyType = "ON_FAILURE"` | Không khai báo trong sample | Railway khai báo tường minh |
| Secret | Không ghi trong file; đặt bằng `railway variables set` | Khai báo tên trong `envVars` với `sync: false` hoặc `generateValue: true` | Render cho phép khai báo secret trong file (không có giá trị) để commit; Railway tách secret ra khỏi file |
| Redis | Thêm bằng dashboard, tham chiếu qua `${{Redis.REDIS_URL}}` | Khai báo `type: redis` trong cùng file | Render mô tả toàn bộ hạ tầng (web + Redis) trong một file; Railway tách việc tạo Redis ra khỏi file |
| Khu vực, gói | Chọn trên dashboard | `region`, `plan` nằm trong file | Render là infrastructure-as-code đầy đủ hơn |
| Tự deploy | Chạy `railway up` hoặc kết nối GitHub | `autoDeploy: true` | Render tự deploy khi push, theo cấu hình trong file |

**Vì sao khác nhau:** `railway.toml` cấu hình một service build từ Dockerfile và được CLI đẩy lên, nên nhanh cho MVP (dưới 5 phút). `render.yaml` là Blueprint khai báo toàn bộ hạ tầng (web service, Redis, region, plan) và commit được vào repo, nên tái tạo được môi trường nhưng phải viết nhiều hơn. Với lab này, Railway ít cấu hình hơn; Render phù hợp hơn khi cần quản lý nhiều tài nguyên có version control.

### Exercise 3.3: Pipeline Cloud Run (đọc `cloudbuild.yaml` và `service.yaml`)

Pipeline `cloudbuild.yaml` có 4 bước theo thứ tự: chạy test (`pytest tests/`), build image tag theo commit SHA và `latest` (dùng `--cache-from` để tận dụng layer cache), push image lên `gcr.io`, rồi deploy lên Cloud Run ở `asia-southeast1` với `min-instances=1`, `max-instances=10`, 512Mi RAM, và `OPENAI_API_KEY` lấy từ Secret Manager. `service.yaml` khai báo cùng service dạng IaC, với liveness probe trên `/health`, startup probe trên `/ready`, và `containerConcurrency: 80`. Vấn đề cần lưu ý: thư mục `production-cloud-run/` không có thư mục `tests/`, nên bước test sẽ fail nếu chạy đúng như file; cấu hình deploy cũng nằm ở hai nơi (flag trong `cloudbuild.yaml` và `service.yaml`) và có thể lệch nhau, ví dụ `AGENT_API_KEY` chỉ có trong `service.yaml`.

## Part 4: API Security

## Exercise 4.1 — API Key authentication (`develop/app.py`)

**API key được check ở đâu?** Trong dependency `verify_api_key` (dòng 39–54), được gắn vào `/ask` qua `Depends(verify_api_key)` (dòng 70). Key lấy từ header `X-API-Key` qua `APIKeyHeader`, so sánh với `AGENT_API_KEY` đọc từ env (dòng 35).

**Sai key thì sao?**
- Không có header → **401** `Missing API key…`
- Có header nhưng sai → **403** `Invalid API key.`

**Rotate key thế nào?** Đổi biến môi trường `AGENT_API_KEY` rồi restart process. Code không hỗ trợ nhiều key cùng lúc, nên khi rotate sẽ có một khoảng thời gian client cũ bị 403. Cách làm tốt hơn: chấp nhận danh sách key (key cũ và key mới) trong một khoảng chuyển tiếp, rồi bỏ key cũ.

Kết quả chạy (`AGENT_API_KEY=secret-key-123`, port 8011):

```
POST /ask  (không key)        → HTTP/1.1 401  {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
POST /ask  X-API-Key: secret-key-123 → HTTP/1.1 200  {"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response)…"}
POST /ask  X-API-Key: wrong   → 403
```

## Exercise 4.2 — JWT authentication (`production/`)

**JWT flow** (`auth.py`):
1. `POST /auth/token` với username/password → server kiểm tra `DEMO_USERS` và ký JWT bằng `JWT_SECRET` (HS256), payload gồm `sub`, `role`, `iat`, `exp` (60 phút).
2. Client gửi `Authorization: Bearer <token>`.
3. `verify_token` giải mã và kiểm tra chữ ký và hạn. Token hết hạn → 401; token sai chữ ký → 403. Không cần truy vấn DB cho mỗi request vì mọi thông tin nằm trong token.

Kết quả chạy (port 8010):

```
POST /auth/token  {"username":"student","password":"demo123"} → access_token (168 ký tự, eyJ…[masked])
POST /ask (không token)                       → HTTP/1.1 401  {"detail":"Authentication required. Include: Authorization: Bearer <token>"}
POST /ask  Authorization: Bearer eyJ…[masked] → HTTP/1.1 200  {"question":"Explain JWT","answer":"…(mock response)…","usage":{"requests_remaining":9,…}}
```

## Exercise 4.3 — Rate limiting (`production/rate_limiter.py`)

- **Algorithm:** sliding window log. Mỗi user có một deque các timestamp; khi gọi, bỏ các timestamp cũ hơn 60 giây, rồi đếm. Docstring gọi là "Sliding Window Counter", nhưng cách làm là lưu từng timestamp, nên đúng hơn là *sliding window log*.
- **Limit:** user 10 request/phút (`rate_limiter_user`); admin 100 request/phút (`rate_limiter_admin`).
- **Bypass cho admin?** Không bypass. `app.py` chọn limiter theo role (`limiter = rate_limiter_admin if role == "admin"`), nên admin chỉ có limit cao hơn. Không có đường tắt nào trong code.

Kết quả vòng lặp 20 request bằng token của `student` (lần gọi 4.2 đã dùng 1 request):

```
req 1–9:  200
req 10–20: 429
```

Response 429 (token đã che):

```
HTTP/1.1 429 Too Many Requests
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":45}}
```

Response 429 kèm header (chạy lại bằng `test_part4.cmd`):

```
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795684581
retry-after: 52
```

Tài khoản `teacher` (admin) gọi `/ask` trả 200 ở cùng thời điểm, cho thấy limiter khác nhau theo role.

## Exercise 4.4 — Cost guard (`production/cost_guard.py`)

**Cách hoạt động:**
- Giá token được hard-code (`PRICE_PER_1K_*`). Mỗi request sau khi gọi LLM, `record_usage` cộng số token ước tính (mock: số từ × 2) và tính tiền.
- Trước mỗi request, `check_budget` kiểm tra hai lớp:
  1. Ngân sách toàn hệ thống (`global_daily_budget_usd = $10`): vượt → **503**.
  2. Ngân sách từng user (`daily_budget_usd = $1`): vượt → **402 Payment Required**.
- Usage được reset theo ngày (`day` so với hôm nay), không theo tháng.

Kết quả thật sau 10 request thành công của `student` (`GET /me/usage`):

```
{"user_id":"student","date":"2026-11-26","requests":10,"input_tokens":40,"output_tokens":308,
 "cost_usd":0.000191,"budget_usd":1.0,"budget_remaining_usd":0.999809,"budget_used_pct":0.0}
```

Chi phí mock rất nhỏ, nên không chạm được ngưỡng 402 trong lab. Muốn thấy 402 phải hạ `daily_budget_usd` xuống hoặc tăng token mock.

**Triển khai bản Redis (đề bài yêu cầu, theo lời giải trong CODE_LAB):**

```python
import redis
from datetime import datetime

r = redis.Redis()

def check_budget(user_id: str, estimated_cost: float) -> bool:
    month_key = datetime.now().strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"
    current = float(r.get(key) or 0)
    if current + estimated_cost > 10:
        return False
    r.incrbyfloat(key, estimated_cost)
    r.expire(key, 32 * 24 * 3600)  # 32 ngày, để key tự hết hạn sau tháng
    return True
```

Hàm này **chưa được chạy thử** (không có Redis trong lần chạy này). Lưu ý khi dùng: check và cộng tiền là hai lệnh riêng nên có race condition khi nhiều request đến cùng lúc; cách an toàn hơn là dùng Lua script hoặc `INCRBYFLOAT` rồi kiểm tra kết quả, và hoàn tiền nếu vượt.

**Vì sao cần cả rate limit và cost guard?** Rate limit chặn tốc độ (một user spam 1000 request/phút). Cost guard chặn tổng tiền (user gửi ít request nhưng mỗi request rất dài, vẫn có thể tốn nhiều tiền). Chỉ có một trong hai thì bỏ lọt trường hợp còn lại.

## Part 5: Scaling & Reliability

Các output dưới đây là từ lần chạy thật ngày 2026-11-26. Lệnh Docker dùng `-p k5-day14-scaling` để không trùng với stack khác.

## Exercise 5.1 — Health checks (`develop/app.py`)

**Liveness khác readiness ở đâu?**
- `GET /health` (liveness) trả lời "process còn sống không?". Platform gọi định kỳ; nếu fail thì **restart** container. Endpoint này không nên phụ thuộc vào dependency bên ngoài, vì nếu Redis chết mà trả fail thì platform sẽ restart cả container không liên quan.
- `GET /ready` (readiness) trả lời "có nên gửi traffic vào instance này không?". Trả 503 khi chưa khởi động xong hoặc đang shutdown. Platform hoặc load balancer **ngừng route** traffic vào, nhưng không restart container.

Code trong `develop/app.py`: `/health` trả `status`, `uptime_seconds`, `checks.memory` (psutil nếu có). `/ready` trả 503 khi `_is_ready = False`, và `_is_ready` được bật trong `lifespan` sau khi "load model" (`time.sleep(0.2)`).

Kết quả chạy (port 8021):

```
GET /health → 200 {"status":"ok","uptime_seconds":4.0,"version":"1.0.0","checks":{"memory":{"status":"ok","used_percent":31.3}}}
GET /ready  → 200 {"ready":true,"in_flight_requests":1}
```

Lưu ý: `in_flight_requests: 1` là chính request `/ready` đang đếm chính nó, vì middleware `track_requests` tăng counter trước khi endpoint chạy.

## Exercise 5.2 — Graceful shutdown (`develop/app.py`)

**Code có làm gì:**
- `handle_sigterm` chỉ ghi log. Uvicorn tự bắt SIGTERM và chạy `lifespan` shutdown.
- Trong `lifespan`, khi shutdown: đặt `_is_ready = False` (để `/ready` trả 503 và load balancer ngừng gửi request mới), rồi chờ `_in_flight_requests` về 0, tối đa 30 giây.
- `uvicorn.run(..., timeout_graceful_shutdown=30)` cũng giới hạn thời gian chờ ở phía uvicorn.

**Đã kiểm tra:** code đúng về cấu trúc, nhưng **chưa xác nhận bằng test SIGTERM**. Lý do: mock LLM trả lời ngay lập tức nên không có request nào đủ dài để kill giữa chừng, và `kill -TERM` trên Windows không hoạt động như trên Linux. Muốn test đúng cần thêm độ trễ cho `ask()` rồi gửi SIGTERM khi request đang chạy (trên Linux hoặc WSL).

## Exercise 5.3 — Stateless design (`production/app.py`)

**Vì sao không lưu state trong memory?** Mỗi instance có memory riêng. Nếu user A gửi request 1 vào instance 1 và request 2 vào instance 2, instance 2 không có lịch sử của A → lỗi "mất hội thoại". Khi scale lên nhiều instance, state trong RAM sẽ không đồng bộ.

**Cách làm trong `production/app.py`:**
- Mọi session lưu trong Redis qua `save_session` / `load_session` (key `session:{id}`, TTL 1 giờ, tối đa 20 message).
- Bất kỳ instance nào cũng đọc được session từ Redis, nên instance không giữ state gì.
- Có fallback `_memory_store` khi không có Redis, nhưng fallback này **không scale được**; app in cảnh báo "not scalable!" khi dùng.

**Khác với mẫu trong lab:** lab dùng endpoint `/ask` với `user_id`; code thật dùng `/chat` với `session_id`, và trả về `served_by` để thấy instance nào xử lý.

## Exercise 5.4 — Load balancing với Nginx

Lệnh đã chạy (từ `05-scaling-reliability/production/`):

```bash
docker compose -p k5-day14-scaling up -d --build --scale agent=3
```

Trạng thái sau khi lên (đã healthy):

```
k5-day14-scaling-agent-1   Up (healthy)
k5-day14-scaling-agent-2   Up (healthy)
k5-day14-scaling-agent-3   Up (healthy)
k5-day14-scaling-nginx-1   Up        0.0.0.0:8080->80
k5-day14-scaling-redis-1   Up (healthy)
```

Nginx gửi request đi vòng tròn (round-robin) qua 3 instance. Mỗi response có header `X-Served-By` là địa chỉ của instance. 10 request liên tiếp qua `http://localhost:8080/chat`:

```
X-Served-By: 172.19.0.3:8000
X-Served-By: 172.19.0.4:8000
X-Served-By: 172.19.0.5:8000
X-Served-By: 172.19.0.3:8000
X-Served-By: 172.19.0.4:8000
X-Served-By: 172.19.0.5:8000
X-Served-By: 172.19.0.3:8000
X-Served-By: 172.19.0.4:8000
X-Served-By: 172.19.0.5:8000
X-Served-By: 172.19.0.3:8000
```

Log của các container: agent-1 nhận 6 request `POST /chat`, agent-2 nhận 4, agent-3 nhận 6 (tổng 16, gồm 1 request seed, 5 request của `test_stateless.py` và 10 request trên).

**Nếu một instance chết thì sao?** Nginx có `proxy_next_upstream error timeout http_503` và `proxy_next_upstream_tries 3`, nên request được thử lại trên instance khác. Xem phần kill bên dưới.

## Exercise 5.5 — Test stateless (`production/test_stateless.py`)

```bash
python test_stateless.py
```

Kết quả: 5 request liên tiếp trong cùng một session, được phục vụ bởi 3 instance khác nhau (`instance-7febbe`, `instance-1685d1`, `instance-337a08`). Lịch sử đọc lại từ `/chat/{session_id}/history` có đủ **10 message** (5 câu hỏi + 5 câu trả lời), và script in "Session history preserved across all instances via Redis!".

**Kiểm tra thêm: kill một instance giữa phiên.**
1. Tạo session, nhận `served_by` ban đầu.
2. `docker kill k5-day14-scaling-agent-2` (dừng đột ngột, không phải graceful).
3. Gửi tiếp 3 câu hỏi trong cùng `session_id`. Request được phục vụ bởi 2 instance còn lại (`instance-7febbe` và `instance-1685d1`), không request nào bị lỗi.
4. Lịch sử: **8 message** (4 lượt hỏi-đáp), đủ cả trước và sau khi kill.
5. Restart `agent-2` bằng `docker start`; sau ~12 giây container về trạng thái `healthy`.

Kết luận: conversation không phụ thuộc vào instance nào đang sống, vì state nằm trong Redis.

**Dọn dẹp:** `docker compose -p k5-day14-scaling down` (đã chạy, Redis và network đã được gỡ).

## Checkpoint 5

- [x] Implement health và readiness checks — `develop/app.py` có `/health` và `/ready`, đã test 200.
- [~] Implement graceful shutdown — code có chờ in-flight request tối đa 30 giây, nhưng **chưa test được SIGTERM khi có request đang chạy** (xem Exercise 5.2).
- [x] Refactor code thành stateless — session lưu trong Redis, đã xác nhận bằng 3 instance dùng chung một session.
- [x] Hiểu load balancing với Nginx — round-robin đã quan sát được qua `X-Served-By` và log.
- [x] Test stateless design — `test_stateless.py` pass; thêm test kill instance giữa phiên pass.

## AI log

- **Hỏi:** nhờ AI đọc code và chạy các Exercise 5.1, 5.4, 5.5 cùng test kill instance để điền file này.
- **Nhận:** giải thích liveness vs readiness, mô tả luồng stateless qua Redis, các lệnh và kết quả.
- **Tự sửa và tự kiểm tra:** chạy health/ready trên `develop`; dựng stack 3 replica, kiểm tra phân phối qua `X-Served-By`, chạy `test_stateless.py`, kill và restart một instance rồi xác nhận lịch sử còn nguyên.