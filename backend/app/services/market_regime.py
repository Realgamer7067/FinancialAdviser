"""Deterministic market-regime detector (Section 33). Feeds Qwen and the
council so the same stock is interpreted in context, not in a vacuum."""

from app.providers.base import Candle, Quote

# India VIX bands are a coarse, documented heuristic, not a calibrated model --
# revisit once enough regime/outcome history exists to calibrate (Section 36).
VIX_ELEVATED_THRESHOLD = 20.0
VIX_HIGH_THRESHOLD = 30.0


def detect_market_regime(nifty_candles: list[Candle], india_vix: Quote | None) -> dict:
    if len(nifty_candles) < 50:
        return {"nifty_trend": "unknown", "india_vix": "unknown", "market_regime": "unknown"}

    closes = [c.close for c in nifty_candles]
    sma_50 = sum(closes[-50:]) / 50
    sma_20 = sum(closes[-20:]) / 20
    last = closes[-1]

    if last > sma_50 * 1.01 and sma_20 > sma_50:
        nifty_trend = "bullish"
    elif last < sma_50 * 0.99 and sma_20 < sma_50:
        nifty_trend = "bearish"
    else:
        nifty_trend = "neutral"

    if india_vix is None:
        vix_band = "unknown"
    elif india_vix.price >= VIX_HIGH_THRESHOLD:
        vix_band = "high"
    elif india_vix.price >= VIX_ELEVATED_THRESHOLD:
        vix_band = "elevated"
    else:
        vix_band = "low"

    volatility_suffix = "_high_volatility" if vix_band in ("elevated", "high") else "_low_volatility"
    regime = f"{nifty_trend}{volatility_suffix}" if nifty_trend != "unknown" else "unknown"

    return {"nifty_trend": nifty_trend, "india_vix": vix_band, "market_regime": regime}
