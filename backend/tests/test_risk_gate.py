from app.risk.gate import apply_risk_gate
from app.scoring.final_score import ScoreBreakdown


def _breakdown(**overrides) -> ScoreBreakdown:
    base = dict(
        fundamental=80,
        technical=75,
        kronos=70,
        news=65,
        portfolio=60,
        risk=90,
        final_score=85,
        model_agreement=0.9,
        data_quality=0.9,
        confidence=0.9,
        confidence_band="high",
    )
    base.update(overrides)
    return ScoreBreakdown(**base)


def test_high_score_high_confidence_is_strong_candidate():
    assert apply_risk_gate(_breakdown(final_score=85, confidence_band="high"), risk_fit_score=90) == "STRONG_CANDIDATE"


def test_mid_score_is_candidate():
    assert apply_risk_gate(_breakdown(final_score=70, confidence_band="high"), risk_fit_score=90) == "CANDIDATE"


def test_low_score_is_watchlist():
    assert apply_risk_gate(_breakdown(final_score=55, confidence_band="high"), risk_fit_score=90) == "WATCHLIST"


def test_very_low_score_is_no_recommendation():
    assert apply_risk_gate(_breakdown(final_score=30, confidence_band="high"), risk_fit_score=90) == "NO_RECOMMENDATION"


def test_low_confidence_forces_no_recommendation_even_with_high_score():
    assert apply_risk_gate(_breakdown(final_score=95, confidence_band="low"), risk_fit_score=90) == "NO_RECOMMENDATION"


def test_thin_data_forces_no_recommendation():
    assert (
        apply_risk_gate(_breakdown(final_score=95, confidence_band="high", data_quality=0.2), risk_fit_score=90)
        == "NO_RECOMMENDATION"
    )


def test_poor_risk_fit_forces_no_recommendation():
    assert apply_risk_gate(_breakdown(final_score=95, confidence_band="high"), risk_fit_score=10) == "NO_RECOMMENDATION"


def test_unknown_risk_fit_does_not_block():
    assert apply_risk_gate(_breakdown(final_score=85, confidence_band="high"), risk_fit_score=None) == "STRONG_CANDIDATE"


def test_high_volatility_regime_tightens_risk_fit_floor():
    # 40 clears the baseline floor (30) but not the high-volatility floor (45)
    # -- same evidence, different regime, different outcome (Section 33/20).
    breakdown = _breakdown(final_score=85, confidence_band="high")
    assert apply_risk_gate(breakdown, risk_fit_score=40, market_regime="bullish_low_volatility") == "STRONG_CANDIDATE"
    assert apply_risk_gate(breakdown, risk_fit_score=40, market_regime="bullish_high_volatility") == "NO_RECOMMENDATION"


def test_unknown_regime_uses_baseline_floor():
    assert (
        apply_risk_gate(_breakdown(final_score=85, confidence_band="high"), risk_fit_score=40, market_regime="unknown")
        == "STRONG_CANDIDATE"
    )
