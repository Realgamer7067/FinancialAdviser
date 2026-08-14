"""Provider selection (Section 65 fallback chain): configured Upstox with a
valid token -> demo/cached seed. Never silently serves stale data as live --
callers get `Quote.is_stale` / provenance on every row."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.providers.base import MarketDataProvider
from app.providers.demo_market_data import DemoMarketDataProvider
from app.providers.upstox import UpstoxProvider
from app.services.upstox_auth import get_upstox_token_state


async def get_market_data_provider(db: AsyncSession) -> MarketDataProvider:
    if settings.demo_mode or not settings.upstox_configured:
        return DemoMarketDataProvider()

    access_token, expires_at = await get_upstox_token_state(db)
    if not access_token or (expires_at and datetime.now(timezone.utc) >= expires_at):
        return DemoMarketDataProvider()

    return UpstoxProvider(access_token, expires_at)
