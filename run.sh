#!/usr/bin/env bash
# Local (non-docker) dev entrypoint. For containerized dev, use `docker compose up`.
set -euo pipefail

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — fill in QWEN_API_KEY before real (non-demo) use; market data needs no key."
fi

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -d backend/.venv ]; then
  uv venv backend/.venv
fi
source backend/.venv/bin/activate
uv pip install -q -r backend/requirements.txt

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
