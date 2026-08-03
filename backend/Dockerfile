# Render deploys from this image. Heavy build work stays on CI, not the box.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build deps for asyncpg/lxml; removed from the final layer.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libxml2-dev libxslt1-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e .

COPY app ./app
COPY scripts ./scripts
COPY seed ./seed
# Startup runs `alembic upgrade head` (app/services/bootstrap.py) — it needs
# the migration scripts and config INSIDE the image or first boot dies.
COPY migrations ./migrations
COPY alembic.ini ./
COPY deploy/start.sh ./deploy/start.sh

# Uploads / generated packs / dev email outbox. EPHEMERAL on free tiers:
# ingested content survives (rows + chunks + vectors live in Postgres/Qdrant)
# but re-ingest of an old upload needs the original file again.
RUN chmod +x deploy/start.sh \
    && mkdir -p var/uploads var/outbox \
    && useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

# start.sh = uvicorn + the ingestion worker in one container (free tiers give
# you a single process; without the worker every upload sits "pending" forever).
CMD ["./deploy/start.sh"]
