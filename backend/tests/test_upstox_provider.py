"""Integration test (Section 58): mocked Upstox HTTP responses -> parsed
Candle objects -> deterministic technical features. No real network call."""

from datetime import datetime, timedelta, timezone

import pytest
import respx
from httpx import Response

from app.providers.nifty50_seed import NIFTY50_SEED
from app.providers.upstox import UPSTOX_BASE, UpstoxAuthRequired, UpstoxProvider
from app.services.technical_analysis import compute_technical_features

RELIANCE = next(s for s in NIFTY50_SEED if s.symbol == "RELIANCE")


def _sample_candles_payload(n: int = 220) -> dict:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = []
    price = 2000.0
    for i in range(n):
        price *= 1.002  # gentle uptrend
        ts = (start + timedelta(days=i)).isoformat()
        candles.append([ts, price * 0.99, price * 1.01, price * 0.98, price, 500_000, 0])
    return {"status": "success", "data": {"candles": list(reversed(candles))}}


@pytest.mark.asyncio
@respx.mock
async def test_get_historical_ohlcv_parses_upstox_response():
    respx.get(url__regex=rf"{UPSTOX_BASE}/v3/historical-candle/.*").mock(
        return_value=Response(200, json=_sample_candles_payload())
    )

    provider = UpstoxProvider(access_token="fake-token", token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    candles = await provider.get_historical_ohlcv(
        RELIANCE.symbol, "1d", from_date=datetime(2025, 1, 1).date(), to_date=datetime(2025, 8, 1).date()
    )

    assert len(candles) == 220
    assert all(c.source == "upstox" for c in candles)
    assert candles[0].close > 0


@pytest.mark.asyncio
@respx.mock
async def test_candles_flow_into_technical_features():
    respx.get(url__regex=rf"{UPSTOX_BASE}/v3/historical-candle/.*").mock(
        return_value=Response(200, json=_sample_candles_payload(220))
    )

    provider = UpstoxProvider(access_token="fake-token", token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    candles = await provider.get_historical_ohlcv(
        RELIANCE.symbol, "1d", from_date=datetime(2025, 1, 1).date(), to_date=datetime(2025, 8, 1).date()
    )

    features = compute_technical_features(candles, timeframe="1d")
    assert features["trend"] in ("bullish", "neutral")  # gentle synthetic uptrend
    assert features["rsi_14"] is not None


@pytest.mark.asyncio
async def test_expired_token_raises_auth_required():
    provider = UpstoxProvider(access_token="stale-token", token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    with pytest.raises(UpstoxAuthRequired):
        await provider.get_quote(RELIANCE.symbol)


@pytest.mark.asyncio
async def test_missing_token_raises_auth_required():
    provider = UpstoxProvider(access_token=None, token_expires_at=None)
    with pytest.raises(UpstoxAuthRequired):
        await provider.get_historical_ohlcv(
            RELIANCE.symbol, "1d", from_date=datetime(2025, 1, 1).date(), to_date=datetime(2025, 2, 1).date()
        )
