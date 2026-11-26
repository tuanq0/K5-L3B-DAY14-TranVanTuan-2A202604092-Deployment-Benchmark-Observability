# ============================================================
# Production Dockerfile — multi-stage, slim, non-root, HEALTHCHECK
# ============================================================

# ── Stage 1: builder — cài dependencies vào /install ──
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime — chỉ copy những gì cần để chạy ──
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

RUN groupadd -r app && useradd -r -g app -d /app -s /usr/sbin/nologin app

COPY --from=builder /install /usr/local

WORKDIR /app
COPY app/ ./app/
COPY utils/ ./utils/
RUN chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=4)" || exit 1

# exec: uvicorn trở thành PID 1 và nhận SIGTERM từ `docker stop`
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
