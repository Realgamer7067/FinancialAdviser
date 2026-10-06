FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY requirements.txt .
# CPU-only torch wheel -- the default PyPI build drags in several GB of CUDA
# kernels (nvidia-cublas-cu12, nvidia-cudnn-cu12, ...) that are never used;
# Kronos/FinBERT are sized to run on CPU (no GPU in this stack).
RUN uv pip install --system --no-cache torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu
RUN uv pip install --system --no-cache -r requirements.txt

# Kronos (github.com/shiyu-coder/Kronos) has no setup.py/pyproject.toml -- it's
# not pip-installable, so it's cloned directly and put on PYTHONPATH instead.
# KRONOS_REPO_PATH (set in docker-compose.yml) must match this location.
# Pinned to a specific commit (not just "latest master") so a rebuild months
# from now doesn't silently pick up upstream changes -- V3 Phase 11 found no
# SHA was pinned anywhere before this. `git fetch --depth 1 <sha>` keeps the
# shallow-clone size benefit while still landing on an exact commit.
ARG KRONOS_COMMIT=67b630e67f6a18c9e9be918d9b4337c960db1e9a
RUN mkdir /opt/kronos && cd /opt/kronos \
    && git init -q \
    && git remote add origin https://github.com/shiyu-coder/Kronos.git \
    && git fetch --depth 1 origin ${KRONOS_COMMIT} \
    && git checkout FETCH_HEAD
ENV PYTHONPATH=/opt/kronos:$PYTHONPATH

COPY . .

EXPOSE 8000

# Backend's own /health endpoint (app/main.py) -- used by docker-compose's
# `service_healthy` condition so the worker doesn't start (or is at least
# correctly gated) before the API/migration step is genuinely up, not just
# "the process started" (V3 Phase 11: migration_barrier.py can make this
# process exit right after starting on a schema mismatch -- a healthcheck
# catches that faster than depends_on: service_started ever could).
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
