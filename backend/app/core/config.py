import os
from pathlib import Path

import yaml
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SECRET_KEY = "change-me-in-production"

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
    secret_key: str = _DEFAULT_SECRET_KEY
    timezone: str = "Asia/Kolkata"

    @model_validator(mode="after")
    def _forbid_default_secret_outside_dev(self) -> "Settings":
        # A forgeable, publicly-known JWT signing key is a full auth bypass --
        # fail startup loudly rather than silently accept it anywhere but local dev.
        if self.secret_key == _DEFAULT_SECRET_KEY and self.environment != "development":
            raise ValueError(
                "SECRET_KEY is still the default placeholder outside a development "
                "environment -- set a real secret via the SECRET_KEY env var."
            )
        return self

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/equity_research"
    sync_database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/equity_research"

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
    fundamentals_cache_ttl_hours: int = 24

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
