# MISSION_ANSWERS — Part 5: Scaling & Reliability

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
- **Tự sửa và tự kiểm tra:** chạy health/ready trên `develop`; dựng stack 3 replica, kiểm tra phân phối qua `X-Served-By`, chạy `test_stateless.py`, kill và restart một instance rồi xác nhận lịch sử còn nguyên. Phần graceful shutdown chưa được kiểm tra bằng SIGTERM thật.
