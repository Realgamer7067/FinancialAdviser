#!/usr/bin/env bash
# Local (non-docker) dev entrypoint. For containerized dev, use `docker compose up`.
set -euo pipefail

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — fill in Upstox / Qwen keys before real (non-demo) use."
fi

if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
fi
source backend/.venv/bin/activate
pip install -q -r backend/requirements.txt

# Kronos (github.com/shiyu-coder/Kronos) has no setup.py/pyproject.toml -- not
# pip-installable. Clone it once; app/models_iface/kronos.py finds it via
# KRONOS_REPO_PATH (defaults to backend/vendor/kronos).
if [ ! -d backend/vendor/kronos ]; then
  git clone --depth 1 https://github.com/shiyu-coder/Kronos.git backend/vendor/kronos
fi

export $(grep -v '^#' .env | xargs)

cd backend
alembic upgrade head

python -m app.worker &
WORKER_PID=$!
trap "kill $WORKER_PID" EXIT

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
