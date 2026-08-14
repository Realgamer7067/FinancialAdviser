import os
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

# parents[3] resolves correctly for local dev (repo_root/backend/app/core/config.py)
# but NOT inside the container, where the backend's own directory is mounted at
# /app -- parents[3] there is "/". CONFIG_DIR/DATA_DIR are therefore
# environment-overridable; docker-compose.yml sets them explicitly to match its
# `./config:/app/config` and `./data:/app/data` volume mounts.
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", REPO_ROOT / "config"))
DATA_DIR = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    demo_mode: bool = True
    environment: str = "development"
    secret_key: str = "change-me-in-production"
    timezone: str = "Asia/Kolkata"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/equity_research"
    sync_database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/equity_research"

    upstox_api_key: str = ""
    upstox_api_secret: str = ""
    upstox_redirect_uri: str = "http://localhost:8000/admin/upstox/callback"

    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_api_key: str = ""
    qwen_model: str = "qwen2.5-32b-instruct"

    hf_home: str = "./data/cache/huggingface"
    kronos_model_id: str = "NeoQuasar/Kronos-small"
    kronos_tokenizer_id: str = "NeoQuasar/Kronos-Tokenizer-base"
    # The Kronos repo (github.com/shiyu-coder/Kronos) has no setup.py/pyproject.toml
    # -- it's not pip-installable. This must point at a `git clone` of it (done by
    # the Dockerfile / run.sh) so `from model import ...` resolves via sys.path.
    kronos_repo_path: str = "./vendor/kronos"
    finbert_model_id: str = "ProsusAI/finbert"

    worker_poll_interval_seconds: int = 5

    @property
    def upstox_configured(self) -> bool:
        return bool(self.upstox_api_key and self.upstox_api_secret)

    @property
    def qwen_configured(self) -> bool:
        return bool(self.qwen_api_key)


settings = Settings()


def load_yaml_config(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path) as f:
        return yaml.safe_load(f)


def scoring_config() -> dict:
    return load_yaml_config("scoring.yaml")


def screening_config() -> dict:
    return load_yaml_config("screening.yaml")
