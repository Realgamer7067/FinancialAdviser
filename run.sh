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

export $(grep -v '^#' .env | xargs)

cd backend
alembic upgrade head

python -m app.worker &
WORKER_PID=$!
trap "kill $WORKER_PID" EXIT

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
