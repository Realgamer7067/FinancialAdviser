"""V3 audit finding (2026-09-16, found testing against restored real data):
yfinance's `debtToEquity` field is returned already multiplied by 100 (e.g.
100.415 for an actual 1.0x ratio) -- every other fractional field yfinance
exposes (`revenueGrowth`, `returnOnEquity`, `profitMargins`, ...) is a plain
0-1-ish fraction, and both screening.yaml's `max_debt_to_equity` and
scoring.yaml's `debt_to_equity_bands` are written assuming a plain ratio.
Left unconverted, this silently excluded almost every real non-financial
company from screening while financial-sector tickers only "passed" because
yfinance doesn't populate `debtToEquity` for them at all (null skips the
check, not a real pass) -- looked exactly like a "financial sector only"
bug from the outside, but was really a unit-scale bug in this one field."""

import pytest

from app.providers.fundamentals import YFinanceFundamentalProvider, _safe_debt_to_equity


def test_debt_to_equity_is_converted_from_yfinance_percentage_to_a_plain_ratio():
    # A real-shaped yfinance `.info` value (BHARTIARTL's actual restored
    # figure from this session's dump) -- 100.415 in yfinance's raw
    # percentage convention is a 1.00415x ratio, not literally "100x debt".
    info = {"debtToEquity": 100.415}
    assert _safe_debt_to_equity(info) == pytest.approx(1.00415)


def test_debt_to_equity_missing_stays_none_not_zero():
    # yfinance genuinely omits this field for many financial-sector tickers
    # -- must stay an honest "unknown", never coerced to 0.0 (which would
    # look like "no debt" and wrongly pass every downstream check).
    assert _safe_debt_to_equity({}) is None
    assert _safe_debt_to_equity({"debtToEquity": None}) is None


def test_debt_to_equity_non_numeric_stays_none():
    assert _safe_debt_to_equity({"debtToEquity": "N/A"}) is None


@pytest.mark.asyncio
async def test_get_fundamentals_applies_the_conversion_end_to_end(monkeypatch):
    provider = YFinanceFundamentalProvider()
    symbol = next(iter(provider._by_symbol))

    def fake_fetch_info(_ticker: str) -> dict:
        return {"debtToEquity": 314.833, "returnOnEquity": 0.15}

    monkeypatch.setattr(YFinanceFundamentalProvider, "_fetch_info", staticmethod(fake_fetch_info))

    snapshot = await provider.get_fundamentals(symbol)

    assert snapshot is not None
    assert snapshot.debt_to_equity == pytest.approx(3.14833)
    # returnOnEquity is already a plain fraction in yfinance's own
    # convention -- must NOT also get divided by 100.
    assert snapshot.roe == pytest.approx(0.15)
