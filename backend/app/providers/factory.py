"""Provider selection (Section 65 fallback chain): Yahoo Finance (no
account/KYC needed) -> demo/cached seed if DEMO_MODE is on. Never silently
serves stale data as live -- callers get `Quote.is_stale` / provenance on
every row."""

from app.core.config import settings
from app.providers.base import MarketDataProvider
from app.providers.demo_market_data import DemoMarketDataProvider
from app.providers.yfinance_market_data import YFinanceMarketDataProvider


async def get_market_data_provider() -> MarketDataProvider:
    if settings.demo_mode:
        return DemoMarketDataProvider()

    return YFinanceMarketDataProvider()
