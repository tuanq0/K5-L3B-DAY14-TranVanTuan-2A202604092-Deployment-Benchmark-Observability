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
- URL: https://your-app.railway.app
- Screenshot: [Link to screenshot in repo]

## Part 4: API Security

### Exercise 4.1-4.3: Test results
[Paste your test outputs]

### Exercise 4.4: Cost guard implementation
[Explain your approach]

## Part 5: Scaling & Reliability

### Exercise 5.1-5.5: Implementation notes
[Your explanations and test results]
```

---