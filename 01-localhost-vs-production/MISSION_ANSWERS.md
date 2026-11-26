# MISSION_ANSWERS — Part 1: Localhost vs Production

## Exercise 1.1 — Phát hiện anti-patterns trong `develop/app.py`

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

## Exercise 1.2 — Chạy basic version

Lệnh trong lab: `curl -X POST .../ask -H "Content-Type: application/json" -d '{"question": "Hello"}'`

Quan sát khi chạy `develop/app.py` gốc (thử trên Windows, Python 3.13, FastAPI 0.115.0):

- **Lệnh JSON body trong lab trả về 422** `{"detail":[{"type":"missing","loc":["query","question"],...}]}`. Lý do: `ask_agent(question: str)` đọc `question` từ **query string**, không đọc từ body JSON. Lệnh đúng cho bản basic là `curl -X POST "http://localhost:8000/ask?question=Hello"` (đúng với comment trong code).
- **Gọi bằng query string bị lỗi 500 trên console Windows**: `UnicodeEncodeError: 'charmap' codec can't encode character 'đ'`. Lý do: `print()` ghi tiếng Việt ra console dùng codepage cp1252. Đây là một anti-pattern nữa (dùng `print` thay vì logging, không kiểm soát encoding), và chạy với `PYTHONUTF8=1` thì hết lỗi.
- `GET /health` trả 404 vì bản basic không có endpoint này.

Kết quả 200 đầy đủ: [điền output sau khi chạy lại với `PYTHONUTF8=1`].

**Kết luận:** agent chạy được, nhưng không sẵn sàng cho production: sai lệch giữa lệnh trong tài liệu và API thực tế, log lỗi trên một môi trường khác, không có health check.

## Exercise 1.3 — So sánh `develop/app.py` và `production/`

Bảng so sánh (đọc từ `production/app.py`, `production/config.py`, `production/.env.example`):

| Feature | Basic (`develop/`) | Advanced (`production/`) | Tại sao quan trọng? |
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

### Lưu ý về bản production (để không đánh giá quá mức)

- **Graceful shutdown còn chưa đầy đủ.** `handle_sigterm` chỉ ghi log, và phần "chờ request hoàn thành" là `time.sleep(0.1)` trong `lifespan`. Phần thực sự tắt êm là do uvicorn xử lý. Đây là điểm cần cải thiện nếu agent có tác vụ dài.
- **`AGENT_API_KEY` được định nghĩa trong `config.py` nhưng endpoint `/ask` chưa kiểm tra nó.** Ai gọi được URL đều gọi được `/ask`. Phần này được xử lý ở Part 4 (API Security).
- **Production đã bỏ `DATABASE_URL`** vì bản này không kết nối DB; bản basic có chuỗi kết nối nhưng không dùng đến.

