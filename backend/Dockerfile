FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=UTC

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 1000 bot && chown -R bot:bot /app
USER bot

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=10s --start-period=90s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["python", "main.py"]
