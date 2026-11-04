# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------------------------------------------------
# KIFARU PORTOS API image. Build from the REPOSITORY ROOT so the workspace packages are in context:
#   docker build -f apps/api/Dockerfile -t kifaru/api:dev .
# The same image runs every backend role (api, realtime, worker, ingest, migrate, seed, pg_dump); the ECS task definition
# or docker-compose `command` selects the entrypoint.
# ---------------------------------------------------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12

# --- Stage 1: build wheels/venv ----------------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build tools only in this stage (most deps ship wheels; gcc covers any sdist fallback).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /src
COPY packages/wim_dsp   ./packages/wim_dsp
COPY packages/ai_agents ./packages/ai_agents
COPY apps/api           ./apps/api

# Workspace packages first so `kifaru-wim-dsp` / `kifaru-ai-agents` resolve locally, then the API itself.
# boto3 is added for S3 object storage and the pg_dump upload task (not yet in pyproject; see deployment guide).
RUN pip install --upgrade pip \
 && pip install ./packages/wim_dsp ./packages/ai_agents \
 && pip install ./apps/api "boto3>=1.35" "email-validator>=2.2"

# --- Stage 2: runtime ----------------------------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG PG_MAJOR=16
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    KIFARU_LOCAL_OBJECT_DIR=/data/objects

# postgresql-client-16 (pg_dump/psql matching the RDS major) from the PGDG repository; tini for signal handling.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg tini \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && . /etc/os-release \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-${PG_MAJOR} \
 && apt-get purge -y --auto-remove curl gnupg \
 && rm -rf /var/lib/apt/lists/*

# Non-root runtime user
RUN groupadd --system --gid 10001 kifaru \
 && useradd --system --uid 10001 --gid kifaru --home-dir /app --shell /usr/sbin/nologin kifaru \
 && mkdir -p /app /data/objects \
 && chown -R kifaru:kifaru /app /data

COPY --from=builder /opt/venv /opt/venv
# Alembic needs alembic.ini + the versions folder at runtime; the kifaru package itself is installed in the venv.
COPY --chown=kifaru:kifaru apps/api/alembic.ini /app/alembic.ini
COPY --chown=kifaru:kifaru apps/api/alembic     /app/alembic

WORKDIR /app
USER kifaru

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "kifaru.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
