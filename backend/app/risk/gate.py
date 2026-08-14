"""Risk gate + NO_RECOMMENDATION logic (Section 20 hard requirement). Never
forces BUY/STRONG_CANDIDATE when evidence is thin, contradictory, or a poor
fit for the user -- "no high-confidence opportunity" is a valid, expected
outcome, not a failure."""

from typing import Literal

from app.core.config import scoring_config
from app.scoring.final_score import ScoreBreakdown

Recommendation = Literal["STRONG_CANDIDATE", "CANDIDATE", "WATCHLIST", "NO_RECOMMENDATION"]


def apply_risk_gate(breakdown: ScoreBreakdown, risk_fit_score: float | None) -> Recommendation:
    thresholds = scoring_config()["thresholds"]

    # Hard gates -- any one of these forces NO_RECOMMENDATION regardless of score.
    if breakdown.confidence_band == "low":
        return "NO_RECOMMENDATION"
    if breakdown.data_quality < 0.4:
        return "NO_RECOMMENDATION"
    if risk_fit_score is not None and risk_fit_score < 30:
        return "NO_RECOMMENDATION"  # excessively volatile for this user's risk profile

    score = breakdown.final_score
    if score >= thresholds["strong_candidate"]:
        return "STRONG_CANDIDATE"
    if score >= thresholds["candidate"]:
        return "CANDIDATE"
    if score >= thresholds["watchlist"]:
        return "WATCHLIST"
    return "NO_RECOMMENDATION"
