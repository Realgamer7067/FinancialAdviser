from app.scoring.evidence import FundamentalEvidence, KronosEvidence, NewsEvidence, PortfolioEvidence, TechnicalEvidence
from app.scoring.subscores import (
    fundamental_score,
    kronos_score,
    news_score,
    portfolio_score,
    risk_fit_score,
    risk_tier,
    risk_tier_score,
    risk_tier_score_with_breakdown,
    technical_score,
)


def test_fundamental_score_strong_company_scores_high():
    ev = FundamentalEvidence(roe=0.25, revenue_growth=0.20, debt_to_equity=0.3, pe=12, net_margin=0.22, promoter_pledging=None)
    assert fundamental_score(ev) >= 85


def test_fundamental_score_weak_company_scores_low():
    ev = FundamentalEvidence(roe=0.02, revenue_growth=-0.05, debt_to_equity=4.0, pe=60, net_margin=0.01, promoter_pledging=0.7)
    assert fundamental_score(ev) <= 30


def test_fundamental_score_none_when_no_data():
    ev = FundamentalEvidence(roe=None, revenue_growth=None, debt_to_equity=None, pe=None, net_margin=None, promoter_pledging=None)
    assert fundamental_score(ev) is None


def test_fundamental_score_none_evidence():
    assert fundamental_score(None) is None


def test_technical_score_bullish_trend_scores_above_baseline():
    ev = TechnicalEvidence(rsi_14=55, trend="bullish", volatility_30d=0.2, drawdown_1y=-0.05, macd_hist=0.5, beta=None)
    assert technical_score(ev) > 50


def test_technical_score_bearish_trend_scores_below_baseline():
    ev = TechnicalEvidence(rsi_14=50, trend="bearish", volatility_30d=0.2, drawdown_1y=-0.3, macd_hist=-0.5, beta=None)
    assert technical_score(ev) < 50


def test_technical_score_bounds_clip_at_100():
    ev = TechnicalEvidence(rsi_14=50, trend="bullish", volatility_30d=0.1, drawdown_1y=0, macd_hist=1.0, beta=None)
    score = technical_score(ev)
    assert score is not None and 0 <= score <= 100


def _kronos_ev(direction, predicted_return, confidence, direction_agreement=0.9):
    return KronosEvidence(
        forecast_horizon="30d",
        direction=direction,
        predicted_return=predicted_return,
        predicted_return_p10=predicted_return - 0.02,
        predicted_return_p90=predicted_return + 0.02,
        direction_agreement=direction_agreement,
        sample_count=8,
        confidence=confidence,
    )


def test_kronos_score_bullish_forecast_above_baseline():
    ev = _kronos_ev("bullish", 0.05, 0.8)
    assert kronos_score(ev) > 50


def test_kronos_score_neutral_forecast_is_none():
    # A neutral call is "no directional evidence," not "evidence of no
    # movement" -- must be excluded, not silently contribute the midpoint (50).
    ev = _kronos_ev("neutral", 0.0, 0.5)
    assert kronos_score(ev) is None


def test_kronos_score_bearish_forecast_below_baseline():
    ev = _kronos_ev("bearish", -0.06, 0.9)
    assert kronos_score(ev) < 50


def test_kronos_score_none_when_no_forecast():
    assert kronos_score(None) is None


def test_kronos_score_none_when_confidence_too_low():
    # A near-zero-confidence forecast must be excluded like any other missing
    # signal, not silently contribute the neutral midpoint (50) as if real.
    ev = _kronos_ev("bullish", 0.05, 0.05)
    assert kronos_score(ev) is None


def test_kronos_score_none_when_confidence_uncalibrated():
    # No calibration table exists yet for this (model_version, horizon,
    # direction_agreement bucket) -- must be excluded, never guessed.
    ev = _kronos_ev("bullish", 0.05, None)
    assert kronos_score(ev) is None


def test_news_score_positive_sentiment_above_baseline():
    ev = NewsEvidence(sentiment=0.6, confidence=0.9, article_count=5)
    assert news_score(ev) > 50


def test_news_score_none_when_no_articles():
    ev = NewsEvidence(sentiment=0.0, confidence=0.0, article_count=0)
    assert news_score(ev) is None


def test_portfolio_score_scales_with_recommended_weight():
    ev = PortfolioEvidence(recommended_weight=0.25, expected_sharpe=1.2)
    assert portfolio_score(ev, max_single_weight=0.25) == 100


def test_portfolio_score_none_when_not_recommended():
    assert portfolio_score(PortfolioEvidence(recommended_weight=None, expected_sharpe=None), 0.25) is None


def test_risk_fit_score_matches_volatility_to_user_profile():
    low_vol = TechnicalEvidence(rsi_14=50, trend="neutral", volatility_30d=0.10, drawdown_1y=-0.05, macd_hist=0, beta=None)
    high_vol = TechnicalEvidence(rsi_14=50, trend="neutral", volatility_30d=0.60, drawdown_1y=-0.05, macd_hist=0, beta=None)

    assert risk_fit_score("conservative", low_vol) == 100
    assert risk_fit_score("conservative", high_vol) == 20
    assert risk_fit_score("aggressive", high_vol) == 100


def test_risk_fit_score_none_when_volatility_unknown():
    ev = TechnicalEvidence(rsi_14=50, trend="neutral", volatility_30d=None, drawdown_1y=None, macd_hist=None, beta=None)
    assert risk_fit_score("moderate", ev) is None


def test_risk_tier_score_none_when_fewer_than_min_inputs():
    # Only volatility present (1 signal) -- min_inputs is 2, so this must stay
    # None rather than silently classify off a single incomplete signal.
    ev = TechnicalEvidence(rsi_14=50, trend="neutral", volatility_30d=0.30, drawdown_1y=None, macd_hist=None, beta=None)
    assert risk_tier_score(ev, None) is None
    assert risk_tier(ev, None) is None


def test_risk_tier_score_with_breakdown_none_when_fewer_than_min_inputs():
    ev = TechnicalEvidence(rsi_14=50, trend="neutral", volatility_30d=0.30, drawdown_1y=None, macd_hist=None, beta=None)
    score, breakdown = risk_tier_score_with_breakdown(ev, None)
    assert score is None
    assert breakdown is None


def test_risk_tier_score_with_breakdown_matches_plain_score_and_exposes_parts():
    technical_ev = TechnicalEvidence(
        rsi_14=50, trend="neutral", volatility_30d=0.10, drawdown_1y=-0.05, macd_hist=0, beta=0.5
    )
    fundamental_ev = FundamentalEvidence(
        roe=0.15, revenue_growth=0.1, debt_to_equity=0.3, pe=20, net_margin=0.1, promoter_pledging=None
    )
    score, breakdown = risk_tier_score_with_breakdown(technical_ev, fundamental_ev)
    assert score == risk_tier_score(technical_ev, fundamental_ev)
    assert set(breakdown.keys()) == {"volatility_30d", "drawdown_1y", "beta", "debt_to_equity"}
    assert all(0 <= v <= 100 for v in breakdown.values())


def test_risk_tier_low_signals_across_the_board_is_safer():
    technical_ev = TechnicalEvidence(
        rsi_14=50, trend="neutral", volatility_30d=0.10, drawdown_1y=-0.05, macd_hist=0, beta=0.5
    )
    fundamental_ev = FundamentalEvidence(
        roe=0.15, revenue_growth=0.1, debt_to_equity=0.3, pe=20, net_margin=0.1, promoter_pledging=None
    )
    assert risk_tier(technical_ev, fundamental_ev) == "safer"


def test_risk_tier_high_signals_across_the_board_is_riskiest():
    technical_ev = TechnicalEvidence(
        rsi_14=50, trend="neutral", volatility_30d=0.70, drawdown_1y=-0.55, macd_hist=0, beta=2.0
    )
    fundamental_ev = FundamentalEvidence(
        roe=0.05, revenue_growth=0.0, debt_to_equity=4.0, pe=None, net_margin=0.02, promoter_pledging=None
    )
    assert risk_tier(technical_ev, fundamental_ev) == "riskiest"


def test_risk_tier_uses_available_subset_when_fundamentals_missing():
    # 3 of 4 technical signals present, fundamentals entirely absent -- still
    # above min_inputs, so this must classify off the technical subset alone.
    technical_ev = TechnicalEvidence(
        rsi_14=50, trend="neutral", volatility_30d=0.15, drawdown_1y=-0.05, macd_hist=0, beta=0.6
    )
    assert risk_tier(technical_ev, None) == "safer"
