from app.scoring.final_score import compute_final_score, compute_model_agreement


def test_model_agreement_full_consensus():
    agreement = compute_model_agreement(fundamental=85, technical_trend="bullish", kronos_direction="bullish", news=70)
    assert agreement == 1.0


def test_model_agreement_partial_consensus():
    # fundamental->bullish, technical->bullish, kronos->bearish, news->neutral: 2/4 agree
    agreement = compute_model_agreement(fundamental=85, technical_trend="bullish", kronos_direction="bearish", news=50)
    assert agreement == 0.5


def test_model_agreement_insufficient_signals_returns_conservative_default():
    agreement = compute_model_agreement(fundamental=None, technical_trend=None, kronos_direction="bullish", news=None)
    assert agreement == 0.4


def test_compute_final_score_all_evidence_present():
    sub_scores = {"fundamental": 90, "technical": 80, "kronos": 75, "news": 70, "portfolio": 60, "risk": 100}
    breakdown = compute_final_score(sub_scores, technical_trend="bullish", kronos_direction="bullish")
    assert breakdown.data_quality == 1.0
    assert 0 <= breakdown.final_score <= 100
    assert breakdown.confidence_band in ("high", "medium", "low")


def test_compute_final_score_missing_evidence_lowers_data_quality():
    sub_scores = {"fundamental": 90, "technical": None, "kronos": None, "news": None, "portfolio": None, "risk": None}
    breakdown = compute_final_score(sub_scores, technical_trend=None, kronos_direction=None)
    assert abs(breakdown.data_quality - 1 / 6) < 0.01  # data_quality is rounded to 2dp
    assert breakdown.confidence_band == "low"


def test_compute_final_score_no_evidence_at_all_is_zero():
    sub_scores = {k: None for k in ["fundamental", "technical", "kronos", "news", "portfolio", "risk"]}
    breakdown = compute_final_score(sub_scores, technical_trend=None, kronos_direction=None)
    assert breakdown.final_score == 0.0
    assert breakdown.data_quality == 0.0
    assert breakdown.confidence_band == "low"
