"""Checklist score: pure-function behaviour on the cases that matter (negative EPS, banks, gaps, basis check)."""

from app.portfolio_intelligence.scoring import checklist as C
from app.portfolio_intelligence.scoring.checklist import StockInput
from sqlalchemy import select


def good(sym, sector="Information Technology", **kw):
    base = dict(symbol=sym, name=sym, sector=sector, price=100.0, eps=10.0, pe_stored=10.0, pb=2.0, ev_ebitda=8.0, roe=0.22, net_margin=0.22, eps_growth=0.18,
                revenue_growth=0.16, free_cash_flow=5.0, debt_to_equity=0.2, vol_252=0.18, max_dd_1y=-0.12)
    base.update(kw)
    return StockInput(**base)


def universe(n=10, **kw):
    return [good(f"S{i}", price=100.0 + 10 * i, pe_stored=10.0 + i, pb=1.0 + i * 0.3, ev_ebitda=6.0 + i, **kw) for i in range(n)]


def by(rows, sym):
    return next(r for r in rows if r["symbol"] == sym)


def test_cheaper_beats_dearer_on_the_same_fundamentals_and_inputs_are_shown():
    rows = C.score_universe(universe())
    assert by(rows, "S0")["score"] > by(rows, "S9")["score"]
    s0 = by(rows, "S0")
    assert set(s0["components"]) == {"valuation", "quality", "balance", "risk"} and s0["components"]["valuation"]["inputs"]["pe"] == 10.0
    assert s0["status"] == "eligible" and s0["coverage"] == 1.0 and s0["shown_only"] == {}


def test_negative_earnings_are_not_cheap_and_are_named():
    u = universe() + [good("LOSS", eps=-5.0, pe_stored=None, roe=-0.05, eps_growth=-0.4, net_margin=-0.03, free_cash_flow=-1.0)]
    r = by(C.score_universe(u), "LOSS")
    assert r["pe"] is None and any("not meaningful" in f for f in r["flags"])
    assert r["components"]["valuation"]["inputs"]["pe"] is None and "negative earnings (P/E not meaningful)" in r["reasons"]
    assert r["status"] == "below_floor" and r["score"] < C.FLOOR


def test_banks_are_compared_with_banks_and_never_on_debt_or_ev_ebitda():
    banks = [good(f"B{i}", sector="Financial Services", price=100.0 + 5 * i, pe_stored=9.0 + i, pb=1.0 + 0.2 * i, ev_ebitda=None, debt_to_equity=9.0, net_margin=None, free_cash_flow=None) for i in range(9)]
    rows = C.score_universe(universe() + banks)
    b0 = by(rows, "B0")
    assert b0["financial"] and "balance" not in b0["components"] and "ev_ebitda" not in b0["components"]["valuation"]["inputs"]
    assert b0["status"] == "eligible" and b0["coverage"] == 1.0       # coverage is measured against the components that apply to a bank
    assert not any("debt" in x for x in b0["reasons"])                # D/E of 9 would have been a red flag for an industrial; for a bank it is ignored


def test_missing_inputs_are_left_out_and_named_and_too_few_means_not_scored():
    r = by(C.score_universe(universe() + [good("GAP", roe=None, net_margin=None, eps_growth=None, revenue_growth=None, free_cash_flow=None)]), "GAP")
    assert r["components"]["quality"]["score"] is None and "quality" in r["missing"] and r["coverage"] == 0.65 and r["score"] is not None
    r = by(C.score_universe(universe() + [good("BARE", eps=None, pb=None, ev_ebitda=None, roe=None, net_margin=None, eps_growth=None, revenue_growth=None, free_cash_flow=None)]), "BARE")
    assert r["score"] is None and r["status"] == "not_scored" and r["coverage"] < C.MIN_COVERAGE


def test_a_pe_basis_mismatch_is_not_used():
    # stored P/E 10 at a price of 100 and EPS 10; a bonus-style change makes price / EPS = 40: far outside the band
    pe, flag = C.pe_of(good("X", price=100.0, eps=2.5, pe_stored=10.0))
    assert pe is None and "same basis" in flag
    assert C.pe_of(good("X", price=100.0, eps=10.0, pe_stored=10.0)) == (10.0, None)
    assert C.pe_of(good("X", price=90.0, eps=10.0, pe_stored=10.0))[0] == 9.0          # a price move inside the band is simply used


def test_price_signals_that_have_not_earned_a_weight_add_no_points():
    a = good("A"); b = good("B"); b.shown_only = {"trend": "below", "mom_12_1_rank": 3, "forecast_rank": 99}
    ra, rb = C.score_universe(universe() + [a])[-1], C.score_universe(universe() + [b])[-1]
    assert ra["score"] == rb["score"] and rb["shown_only"]["trend"] == "below"


async def test_the_plan_picks_the_best_scoring_liquid_stock_per_sector_and_a_low_scorer_is_never_picked_but_is_listed_with_reasons(db_session):
    from app.models.market import Instrument
    from app.portfolio_intelligence.allocation.select import select_candidates
    from app.portfolio_intelligence.allocation.service import stock_screen
    from tests.test_signals_p2 import EXPECTED, NOW, make_security, walk
    from tests.test_signals_p2 import sr as signals_run

    sectors = ["Energy", "Energy", "Energy", "IT", "IT", "IT", "Metals", "Metals", "Metals", "Metals"]
    stocks = []
    for i, sec in enumerate(sectors):
        inst = Instrument(symbol=f"S{i}", exchange="NSE", isin=f"INE00{i}A00011", name=f"S{i}", sector=sec)
        db_session.add(inst)
        await db_session.flush()
        s = await make_security(db_session, f"S{i}", walk(300, 100 + i), sector=sec)
        s.instrument_id = inst.id
        stocks.append(s)
    await db_session.commit()
    await signals_run.run_signals(db_session, NOW)

    # S0 is the cheapest Energy name, S2 the dearest; S9 (Metals) loses money and must be knocked out whatever else it scores
    inputs = [good(f"S{i}", sector=sec, price=100.0 + 10 * i, pe_stored=10.0 + i, pb=1.0 + 0.3 * i, ev_ebitda=6.0 + i) for i, sec in enumerate(sectors)]
    inputs[9] = good("S9", sector="Metals", eps=-3.0, pe_stored=None, roe=-0.04, eps_growth=-0.5, net_margin=-0.02, free_cash_flow=-1.0)
    rows = {r["symbol"]: {**r, "security_id": str(next(s.id for s in stocks if s.symbol == r["symbol"]))} for r in C.score_universe(inputs)}
    scores = {"version": C.CHECKLIST_VERSION, "rows": rows, "fundamentals_as_of": {"oldest": "2026-08-23", "newest": "2026-08-23"}}
    assert rows["S9"]["status"] == "below_floor" and rows["S0"]["score"] > rows["S2"]["score"]

    cands = await select_candidates(db_session, EXPECTED, scores)
    picked = {st["sector"]: st["symbol"] for st in cands["satellite"]}
    assert picked["Energy"] == "S0" and picked["IT"] == "S3" and picked["Metals"] == "S6"                 # cheapest, otherwise equal, in each sector
    assert "S9" not in {st["symbol"] for st in cands["satellite"]}                                      # the knocked-out stock is never a candidate
    assert [st["score"] for st in cands["satellite"]] == sorted((st["score"] for st in cands["satellite"]), reverse=True)

    legs = [{"role": "satellite", "symbol": "S0"}]
    screen = stock_screen(scores, cands, legs)
    by_sym = {r["symbol"]: r for r in screen["rows"]}
    assert by_sym["S0"]["status"] == "picked"
    assert by_sym["S1"]["status"] == "not_picked" and "S0 scores higher in Energy" in by_sym["S1"]["note"]
    low = by_sym["S9"]
    assert low["status"] == "low_score" and "below the 60 floor" in low["note"] and "negative earnings (P/E not meaningful)" in low["reasons"]
    assert screen["rows"][-1]["symbol"] == "S9" and screen["floor"] == 60.0 and "add no points" in screen["note"]


async def test_scores_are_stored_once_per_day_and_never_rewritten(client, db_session):
    from app.models.fundamentals import FundamentalMetrics
    from app.models.market import Instrument
    from app.models.securities import SecurityScore
    from app.portfolio_intelligence.scoring.service import current_scores
    from tests.test_signals_p2 import EXPECTED, NOW, make_security, walk
    from tests.test_signals_p2 import sr as signals_run
    from datetime import timedelta

    inst = Instrument(symbol="Z0", exchange="NSE", isin="INE00ZA00011", name="Z0", sector="IT")
    db_session.add(inst)
    await db_session.flush()
    s = await make_security(db_session, "Z0", walk(300, 5), sector="IT")
    s.instrument_id = inst.id
    db_session.add(FundamentalMetrics(instrument_id=inst.id, as_of_date=EXPECTED, eps=10.0, pe=10.0, roe=0.2, retrieved_at=NOW, source="t"))
    await db_session.commit()
    await signals_run.run_signals(db_session, NOW)

    first = await current_scores(db_session, now=NOW)
    rows = (await db_session.execute(select(SecurityScore))).scalars().all()
    assert len(rows) == 1 and rows[0].method_version == C.CHECKLIST_VERSION and rows[0].fundamentals_as_of == EXPECTED
    stored = (rows[0].computed_at, rows[0].score, dict(rows[0].detail))
    await current_scores(db_session, now=NOW + timedelta(hours=3))                      # same price day: nothing new, nothing rewritten
    again = (await db_session.execute(select(SecurityScore))).scalars().all()
    assert len(again) == 1 and (again[0].computed_at, again[0].score, dict(again[0].detail)) == stored
    assert first["rows"]["Z0"]["security_id"] == str(s.id)

    resp = (await client.get("/api/v4/allocation/stock-scores")).json()
    assert resp["version"] == C.CHECKLIST_VERSION and resp["floor"] == 60.0 and {r["symbol"] for r in resp["rows"]} == {"Z0"}
