"""P7 total returns: dividend scaling by later splits, reinvestment, and the cases that are skipped rather than guessed."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.portfolio_intelligence.market import total_return as tr

D = Decimal


def rows(closes, start=date(2024, 1, 1)):
    out, d = [], start
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"trade_date": d, "open": D(str(c)), "high": D(str(c)), "low": D(str(c)), "close": D(str(c)), "volume": 1000})
        d += timedelta(days=1)
    return out


def div(ex, amount, review=False):
    return {"ex_date": ex, "kind": "dividend", "amount": D(str(amount)), "price_factor": None, "needs_review": review}


def test_a_dividend_is_reinvested_at_the_ex_date_close():
    r = rows([100, 100, 100, 95, 95, 96])
    ex = r[3]["trade_date"]
    out = tr.prepare(r, [div(ex, 5)])
    assert out["applied"] == 1
    t = [float(x) for x in out["tr"]]
    assert t[:3] == [100, 100, 100] and t[3] == pytest.approx(100.0)          # a 5 drop on a 5 dividend is no loss in total return
    assert t[4] == pytest.approx(100.0) and t[5] == pytest.approx(100 * 96 / 95)


def test_total_return_exceeds_price_return_by_about_the_dividend_yield():
    closes = [100.0] * 250
    r = rows(closes)
    events = [div(r[i]["trade_date"], 1.0) for i in (60, 120, 180)]            # three Rs 1 dividends on a Rs 100 stock, price unchanged because the
    out = tr.prepare(r, events)                                                # price dips are not modeled here: TR must still rise by the cash paid
    assert float(out["tr"][-1]) == pytest.approx(100 * 1.01 ** 3, rel=1e-9)


def test_pre_split_dividends_are_scaled_by_later_splits_and_bonuses():
    r = rows([100.0] * 10)
    split = {"ex_date": r[6]["trade_date"], "kind": "bonus", "price_factor": D("0.5"), "needs_review": False}
    # a series that is already adjusted by the source: flat across the bonus ex-date, so the audit says "adjusted" and the factor applies to dividends
    out = tr.prepare(r, [div(r[3]["trade_date"], 10), split, div(r[8]["trade_date"], 10)])
    assert out["applied"] == 2
    t = [float(x) for x in out["tr"]]
    assert t[3] == pytest.approx(100 * 1.05)         # Rs 10 before a 1:1 bonus = Rs 5 in today's share terms (5% of 100), NOT 10%
    assert t[8] == pytest.approx(t[7] * 1.10)        # Rs 10 after the bonus is a full Rs 10


def test_a_split_still_raw_in_the_source_is_adjusted_and_also_scales_earlier_dividends():
    closes = [200.0] * 5 + [100.0] * 5                                         # price halves at index 5: the source did NOT adjust this bonus
    r = rows(closes)
    split = {"ex_date": r[5]["trade_date"], "kind": "bonus", "price_factor": D("0.5"), "needs_review": False}
    out = tr.prepare(r, [div(r[2]["trade_date"], 10), split])
    assert out["audit"][0]["status"] == "raw" and out["applied"] == 1
    t = [float(x) for x in out["tr"]]
    assert float(out["rows"][0]["close"]) == pytest.approx(100.0)              # prices adjusted into today's terms
    assert t[2] == pytest.approx(100 * 1.05)                                   # Rs 10 -> Rs 5 against a Rs 100 (adjusted) price


def test_unparseable_unsure_or_out_of_range_dividends_are_skipped_and_counted_not_guessed():
    r = rows([100.0] * 10)
    unsure = {"ex_date": r[6]["trade_date"], "kind": "bonus", "price_factor": D("0.9"), "needs_review": False}      # factor within 15% of 1: cannot tell if adjusted
    out = tr.prepare(r, [div(r[2]["trade_date"], 4), unsure, div(r[8]["trade_date"], 3), div(r[8]["trade_date"], 9, review=True), div(date(2020, 1, 1), 5), div(r[0]["trade_date"], 5)])
    assert out["skipped"] == {"needs_review": 1, "uncertain_scaling": 1, "outside_range": 2}                          # the first-day and pre-history ones are outside
    assert out["applied"] == 1                                                                                          # only the clean post-bonus dividend
    assert [round(float(x), 6) for x in out["tr"]][-1] == pytest.approx(100 * 1.03)


def test_a_dividend_on_a_non_trading_day_is_applied_on_the_next_stored_day():
    r = rows([100.0] * 6)
    saturday = r[2]["trade_date"] + timedelta(days=1) if r[2]["trade_date"].weekday() == 4 else r[2]["trade_date"] + timedelta(days=1)
    scaled = [{"ex_date": saturday, "amount": D(2)}]
    t = tr.build_tr([x["trade_date"] for x in r], [x["close"] for x in r], scaled)
    nxt = next(i for i, x in enumerate(r) if x["trade_date"] >= saturday)
    assert float(t[nxt]) == pytest.approx(102.0) and float(t[nxt - 1]) == pytest.approx(100.0)


def test_no_events_means_total_return_equals_price():
    r = rows([100, 101, 99, 103])
    out = tr.prepare(r, [])
    assert [float(x) for x in out["tr"]] == [100, 101, 99, 103] and out["applied"] == 0
    assert tr.prepare([], [])["tr"] == []


def test_a_future_split_the_data_does_not_reach_does_not_scale_earlier_dividends():
    r = rows([100.0] * 8)
    future = {"ex_date": r[-1]["trade_date"] + timedelta(days=30), "kind": "bonus", "price_factor": D("0.5"), "needs_review": False}
    out = tr.prepare(r, [div(r[3]["trade_date"], 10), future])
    assert float(out["tr"][3]) == pytest.approx(110.0)                           # prices are not adjusted for it yet, so neither is the dividend
