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
    timezone: str = "Asia/Kolkata"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/equity_research"
    sync_database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/equity_research"

    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_api_key: str = ""
    qwen_model: str = "qwen2.5-32b-instruct"
    # Optional comma-separated pool of additional keys against the SAME
    # base_url/model (e.g. 3 separate Gemini API keys each with their own
    # quota) -- when set, QwenOpenAICompatibleProvider round-robins across
    # qwen_api_key + this pool per call, and specifically retries with the
    # NEXT key (not the same one) on a 429, instead of just backing off
    # against an already-exhausted key. Empty means single-key, unchanged
    # behavior.
    qwen_api_key_pool: str = ""

    # V3 Phase 04 (docs/V3-IMPLEMENTATION-PLAN.md Section 11): provider-neutral
    # model adapter, Gemini REST as the new candidate, Qwen kept as a selectable
    # baseline under the same interface -- see app/models_iface/model_adapter.py.
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_api_key: str = ""
    gemini_flash_lite_model: str = "gemini-3.5-flash-lite"
    gemini_flash_model: str = "gemini-3.8-flash"

    # V3 Phase 11: dead field -- no code in this repo reads settings.hf_home.
    # The real HF_HOME env var (which transformers/huggingface_hub actually
    # honor) comes from .env via run.sh's `export $(grep -v '^#' .env | xargs)`
    # / docker-compose's env_file, resolved against whatever CWD that shell
    # is in at export time -- which is why `backend/data/cache/huggingface`
    # exists on disk while the repo-root `data/cache/` does not (confirmed
    # during this pass). Left as documentation of the actual cache location,
    # not wired to anything; not refactored here (out of this pass's scope).
    hf_home: str = "./data/cache/huggingface"
    kronos_model_id: str = "NeoQuasar/Kronos-small"
    kronos_tokenizer_id: str = "NeoQuasar/Kronos-Tokenizer-base"
    # The Kronos repo (github.com/shiyu-coder/Kronos) has no setup.py/pyproject.toml
    # -- it's not pip-installable. This must point at a `git clone` of it (done by
    # the Dockerfile / run.sh) so `from model import ...` resolves via sys.path.
    # V3 Phase 11: was a bare "./vendor/kronos" (relative to CWD, only correct
    # because run.sh `cd`s into backend/ first -- started from the repo root
    # it silently resolved to a nonexistent <repo>/vendor/kronos and Kronos
    # degraded to None with no error, same class of bug fixed in
    # kronos_calibration.py's _CALIBRATION_ROOT). Anchored to this file's own
    # directory (backend/, i.e. parents[2] from app/core/config.py) rather
    # than REPO_ROOT/"backend" -- REPO_ROOT itself is "/" inside the
    # container (see the comment above), so REPO_ROOT/"backend"/"vendor"/
    # "kronos" would evaluate to "/backend/vendor/kronos" there. Harmless in
    # practice (docker-compose.yml overrides this via KRONOS_REPO_PATH=
    # /opt/kronos) but parents[2] is the semantically correct anchor either way.
    kronos_repo_path: str = str(Path(__file__).resolve().parents[2] / "vendor" / "kronos")
    # `predictor.predict(sample_count=N)` averages the N draws internally and
    # returns one mean path (vendor/kronos/model/kronos.py:465-467) -- to get
    # a real distribution KronosModel calls predict() this many times
    # independently instead. CPU cost scales linearly with this value.
    kronos_sample_count: int = 8
    finbert_model_id: str = "ProsusAI/finbert"

    worker_poll_interval_seconds: int = 5
    # How long a claimed job's lease is valid without a heartbeat before
    # another worker may reclaim it (docs/V2-RETHINK.md P0: no lease recovery
    # existed before, so a killed/hung worker left jobs stuck "running"
    # forever). Must comfortably exceed the gap between progress heartbeats
    # (JobProgressTracker.set_stage renews it on every stage transition).
    job_lease_seconds: int = 300
    fundamentals_cache_ttl_hours: int = 24

    # Test/rehearsal-only overrides against a restored dump whose data is
    # necessarily older than production freshness rules allow (see
    # scripts/restore_postgres_backup.sh) -- never set in a real deployment,
    # where the default 3-day candle / 24h fundamentals staleness rules are
    # the actual product behavior (never serve stale prices as current).
    # None means "use the normal rule," unchanged.
    market_data_staleness_override_days: int | None = None
    fundamentals_staleness_override_hours: int | None = None
    # Overrides expected_candle_source()'s demo/live binary (app/providers/
    # mode.py) -- e.g. "truedata" to test against TrueData-sourced candles
    # specifically instead of whatever DEMO_MODE would otherwise select.
    market_data_source_override: str | None = None

    # TrueData (NSE/BSE/MCX data vendor) -- used only by
    # scripts/sync_truedata_history.py for a one-time historical cache pull
    # during a trial window, never by the live pipeline. Credentials only,
    # never the data itself, belong in .env -- see .TD_API_Docs/ (gitignored,
    # NDA-covered) for the API docs this script implements against.
    truedata_username: str = ""
    truedata_password: str = ""

    @property
    def qwen_configured(self) -> bool:
        return bool(self.qwen_api_key) or bool(self.qwen_api_key_pool.strip())

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)


settings = Settings()


def load_yaml_config(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path) as f:
        return yaml.safe_load(f)


def scoring_config() -> dict:
    return load_yaml_config("scoring.yaml")


def screening_config() -> dict:
    return load_yaml_config("screening.yaml")


def allocation_policy_config() -> dict:
    # V3 Phase 05 (Section 6.2, "Policy ownership") -- synthetic/educational
    # allocation scenarios, not a reviewed/approved policy. See the file's
    # own header comment and its `is_synthetic`/`rationale` fields.
    return load_yaml_config("allocation_policy.yaml")
