# MISSION_ANSWERS — Part 4: API Security

Các output dưới đây là từ lần chạy thật ngày 2026-11-26. Token đã được che (`eyJ…[masked]`).

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

Lưu ý: `develop/app.py` in key ra console khi khởi động (dòng 91). Không nên làm vậy ngoài môi trường lab.

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

## Checkpoint 4

- [x] Implement API key authentication — `develop/app.py`, đã kiểm tra 401 / 403 / 200.
- [x] Hiểu JWT flow — đã lấy token và gọi API bằng Bearer, đã kiểm tra 401 khi thiếu token.
- [x] Implement rate limiting — đã thấy 429 từ request thứ 11 trong 60 giây (lab: request 11+; kết quả thật: request 10 của lần chạy, vì request đầu được tính trong lần lấy token).
- [x] Implement cost guard với Redis — đã viết lời giải theo đề, **chưa chạy với Redis**; bản đang chạy trong `production/` là phiên bản in-memory.

## AI log

- **Hỏi:** nhờ AI đọc `develop/app.py`, `production/auth.py`, `rate_limiter.py`, `cost_guard.py` và chạy Exercise 4.1–4.3 để điền file này.
- **Nhận:** giải thích các cơ chế, lệnh curl, số liệu từ lần chạy.
- **Tự sửa và tự kiểm tra:** chạy cả hai gateway và kiểm tra từng trường hợp 401/403/200/429 bằng curl; đọc lại code để xác nhận cách rate limit theo role. Phần 4.4 Redis không chạy được trong lần này.
