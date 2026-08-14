"""Deterministic 0-100 sub-scores (Section 18). Computed in Python from
evidence, never invented by the LLM. Each returns None when the underlying
evidence is UNKNOWN -- excluded from the weighted average, not zero-filled
(Section 8: never guess)."""

from app.scoring.evidence import (
    FundamentalEvidence,
    KronosEvidence,
    NewsEvidence,
    PortfolioEvidence,
    TechnicalEvidence,
)

_VOL_LOW = 0.25
_VOL_HIGH = 0.45
_RISK_LADDER = ["conservative", "moderate", "aggressive"]
_VOL_LADDER = ["low", "moderate", "high"]


def _clip(x: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, x))


def fundamental_score(ev: FundamentalEvidence | None) -> float | None:
    if ev is None:
        return None
    parts: list[float] = []

    if ev.roe is not None:
        parts.append(100 if ev.roe > 0.20 else 80 if ev.roe > 0.15 else 60 if ev.roe > 0.10 else 40 if ev.roe > 0.05 else 20)
    if ev.debt_to_equity is not None:
        d = ev.debt_to_equity
        parts.append(100 if d < 0.5 else 80 if d < 1 else 60 if d < 2 else 40 if d < 3 else 20)
    if ev.revenue_growth is not None:
        g = ev.revenue_growth
        parts.append(100 if g > 0.15 else 75 if g > 0.08 else 50 if g > 0.02 else 30 if g >= 0 else 10)
    if ev.pe is not None and ev.pe > 0:
        parts.append(90 if ev.pe < 15 else 70 if ev.pe < 25 else 50 if ev.pe < 40 else 30)
    if ev.net_margin is not None:
        m = ev.net_margin
        parts.append(100 if m > 0.20 else 75 if m > 0.10 else 50 if m > 0.03 else 20)
    if ev.promoter_pledging is not None and ev.promoter_pledging > 0.5:
        parts.append(10)  # heavily pledged promoter holding is a red flag regardless of other ratios

    if not parts:
        return None
    return _clip(sum(parts) / len(parts))


def technical_score(ev: TechnicalEvidence | None) -> float | None:
    if ev is None:
        return None
    score = 50.0
    contributed = False

    if ev.trend is not None:
        score += {"bullish": 20, "neutral": 0, "bearish": -20}.get(ev.trend, 0)
        contributed = True
    if ev.rsi_14 is not None:
        # Reward the healthy 40-60 band; penalize overbought/oversold extremes.
        distance_from_mid = abs(ev.rsi_14 - 50)
        score += max(-15, 10 - distance_from_mid * 0.5)
        contributed = True
    if ev.macd_hist is not None:
        score += 10 if ev.macd_hist > 0 else -10
        contributed = True
    if ev.volatility_30d is not None and ev.volatility_30d > 0.6:
        score -= 15  # excessive volatility is a quality concern, not just a risk-fit concern
        contributed = True

    return _clip(score) if contributed else None


def kronos_score(ev: KronosEvidence | None) -> float | None:
    if ev is None:
        return None
    direction_multiplier = {"bullish": 1, "neutral": 0, "bearish": -1}.get(ev.direction, 0)
    swing_magnitude = min(abs(ev.predicted_return) * 100 * 4, 40)  # cap a +/-10% forecast at +/-40 pts
    confidence = max(0.0, min(ev.confidence, 1.0))
    return _clip(50 + swing_magnitude * direction_multiplier * confidence)


def news_score(ev: NewsEvidence | None) -> float | None:
    if ev is None or ev.article_count == 0:
        return None
    return _clip(50 + ev.sentiment * 40 * ev.confidence)


def portfolio_score(ev: PortfolioEvidence | None, max_single_weight: float) -> float | None:
    if ev is None or ev.recommended_weight is None:
        return None
    if max_single_weight <= 0:
        return None
    return _clip(100 * (ev.recommended_weight / max_single_weight))


def volatility_band(volatility_30d: float | None) -> str | None:
    if volatility_30d is None:
        return None
    if volatility_30d < _VOL_LOW:
        return "low"
    if volatility_30d < _VOL_HIGH:
        return "moderate"
    return "high"


def risk_fit_score(user_risk_profile: str, ev: TechnicalEvidence | None) -> float | None:
    """Suitability of this stock's observed risk level for *this* user's risk
    profile (Section 21) -- objective market facts don't change, but the same
    facts score differently per user."""
    band = volatility_band(ev.volatility_30d if ev else None)
    if band is None or user_risk_profile not in _RISK_LADDER:
        return None
    distance = abs(_RISK_LADDER.index(user_risk_profile) - _VOL_LADDER.index(band))
    return {0: 100, 1: 60, 2: 20}[distance]
