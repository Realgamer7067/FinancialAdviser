from datetime import date, datetime, timezone

from app.providers.base import FundamentalSnapshot
from app.services.fundamental_analysis import fill_derived_ratios, has_pledged_shares_risk


def _snapshot(**overrides) -> FundamentalSnapshot:
    base = dict(symbol="TCS", as_of_date=date.today(), retrieved_at=datetime.now(timezone.utc))
    base.update(overrides)
    return FundamentalSnapshot(**base)


def test_fills_ebitda_margin_when_derivable():
    snap = _snapshot(revenue=1000, ebitda=250, ebitda_margin=None)
    result = fill_derived_ratios(snap)
    assert result.ebitda_margin == 0.25


def test_does_not_overwrite_known_value():
    snap = _snapshot(revenue=1000, ebitda=250, ebitda_margin=0.5)
    result = fill_derived_ratios(snap)
    assert result.ebitda_margin == 0.5


def test_leaves_unknown_when_not_derivable():
    snap = _snapshot(revenue=None, ebitda=250, ebitda_margin=None)
    result = fill_derived_ratios(snap)
    assert result.ebitda_margin is None


def test_pledged_shares_risk_flagged_above_threshold():
    assert has_pledged_shares_risk(_snapshot(promoter_pledging=0.6)) is True
    assert has_pledged_shares_risk(_snapshot(promoter_pledging=0.3)) is False


def test_pledged_shares_risk_unknown_is_not_flagged():
    assert has_pledged_shares_risk(_snapshot(promoter_pledging=None)) is False
