"""Risk gate + NO_RECOMMENDATION logic (Section 20 hard requirement). Never
forces BUY/STRONG_CANDIDATE when evidence is thin, contradictory, or a poor
fit for the user -- "no high-confidence opportunity" is a valid, expected
outcome, not a failure."""

from typing import Literal

from app.core.config import scoring_config
from app.scoring.final_score import ScoreBreakdown

Recommendation = Literal["STRONG_CANDIDATE", "CANDIDATE", "WATCHLIST", "NO_RECOMMENDATION"]


def apply_risk_gate(
    breakdown: ScoreBreakdown, risk_fit_score: float | None, market_regime: str | None = None
) -> Recommendation:
    thresholds = scoring_config()["thresholds"]

    # Hard gates -- any one of these forces NO_RECOMMENDATION regardless of score.
    if breakdown.confidence_band == "low":
        return "NO_RECOMMENDATION"
    if breakdown.data_quality < 0.4:
        return "NO_RECOMMENDATION"

    # In a high-volatility regime, require a better risk-fit than the baseline
    # floor before letting anything past -- previously `market_regime` was
    # computed but only ever handed to the LLM planner, never consulted here,
    # so "dynamic risk gating" didn't actually exist.
    risk_fit_floor = thresholds["risk_fit_floor"]
    if market_regime is not None and market_regime.endswith("_high_volatility"):
        risk_fit_floor = thresholds["high_volatility_risk_fit_floor"]
    if risk_fit_score is not None and risk_fit_score < risk_fit_floor:
        return "NO_RECOMMENDATION"  # excessively volatile for this user's risk profile / current regime

    score = breakdown.final_score
    if score >= thresholds["strong_candidate"]:
        return "STRONG_CANDIDATE"
    if score >= thresholds["candidate"]:
        return "CANDIDATE"
    if score >= thresholds["watchlist"]:
        return "WATCHLIST"
    return "NO_RECOMMENDATION"
