# MISSION_ANSWERS — Part 2: Docker Containerization

## Exercise 2.1 — Dockerfile cơ bản (`develop/Dockerfile`)

1. **Base image là gì?** `python:3.11` — image Python đầy đủ (full distribution, khoảng 1 GB). Nó chứa cả compiler, tool build và nhiều package không cần cho lúc chạy.
2. **Working directory là gì?** `/app` (dòng `WORKDIR /app`). Mọi lệnh `COPY` và `RUN` sau đó chạy trong thư mục này, và process khi start cũng bắt đầu ở đây.
3. **Tại sao `COPY requirements.txt` trước?** Docker cache từng layer theo nội dung đầu vào. Nếu chỉ `app.py` đổi, layer `pip install` vẫn được dùng lại từ cache vì `requirements.txt` không đổi, nên build nhanh hơn nhiều. Nếu copy cả source trước, mỗi lần sửa code sẽ cài lại toàn bộ dependencies.
4. **CMD vs ENTRYPOINT khác nhau thế nào?**
   - `CMD` là lệnh mặc định, và `docker run <image> <lệnh khác>` sẽ **thay thế** hoàn toàn nó (ví dụ `docker run -it my-agent bash`).
   - `ENTRYPOINT` là executable cố định; tham số truyền vào `docker run` sẽ được **nối thêm** vào sau nó, không thay thế.
   - Thường dùng: `ENTRYPOINT ["python"]` + `CMD ["app.py"]` để có một lệnh cố định và có thể đổi tham số mặc định.

## Exercise 2.2 — Build và run

Build và chạy với đúng lệnh trong lab:

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name t-develop -p 8100:8000 my-agent:develop
```

Kết quả gọi container:

```
POST /ask (JSON body, như trong lab)       → 422 {"detail":[{"type":"missing","loc":["query","question"],...}]}
POST /ask?question=What%20is%20Docker%3F   → 200 {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
GET  /health                               → 200 {"status":"ok","uptime_seconds":7.7,"container":true}
```

`develop/app.py` đọc `question` từ **query string**, không đọc từ body JSON nên lệnh JSON trong lab trả về 422. Với bản develop, cần dùng dạng `?question=...`.

Kích thước image (`docker images my-agent`, đo ngày 2026-11-26):

```
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:develop    227febfbe921   1.67GB       426MB
```

## Exercise 2.3 — Multi-stage build (`production/Dockerfile`)

Build và đo:

```bash
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images my-agent
```

- **Stage 1 (`builder`, base `python:3.11-slim`):** cài `gcc` và `libpq-dev` (build tools), rồi `pip install --user` vào `/root/.local`. Stage này **không** được dùng để deploy.
- **Stage 2 (`runtime`, base `python:3.11-slim`):** tạo user không phải root `appuser`, chỉ `COPY --from=builder` thư mục packages đã cài, copy `main.py` và `utils/mock_llm.py`. Không có `gcc`, không có cache apt, không có pip.

**Tại sao image nhỏ hơn?** Image cuối chỉ chứa những gì cần để chạy. Build tools (`gcc`, `libpq-dev`, apt cache) và các bước cài đặt nằm ở stage builder, bị bỏ đi khi build stage runtime. Base `slim` cũng nhỏ hơn bản full.

Kết quả đo:

```
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:advanced   e3174a6de09b   240MB        57.4MB
my-agent:develop    227febfbe921   1.67GB       426MB
```

| Image | Disk usage | Content size |
| --- | ---: | ---: |
| develop (basic) | 1.67 GB | 426 MB |
| advanced (multi-stage) | 240 MB | 57.4 MB |
| **Chênh lệch** | **−85.6%** | **−86.5%** |

Chênh lệch tính từ số byte đo được: disk 239,811,555 / 1,667,788,107 bytes; content tính từ số MB hiển thị trong `docker images`.

Container advanced chạy được: `POST /ask` trả 200, `GET /health` trả 200, và log JSON hiển thị đúng.

## Exercise 2.4 — Docker Compose stack (`production/docker-compose.yml`)

Lệnh đã chạy (dùng `-p` để tránh trùng tên với stack khác):

```bash
cd 02-docker/production
docker compose -p k5-day14-docker up -d --build
docker compose -p k5-day14-docker ps
```

Cần file `.env.local` (đã được `.gitignore`) vì compose khai báo `env_file: .env.local`; không có file này `docker compose up` sẽ lỗi. Trong lần chạy này dùng file với giá trị rỗng.

Services đã start:

```
NAME                       SERVICE   STATUS                           PORTS
k5-day14-docker-agent-1    agent     Up (health: starting→healthy)    8000/tcp (không publish ra host)
k5-day14-docker-nginx-1    nginx     Up                               0.0.0.0:80->80, 0.0.0.0:443->443
k5-day14-docker-qdrant-1   qdrant    Up (healthy)                     6333-6334/tcp
k5-day14-docker-redis-1    redis     Up (healthy)                     6379/tcp
```

### Sơ đồ kiến trúc

```
              Host :80 / :443
                    │
             ┌──────▼──────┐
             │   nginx     │  reverse proxy, rate limit 10 r/s,
             │ (alpine)    │  security headers, /health không rate limit
             └──────┬──────┘
                    │  proxy_pass http://agent_backend  (agent:8000)
   ┌────────────────┼──────────────── network "internal" (bridge) ─┐
   │         ┌──────▼──────┐                                       │
   │         │   agent     │── REDIS_URL ──► ┌─────────┐           │
   │         │ FastAPI     │                 │  redis  │ :6379     │
   │         │ (2 workers) │── QDRANT_URL ─► ├─────────┤           │
   │         └─────────────┘                 │ qdrant  │ :6333     │
   │                                         └─────────┘           │
   └───────────────────────────────────────────────────────────────┘
```

- Chỉ **nginx** publish port ra host. `agent`, `redis`, `qdrant` chỉ nói chuyện với nhau trong network `internal`.
- `agent` khởi động sau khi `redis` và `qdrant` báo healthy (`depends_on` với `condition: service_healthy`).
- Nginx chuyển tiếp đến `agent:8000` qua tên service, Docker DNS phân giải tên này trong network.

### Kết quả test qua Nginx

```bash
curl http://localhost/health
curl http://localhost/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
```

```
GET  /health                              → 200 {"status":"ok","uptime_seconds":2.0,"version":"2.0.0",...}
POST /ask {"question":"Explain microservices"} → 200 {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
POST /ask {}                              → 422 {"detail":"question required"}
```

Log của agent cho thấy request đi qua nginx (IP nội bộ `172.19.0.5`) và được trả về đúng mã.

## Checkpoint 2 — Tự kiểm tra

- **Hiểu cấu trúc Dockerfile:** base image, WORKDIR, thứ tự layer để tận dụng cache; `CMD` và `ENTRYPOINT` khác nhau ở chỗ tham số của `docker run` thay thế hay nối thêm.
- **Lợi ích của multi-stage:** build tools không nằm trong image chạy. Đo được: 1.67 GB → 240 MB (−85.6%).
- **Docker Compose orchestration:** 4 service trên network nội bộ, `depends_on` với healthcheck, chỉ nginx mở port ra ngoài.
- **Debug container:** `docker logs` xem log agent (đã dùng để xác nhận request qua nginx); `docker exec` dùng để vào shell của container (chưa dùng trong lần chạy này).

## AI log

- **Hỏi:** nhờ AI đọc các Dockerfile và `docker-compose.yml` để trả lời Exercise 2.1–2.4 và tổ chức file này.
- **Nhận:** giải thích base image, layer cache, CMD vs ENTRYPOINT; mô tả hai stage của multi-stage; sơ đồ stack.
- **Tự sửa và tự kiểm tra:** build cả hai image và đo kích thước bằng `docker images`; chạy container và gọi endpoint; chạy compose stack và test qua nginx. Các số trong file đều lấy từ lần chạy này, không chép từ README.
