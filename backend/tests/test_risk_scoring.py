import pytest

from app.risk.scoring import compute_risk_profile


def test_conservative_profile():
    answers = {"portfolio_drop_20pct_reaction": "sell_all", "priority": "capital_preservation", "loss_tolerance": "0_10"}
    result = compute_risk_profile(answers, investment_horizon_years=2)
    assert result["risk_profile"] == "conservative"
    assert 0 <= result["risk_score"] <= 100


def test_aggressive_profile():
    answers = {"portfolio_drop_20pct_reaction": "buy_more", "priority": "maximum_growth", "loss_tolerance": "50_plus"}
    result = compute_risk_profile(answers, investment_horizon_years=20)
    assert result["risk_profile"] == "aggressive"
    assert result["risk_score"] == 100  # base=100, horizon nudge clipped at 100


def test_moderate_profile():
    answers = {"portfolio_drop_20pct_reaction": "hold", "priority": "balanced_growth", "loss_tolerance": "20_30"}
    result = compute_risk_profile(answers, investment_horizon_years=7)
    assert result["risk_profile"] == "moderate"


def test_longer_horizon_nudges_score_up():
    answers = {"portfolio_drop_20pct_reaction": "hold", "priority": "balanced_growth", "loss_tolerance": "20_30"}
    short = compute_risk_profile(answers, investment_horizon_years=2)
    long = compute_risk_profile(answers, investment_horizon_years=20)
    assert long["risk_score"] > short["risk_score"]


def test_missing_answer_raises():
    answers = {"portfolio_drop_20pct_reaction": "hold", "priority": "balanced_growth", "loss_tolerance": "not_a_real_option"}
    with pytest.raises(ValueError):
        compute_risk_profile(answers, investment_horizon_years=5)


def test_partial_answers_raises():
    with pytest.raises(ValueError):
        compute_risk_profile({"priority": "balanced_growth"}, investment_horizon_years=5)
