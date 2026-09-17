"""Single source of truth for "what source tag does the CURRENT DEMO_MODE
setting produce" (docs/v3-execution/CONTRACTS.md C3). Every read path that
selects a cached candle/fundamental row by "most recent" must filter by this,
not just instrument id -- otherwise flipping DEMO_MODE serves synthetic
demo_seed rows as if real (or vice versa) to both ingestion and API reads."""

from app.core.config import settings

DEMO_CANDLE_SOURCE = "demo_seed"
LIVE_CANDLE_SOURCE = "yfinance"

DEMO_FUNDAMENTALS_SOURCE = "demo_seed"
LIVE_FUNDAMENTALS_SOURCE = "yfinance_nifty50_seed"


def expected_candle_source() -> str:
    if settings.market_data_source_override:
        return settings.market_data_source_override
    return DEMO_CANDLE_SOURCE if settings.demo_mode else LIVE_CANDLE_SOURCE


def expected_fundamentals_source() -> str:
    return DEMO_FUNDAMENTALS_SOURCE if settings.demo_mode else LIVE_FUNDAMENTALS_SOURCE
