"""Deterministic risk-profile scorer (Section 2 hard requirement): raw
questionnaire answers -> risk_score/risk_profile. Qwen interprets this output;
it never computes or overrides it."""

from typing import Literal

from typing_extensions import TypedDict

DROP_20PCT_POINTS = {"sell_all": 0, "sell_some": 25, "hold": 60, "buy_more": 100}
PRIORITY_POINTS = {"capital_preservation": 0, "balanced_growth": 50, "maximum_growth": 100}
LOSS_TOLERANCE_POINTS = {"0_10": 0, "10_20": 25, "20_30": 50, "30_50": 75, "50_plus": 100}

# Small horizon nudge: longer horizons can absorb more volatility.
_HORIZON_NUDGE = [(3, -10), (7, -3), (15, 3), (999, 8)]


class RawRiskAnswers(TypedDict):
    portfolio_drop_20pct_reaction: str  # sell_all | sell_some | hold | buy_more
    priority: str  # capital_preservation | balanced_growth | maximum_growth
    loss_tolerance: str  # 0_10 | 10_20 | 20_30 | 30_50 | 50_plus


class RiskScoreResult(TypedDict):
    risk_score: int
    risk_profile: Literal["conservative", "moderate", "aggressive"]


def _horizon_nudge(years: int) -> int:
    for cutoff, nudge in _HORIZON_NUDGE:
        if years <= cutoff:
            return nudge
    return _HORIZON_NUDGE[-1][1]


def compute_risk_profile(raw_answers: RawRiskAnswers, investment_horizon_years: int) -> RiskScoreResult:
    missing = [
        key
        for key, mapping in [
            ("portfolio_drop_20pct_reaction", DROP_20PCT_POINTS),
            ("priority", PRIORITY_POINTS),
            ("loss_tolerance", LOSS_TOLERANCE_POINTS),
        ]
        if raw_answers.get(key) not in mapping
    ]
    if missing:
        raise ValueError(f"Missing/invalid risk questionnaire answers: {missing}")

    base = (
        DROP_20PCT_POINTS[raw_answers["portfolio_drop_20pct_reaction"]]
        + PRIORITY_POINTS[raw_answers["priority"]]
        + LOSS_TOLERANCE_POINTS[raw_answers["loss_tolerance"]]
    ) / 3

    score = base + _horizon_nudge(investment_horizon_years)
    score = max(0, min(100, round(score)))

    if score < 34:
        profile: Literal["conservative", "moderate", "aggressive"] = "conservative"
    elif score < 67:
        profile = "moderate"
    else:
        profile = "aggressive"

    return {"risk_score": score, "risk_profile": profile}
