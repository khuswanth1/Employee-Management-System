FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
# pg_dump is used by the platform backup endpoint
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY alembic_platform ./alembic_platform
COPY alembic_tenant ./alembic_tenant
RUN useradd --create-home --uid 10001 worksphere && mkdir -p /app/data && chown -R worksphere /app
USER worksphere
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
# One worker: WebSocket fan-out, rate limiting and the webhook worker are in-process (see README: scaling).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
