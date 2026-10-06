"""P3: allocation policy, holdings classification, buy-only plan, candidate selection, whole-plan evaluation, immutable records."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.market import Instrument
from app.models.securities import AllocationPlan, Security
from app.portfolio_intelligence.allocation import policy as P
from app.portfolio_intelligence.allocation import plan as pl
from app.portfolio_intelligence.allocation.classify import classify_positions
from app.portfolio_intelligence.decisions import engine
from tests.test_signals_p2 import EXPECTED, NOW, make_security, walk
from tests.test_signals_p2 import sr as signals_run

D = Decimal
ASOF = date(2026, 9, 30)
FEE = P.FEE_PCT


def inst(symbol, price, *, lot=1, kind="etf", sector=None, cash_like=False, iid=None):
    return {"id": iid or str(uuid.uuid4()), "symbol": symbol, "name": symbol, "kind": kind, "isin": f"INF{symbol[:6].upper():0<9}"[:12], "lot_size": lot, "price": D(str(price)),
            "price_as_of": ASOF, "sector": sector, "turnover": 5e8, "why": "test", "cash_like": cash_like}


def cands(**over):
    c = {"core": {"large": inst("NIFTYBEES", 256.5), "next50": inst("JUNIORBEES", 70.2), "mid150": inst("MIDCAP", 21.8)},
         "gold": [inst("GOLDBEES", 80.1)], "debt": [inst("LIQUIDCASE", 116.2, cash_like=True)], "satellite": []}
    c.update(over)
    return c


def sats(n):
    return [inst(f"STK{i}", 400 + 100 * i, kind="stock", sector=f"Sector{i}", iid=str(uuid.uuid4())) for i in range(n)]


READY = {"status": "ready", "band": "moderate", "score": 50}
OPEN = {"risk_increasing_allowed": True, "limiting_factors": []}
EMPTY = {"buckets": {}, "unknown": D(0), "cash": D(0), "rows": [], "unvalued": 0}


def make(new_money, *, tolerance=READY, constraints=OPEN, what_if=None, holdings=EMPTY, claimed=D(0), candidates=None):
    return pl.build_plan(tolerance=tolerance, constraints=constraints, what_if_band=what_if, new_money=D(str(new_money)), holdings=holdings,
                         short_horizon_claimed=claimed, candidates=candidates or cands())


def by_bucket(plan):
    out = {}
    for l in plan["legs"]:
        out[l["bucket"]] = out.get(l["bucket"], D(0)) + D(l["planned_debit"])
    return out


# --- classification ---------------------------------------------------------------------------------------------------------

def pos(pid, asset_type, value, isin=None):
    return {"position_id": pid, "asset_type": asset_type, "isin": isin, "value": None if value is None else D(str(value)), "label": pid}


def test_classification_uses_the_catalogue_by_isin_and_keeps_unknown_separate():
    cat = {"INF000A00011": {"asset_class": "equity"}, "INF000B00011": {"asset_class": "gold"}, "INF000C00011": {"asset_class": "debt"}, "INF000D00011": {"asset_class": "hybrid"},
           "INF000E00011": {"asset_class": "international"}, "INF000F00011": {"asset_class": "silver"}}
    rows = [pos("e", "etf", 100, "INF000A00011"), pos("g", "etf", 50, "INF000B00011"), pos("d", "mutual_fund", 70, "INF000C00011"), pos("h", "mutual_fund", 30, "INF000D00011"),
            pos("i", "etf", 20, "INF000E00011"), pos("s", "etf", 10, "INF000F00011"), pos("cash", "cash", 999), pos("fd", "deposit", 40), pos("stk", "listed_equity", 60, "INE999Z01019"),
            pos("mystery", "etf", 15, "INF999Z00019"), pos("none", "other", 5), pos("unv", "etf", None)]
    r = classify_positions(rows, cat)
    assert r["buckets"] == {"equity_india": D(160), "gold": D(60), "debt": D(110), "equity_intl": D(20)}   # equity 100 + stock 60 (declared); gold 50 + silver 10; debt 70 + FD 40
    assert r["unknown"] == D(50) and r["cash"] == D(999) and r["unvalued"] == 1                           # hybrid 30 + unmatched ETF 15 + other 5
    basis = {x["position_id"]: x["basis"] for x in r["rows"]}
    assert basis["e"] == "catalogue" and basis["stk"] == "declared" and basis["cash"] == "not part of the allocation" and basis["unv"] == "unvalued"


# --- policy / mix ------------------------------------------------------------------------------------------------------------

def test_every_band_mix_sums_to_one_and_the_policy_is_declared():
    for band, m in P.MIX.items():
        assert sum(m.values()) == 1, band
    d = P.declared()
    assert d["status"] == "unreviewed placeholders" and d["version"] == "allocation-p0-unreviewed" and "international_etfs" in d


def test_gate_order_unknown_tolerance_then_capacity_then_band():
    unknown = pl.decide_mix(tolerance={"status": "unknown", "band": None}, constraints=OPEN, what_if_band=None)
    assert unknown["source"] == "safe_only_no_tolerance" and unknown["mix"] == P.SAFE_ONLY and unknown["needs_input"]
    blocked = pl.decide_mix(tolerance=READY, constraints={"risk_increasing_allowed": False, "limiting_factors": ["reserve_shortfall"]}, what_if_band=None)
    assert blocked["source"] == "safe_only_capacity" and blocked["mix"] == P.SAFE_ONLY and "reserve_shortfall" in blocked["reasons"][0]
    ok = pl.decide_mix(tolerance=READY, constraints=OPEN, what_if_band=None)
    assert ok["source"] == "profile_band" and ok["band"] == "moderate" and not ok["needs_input"]
    what_if = pl.decide_mix(tolerance={"status": "unknown", "band": None}, constraints={"risk_increasing_allowed": False, "limiting_factors": ["tolerance_unknown"]}, what_if_band="aggressive")
    assert what_if["source"] == "what_if_band" and what_if["mix"] == P.MIX["aggressive"] and what_if["needs_input"]
    with pytest.raises(ValueError):
        pl.decide_mix(tolerance=READY, constraints=OPEN, what_if_band="reckless")


# --- the plan ----------------------------------------------------------------------------------------------------------------------

def test_empty_portfolio_moderate_buys_each_bucket_to_target_with_whole_units():
    plan = make(50000)
    assert plan["status"] == "ready" and plan["mix"]["source"] == "profile_band"
    tgt = {b: D(plan["target"][b]["value"]) for b in P.BUCKETS}
    assert tgt["equity_intl"] == 0 and tgt["equity_india"] == D(25000) and tgt["gold"] == D(5000) and tgt["debt"] == D(20000)     # 5% international moved to India
    assert any("premium" in w for w in plan["warnings"])
    spent = by_bucket(plan)
    assert abs(spent["equity_india"] - 25000) < 300 and abs(spent["gold"] - 5000) < 100 and abs(spent["debt"] - 20000) < 150
    assert all(l["units"] > 0 and int(l["units"]) == l["units"] for l in plan["legs"])
    assert D(plan["spent"]) + D(plan["leftover_cash"]) == D(50000) and D(plan["leftover_cash"]) >= 0
    roles = {(l["bucket"], l.get("underlying")) for l in plan["legs"]}
    assert {("equity_india", "large"), ("equity_india", "next50"), ("equity_india", "mid150"), ("gold", None), ("debt", None)} <= roles
    assert not any(l["role"] == "satellite" for l in plan["legs"])                                           # 15% of 25,000 over 5 stocks is under the minimum leg


def test_tolerance_unknown_gives_a_safe_only_plan_that_asks_for_the_answers():
    plan = make(50000, tolerance={"status": "unknown", "band": None}, constraints={"risk_increasing_allowed": False, "limiting_factors": ["tolerance_unknown"]})
    assert plan["status"] == "needs_input" and {l["bucket"] for l in plan["legs"]} == {"debt"} and "risk tolerance is not known" in plan["reasons"][0]
    assert D(plan["spent"]) > 49000


def test_capacity_block_such_as_a_reserve_shortfall_keeps_money_in_the_safe_bucket():
    plan = make(30000, constraints={"risk_increasing_allowed": False, "limiting_factors": ["reserve_shortfall"]})
    assert plan["status"] == "needs_input" and {l["bucket"] for l in plan["legs"]} == {"debt"} and "reserve_shortfall" in plan["reasons"][0]


def test_what_if_shows_the_band_mix_but_stays_needs_input():
    plan = make(100000, tolerance={"status": "unknown", "band": None}, constraints={"risk_increasing_allowed": False, "limiting_factors": ["tolerance_unknown"]}, what_if="aggressive")
    assert plan["mix"] == {"source": "what_if_band", "band": "aggressive", "needs_input": True} and plan["status"] == "needs_input"
    assert D(plan["target"]["equity_india"]["weight"]) == D("0.75")                                          # 65% + the 10% international moved
    assert {"equity_india", "gold", "debt"} <= {l["bucket"] for l in plan["legs"]}


def test_money_claimed_for_short_horizon_goals_is_held_safe_first():
    plan = make(50000, tolerance={"status": "ready", "band": "aggressive"}, claimed=D(20000))
    assert D(plan["target"]["debt"]["value"]) == D(20000)                                                    # 15% would be 7,500; the claim raises it
    assert D(plan["target"]["equity_india"]["value"]) + D(plan["target"]["gold"]["value"]) == D(30000)
    assert any("claimed for goals due within 3 years" in w for w in plan["warnings"])


def test_a_small_amount_becomes_fewer_larger_legs_that_clear_the_minimum():
    plan = make(2500)
    assert plan["legs"], "something should still be bought"
    for l in plan["legs"]:
        assert D(l["planned_debit"]) >= P.MIN_LEG_AMOUNT, l                                                  # nothing the engine would reject for size
    assert len(plan["legs"]) <= 2 and D(plan["spent"]) <= D(2500)


def test_over_target_bucket_gets_no_sale_and_no_new_money():
    holdings = {"buckets": {"debt": D(90000), "equity_india": D(10000)}, "unknown": D(0), "cash": D(0), "rows": [], "unvalued": 0}
    plan = make(10000, holdings=holdings)
    debt = next(d for d in plan["drift"] if d["bucket"] == "debt")
    assert debt["direction"] == "above target" and "no sale is suggested" in debt["note"]
    assert "debt" not in by_bucket(plan) and all(l["units"] > 0 for l in plan["legs"])                    # buy-only: new money goes where it is short
    assert "No sale is ever suggested" in plan["no_sales_note"]


def test_a_large_unknown_share_means_needs_input():
    holdings = {"buckets": {"equity_india": D(50000)}, "unknown": D(30000), "cash": D(0), "rows": [], "unvalued": 0}
    plan = make(20000, holdings=holdings)
    assert plan["status"] == "needs_input" and any("could not be placed" in r for r in plan["reasons"]) and plan["unknown_share"] == "0.375"
    ok = make(20000, holdings={"buckets": {"equity_india": D(50000)}, "unknown": D(5000), "cash": D(0), "rows": [], "unvalued": 0})
    assert ok["status"] == "ready"


def test_no_money_and_inside_the_band_is_nothing_to_do():
    holdings = {"buckets": {"equity_india": D(50000), "gold": D(10000), "debt": D(40000)}, "unknown": D(0), "cash": D(0), "rows": [], "unvalued": 0}
    plan = make(0, holdings=holdings)
    assert plan["status"] == "nothing_to_do" and plan["legs"] == [] and not any(d["outside_band"] for d in plan["drift"])


def test_leftovers_are_spent_a_lot_at_a_time_and_never_overspent():
    c = cands(core={"large": inst("BIGLOT", 1999.0, lot=3), "next50": inst("JUNIORBEES", 70.2), "mid150": inst("MIDCAP", 21.8)}, debt=[inst("LIQUIDCASE", 116.2, cash_like=True)])
    plan = make(60000, candidates=c)
    assert D(plan["spent"]) <= D(60000) and D(plan["leftover_cash"]) >= 0
    cheapest_step = min(pl.debit_for(l["units"] + (3 if l["symbol"] == "BIGLOT" else 1), D(l["price"]), FEE) - pl.debit_for(l["units"], D(l["price"]), FEE) for l in plan["legs"])
    assert D(plan["leftover_cash"]) < cheapest_step                                                         # nothing more can be bought
    big = next(l for l in plan["legs"] if l["symbol"] == "BIGLOT")
    assert big["units"] % 3 == 0


def test_satellite_stocks_need_enough_money_one_per_sector_equal_weight_and_a_cap():
    big = make(2_000_000, tolerance={"status": "ready", "band": "aggressive"}, candidates=cands(satellite=sats(6)))
    stocks = [l for l in big["legs"] if l["role"] == "satellite"]
    assert len(stocks) == 5 and len({l["sector"] for l in stocks}) == 5
    cap = P.SATELLITE_MAX_WEIGHT_OF_PORTFOLIO * D(big["base_total_after_plan"])
    assert all(D(l["planned_debit"]) <= cap for l in stocks)                                                # a HARD cap: leftover rounding never exceeds 3% of the portfolio
    assert any("capped" in w for w in big["warnings"])
    mid = make(10000, tolerance={"status": "ready", "band": "aggressive"}, candidates=cands(satellite=sats(6)))
    assert not any(l["role"] == "satellite" for l in mid["legs"]) and any("at least three separate stocks" in w for w in mid["warnings"])
    small = make(60000, tolerance={"status": "ready", "band": "aggressive"}, candidates=cands(satellite=sats(6)))          # 25% of 45,000 = 11,250: even 3 stocks would be under Rs 5,000 each
    assert not any(l["role"] == "satellite" for l in small["legs"])
    three = make(100000, tolerance={"status": "ready", "band": "aggressive"}, candidates=cands(satellite=sats(6)))        # 18,750 -> 3 stocks of 6,250 (5 or 4 would be under the minimum)
    assert len([l for l in three["legs"] if l["role"] == "satellite"]) == 3
    enough = make(400000, tolerance={"status": "ready", "band": "aggressive"}, candidates=cands(satellite=sats(6)))        # 75,000 over 5 stocks = 15,000 each
    assert len([l for l in enough["legs"] if l["role"] == "satellite"]) == 5 and all(D(l["planned_debit"]) >= P.SATELLITE_MIN_LEG * D("0.95") for l in enough["legs"] if l["role"] == "satellite")
    cons = make(2_000_000, tolerance={"status": "ready", "band": "conservative"}, candidates=cands(satellite=sats(6)))
    assert not any(l["role"] == "satellite" for l in cons["legs"]) and {l.get("underlying") for l in cons["legs"] if l["bucket"] == "equity_india"} == {"large"}


def test_a_bucket_with_no_instrument_is_reported_and_its_money_moves_on():
    plan = make(50000, candidates=cands(gold=[]))
    assert any("no suitable instrument was found for Gold" in w for w in plan["warnings"]) and "gold" not in by_bucket(plan)
    assert D(plan["spent"]) > 49000                                                                          # the gold share was re-spread, not lost


def test_negative_money_is_refused():
    with pytest.raises(ValueError):
        make(-1)


# --- engine bridge: fractional units + whole-plan evaluation ----------------------------------------------------------------------------------

def engine_ctx(plan, *, constraints=OPEN, baseline=None, extra_insts=None):
    from app.portfolio_intelligence.personal.facts import compute_capacity

    cap = compute_capacity({"monthly_income": 100000, "monthly_essential_expenses": 30000, "emergency_reserve_amount": 300000, "emergency_reserve_months_target": 6}, [])
    insts, prices, actions = dict(extra_insts or {}), {}, []
    for l in plan["legs"]:
        insts[l["engine_key"]] = {"symbol": l["symbol"], "sector": l["sector"], "isin": l["isin"], "lot_size": 1, "asset_type": "listed_equity" if l["kind"] == "stock" else "etf", "cash_like": l["cash_like"]}
        prices[l["engine_key"]] = {"price": D(l["price"]), "as_of": date.fromisoformat(l["price_as_of"])}
        actions.append({"type": "BUY", "instrument_id": l["engine_key"], "amount": D(l["budget_for_engine"]), "funding": "new_money", "account_label": "Plan"})
    return {"baseline": baseline or [], "claims": {}, "capacity": cap, "constraints": {**constraints, "ceilings": []}, "restrictions": [], "instruments": insts, "prices": prices,
            "commitments": {}, "goals": {}, "budget": {}, "contribution": D(plan["new_money"]), "withdrawal": D(0), "actions": actions, "priorities": [], "fee_pct": FEE, "today": ASOF}


def test_the_engine_buys_exactly_the_planned_units_and_conserves_money_to_the_paisa():
    plan = make(50000)
    ev = engine.evaluate_plan(engine_ctx(plan))
    assert ev["status"] == "gates_pass" and ev["accounting"]["conserved"] is True and ev["accounting"]["residual"] == "0"
    for planned, leg in zip(plan["legs"], ev["legs"]):
        assert leg["cost"]["units"] == planned["units"], (planned["symbol"], leg["cost"], planned["units"])                  # budget_for_engine reproduces the planned units
        assert D(leg["cost"]["trade_value"]) + D(leg["cost"]["friction"]) == D(planned["planned_debit"])
    assert D(ev["accounting"]["assets_after"]) + D(ev["accounting"]["friction"]) == D(50000)                                    # the leftover cash is still assets


def test_the_engine_comparison_with_hold_is_a_caveated_tradeoff_not_the_status():
    plan = make(50000)
    ev = engine.evaluate_plan(engine_ctx(plan))
    rows = {r["metric"]: r for r in ev["comparison_vs_hold"]["rows"]}
    assert rows["cash_months"]["verdict"] == "worsened" and rows["unknown_weight"]["verdict"] == "worsened"                       # the engine cannot look inside ETFs
    assert ev["status"] == "gates_pass" and "limits of the metrics" in ev["comparison_caveat"]


def test_risk_legs_are_blocked_when_tolerance_is_unknown_but_a_liquid_etf_is_not():
    unknown = {"risk_increasing_allowed": False, "limiting_factors": ["tolerance_unknown"]}
    safe = make(50000, tolerance={"status": "unknown", "band": None}, constraints=unknown)
    assert engine.evaluate_plan(engine_ctx(safe, constraints=unknown))["status"] == "gates_pass"                       # liquid ETF = cash-like, not added risk
    risky = make(50000, what_if="moderate", tolerance={"status": "unknown", "band": None}, constraints=unknown)
    ev = engine.evaluate_plan(engine_ctx(risky, constraints=unknown))
    assert ev["status"] == "needs_input" and any(g["gate_id"] == "risk_capacity" and g["result"] == "unknown" for g in ev["final_gates"])


def test_a_leg_that_fails_a_gate_blocks_the_plan_and_nothing_is_applied_for_it():
    plan = make(50000)
    ctx = engine_ctx(plan)
    ctx["restrictions"] = [{"kind": "exclude_asset_type", "value": "etf"}]
    ev = engine.evaluate_plan(ctx)
    assert ev["status"] == "blocked" and any("excluded" in r or "you excluded" in r for r in ev["reasons"])


def test_fractional_fund_units_conserve_money_and_never_exceed_the_budget():
    from app.portfolio_intelligence.personal.facts import compute_capacity

    cap = compute_capacity({}, [])
    ctx = {"baseline": [], "claims": {}, "capacity": cap, "constraints": {"risk_increasing_allowed": True, "limiting_factors": [], "ceilings": []}, "restrictions": [],
           "instruments": {"fund": {"symbol": "XFUND", "sector": None, "isin": "INF000X00019", "lot_size": 1, "asset_type": "mutual_fund", "fractional": True}},
           "prices": {"fund": {"price": D("37.5912"), "as_of": ASOF}}, "commitments": {}, "goals": {}, "budget": {}, "contribution": D("5000"), "withdrawal": D(0),
           "actions": [{"type": "BUY", "instrument_id": "fund", "amount": D("5000"), "funding": "new_money", "account_label": "Plan"}], "priorities": [], "fee_pct": FEE, "today": ASOF}
    ev = engine.evaluate_plan(ctx)
    leg = ev["legs"][0]
    units = D(leg["cost"]["units"])
    assert units != units.to_integral_value() and units % D("0.001") == 0                                    # fractional, in thousandths
    assert D(leg["cost"]["trade_value"]) + D(leg["cost"]["friction"]) <= D(5000)
    assert ev["accounting"]["conserved"] is True and ev["accounting"]["residual"] == "0"


# --- DB: candidates, plan service, immutability ----------------------------------------------------------------------------------------------

async def seed_market(db):
    """Catalogue + signals + candles for a few ETFs and two Nifty-50 stocks."""
    spec = [("NIFTYBEES", "Nifty 50", "equity", 4e7), ("BIGNIFTY", "Nifty 50", "equity", 9e7), ("EQWT", "Nifty 50 Equal Weight", "equity", 9e8), ("JUNIORBEES", "Nifty Next 50", "equity", 3e7),
            ("MIDBEES", "Nifty Midcap 150", "equity", 2e7), ("GOLDBEES", "Gold", "gold", 5e7), ("GOLD2", "Gold", "gold", 2e7),
            ("LIQUIDCASE", "Nifty 1D Rate Index", "debt", 3e7), ("LIQUIDBEES", "Nifty 1D Rate Index", "debt", 9e7), ("MON100", "NASDAQ 100", "international", 9e7)]
    ids = {}
    for i, (sym, cat, ac, vol) in enumerate(spec):
        price0 = 1000.0 if sym == "LIQUIDBEES" else 100.0 + 10 * i
        s = await make_security(db, sym, [price0] * 300 if sym == "LIQUIDBEES" else walk(300, 900 + i, start=price0), kind="etf", sector=None, vol=int(vol / price0))
        s.category, s.asset_class, s.lot_size = cat, ac, 1
        ids[sym] = s
    await db.commit()
    await signals_run.run_signals(db, NOW)
    return ids


async def test_candidate_selection_picks_the_most_traded_of_the_right_underlying_and_skips_the_rest(db_session):
    from app.portfolio_intelligence.allocation.select import select_candidates

    await seed_market(db_session)
    c = await select_candidates(db_session, EXPECTED)
    assert c["core"]["large"]["symbol"] == "BIGNIFTY" and "the most traded" in c["core"]["large"]["why"] and "out of 2 ETF" in c["core"]["large"]["why"] and "expense ratio not known" in c["core"]["large"]["why"]         # EQWT ("Nifty 50 Equal Weight") is a different index and is ignored
    assert c["core"]["next50"]["symbol"] == "JUNIORBEES" and c["core"]["mid150"]["symbol"] == "MIDBEES"
    assert c["gold"][0]["symbol"] == "GOLDBEES"
    assert c["debt"][0]["symbol"] == "LIQUIDCASE" and "growth-NAV" in c["debt"][0]["why"] and c["debt"][0]["cash_like"] is True   # the fixed-NAV, dividend-unit kind is passed over
    assert "MON100" not in str(c)                                                                                          # international ETFs are never offered


async def test_a_thin_or_stale_etf_is_never_a_candidate(db_session):
    from app.portfolio_intelligence.allocation.select import select_candidates

    s = await make_security(db_session, "THINNIFTY", walk(300, 5), kind="etf", sector=None, vol=10)
    s.category, s.asset_class = "Nifty 50", "equity"
    stale = await make_security(db_session, "OLDNIFTY", walk(300, 6), kind="etf", sector=None, vol=50_000_000, last=EXPECTED - timedelta(days=3))
    stale.category, stale.asset_class = "Nifty 50", "equity"
    await db_session.commit()
    await signals_run.run_signals(db_session, NOW)
    c = await select_candidates(db_session, EXPECTED + timedelta(days=30))     # a month later: the stored prices are too old
    assert c["core"] == {}
    c2 = await select_candidates(db_session, EXPECTED)
    assert "large" in c2["core"] and c2["core"]["large"]["symbol"] == "OLDNIFTY"                                           # fresh enough and most traded; THINNIFTY fails the liquidity floor


async def test_empty_portfolio_unknown_profile_live_shape(client, db_session):
    await seed_market_with_user(db_session)
    r = await client.post("/api/v4/allocation/plan", json={"new_money": "50000"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "needs_input" and p["mix"]["source"] == "safe_only_no_tolerance" and {l["bucket"] for l in p["legs"]} == {"debt"}
    assert p["engine"]["status"] == "gates_pass" and p["engine"]["accounting"]["conserved"] and p["policy"]["status"] == "unreviewed placeholders"
    assert "not advice from a registered adviser" in p["disclaimer"] and p["created"] is True and p["prices_pinned"]
    again = (await client.post("/api/v4/allocation/plan", json={"new_money": "50000"})).json()
    assert again["plan_id"] == p["plan_id"] and again["created"] is False                                                  # same inputs: one record
    other = (await client.post("/api/v4/allocation/plan", json={"new_money": "60000"})).json()
    assert other["plan_id"] != p["plan_id"]
    assert (await db_session.execute(select(func.count()).select_from(AllocationPlan))).scalar_one() == 2


async def seed_market_with_user(db):
    from app.core.single_user import SINGLE_USER_ID
    from app.models.user import User

    db.add(User(id=SINGLE_USER_ID, email="user@local", full_name="U", hashed_password="x"))
    await db.commit()
    return await seed_market(db)


async def test_what_if_band_previews_the_risk_plan_but_the_engine_will_not_clear_it(client, db_session):
    await seed_market_with_user(db_session)
    p = (await client.post("/api/v4/allocation/plan", json={"new_money": "100000", "what_if_band": "moderate"})).json()
    assert p["mix"]["source"] == "what_if_band" and p["status"] == "needs_input"
    assert {"equity_india", "gold", "debt"} <= {l["bucket"] for l in p["legs"]}
    assert p["engine"]["status"] == "needs_input" and any(g["gate_id"] == "risk_capacity" for g in p["engine"]["final_gates"])
    assert "this is a what-if" in p["reasons"][0]


async def test_a_filled_profile_with_existing_holdings_gives_a_ready_plan_through_the_engine(client, db_session):
    from tests.test_decisions import ISIN_REL, ISIN_TCS, complete_setup

    await complete_setup(client, db_session)           # seeds the user, RELIANCE/TCS instruments, accounts, holdings, a complete profile and a goal claim
    await seed_market(db_session)
    p = (await client.post("/api/v4/allocation/plan", json={"new_money": "100000"})).json()
    assert p["mix"]["source"] == "profile_band" and p["mix"]["band"] == "moderate"
    assert p["classified_total"] != "0" and p["holdings_classification"]["rows"]
    cls = {r["label"]: r for r in p["holdings_classification"]["rows"]}
    assert {r["bucket"] for r in cls.values()} >= {"equity_india", "debt", "cash"}              # the two stocks, the FD, and the savings balance kept out of the allocation
    assert D(p["cash_not_counted"]) == D(30000) and D(p["classified_total"]) == D(70000)
    assert p["engine"]["accounting"]["conserved"] is True
    assert all(l["units"] > 0 for l in p["legs"]) and D(p["spent"]) + D(p["leftover_cash"]) == D(100000)
    assert not any(l["isin"] in (ISIN_REL, ISIN_TCS) for l in p["legs"])


async def test_validation_and_history(client, db_session):
    await seed_market_with_user(db_session)
    assert (await client.post("/api/v4/allocation/plan", json={"new_money": "-5"})).status_code == 422
    assert (await client.post("/api/v4/allocation/plan", json={"new_money": "1000000000"})).status_code == 422
    assert (await client.post("/api/v4/allocation/plan", json={"new_money": "100", "what_if_band": "reckless"})).status_code == 422
    made = (await client.post("/api/v4/allocation/plan", json={"new_money": "20000"})).json()
    lst = (await client.get("/api/v4/allocation/plans")).json()
    assert lst[0]["plan_id"] == made["plan_id"] and lst[0]["legs"] == len(made["legs"])
    assert (await client.get(f"/api/v4/allocation/plans/{made['plan_id']}")).json()["plan_id"] == made["plan_id"]
    assert (await client.get(f"/api/v4/allocation/plans/{uuid.uuid4()}")).status_code == 404
    assert (await client.get("/api/v4/allocation/policy")).json()["version"] == "allocation-p0-unreviewed"


async def test_sip_funds_are_ranked_by_expense_ratio_where_known_and_unknown_ones_follow_marked(client, db_session):
    from app.models.securities import SecurityTer

    await seed_market_with_user(db_session)
    funds = []
    for i, (name, amc) in enumerate([("UTI Nifty 50 Index Fund", "UTI"), ("HDFC Nifty 50 Index Fund", "HDFC"), ("Axis Nifty 50 Index Fund", "Axis"), ("360 ONE ELSS Tax Saver Nifty 50 Index Fund", "360 ONE")]):
        f = Security(source_key=f"amfi:{100 + i}", kind="mutual_fund", scheme_code=str(100 + i), name=name, amc=amc, plan="direct", option="growth", nav=D("150.5"),
                     nav_date=date(2026, 9, 30), asset_class="equity", source="amfi_navall", is_active=True, seen_at=NOW)
        db_session.add(f)
        funds.append(f)
    db_session.add(Security(source_key="amfi:200", kind="mutual_fund", scheme_code="200", name="UTI Nifty 50 Index Fund", plan="regular", option="growth", source="amfi_navall", is_active=True, seen_at=NOW))
    await db_session.commit()
    for f, t in ((funds[0], D("0.20")), (funds[1], D("0.10")), (funds[3], D("0.05"))):                         # Axis has no match; the ELSS one is cheap but must never appear
        db_session.add(SecurityTer(security_id=f.id, nsdl_code=f"N{f.scheme_code}", scheme_name=f.name, ter=t, plan_used="direct", matched_via="name_in_fund_house", ter_date=date(2026, 9, 30), matched_at=NOW))
    await db_session.commit()
    p = (await client.post("/api/v4/allocation/plan", json={"new_money": "20000"})).json()
    assert [(f["name"], f["ter_percent"]) for f in p["fund_alternatives"]] == [("HDFC Nifty 50 Index Fund", 0.1), ("UTI Nifty 50 Index Fund", 0.2), ("Axis Nifty 50 Index Fund", None)]
    assert "cheapest expense ratio first" in p["fund_note"] and "no defensible match" in p["fund_note"]


async def test_etf_choice_is_cost_aware_with_a_liquidity_guard_and_never_prefers_unknown_cost(db_session):
    from app.models.securities import SecurityTer
    from app.portfolio_intelligence.allocation.select import choose, select_candidates

    ids = await seed_market(db_session)
    # gold: GOLDBEES (5e7) is the leader; GOLD2 (2e7 = 40% of it) is cheaper and liquid enough
    for sec, t in ((ids["GOLDBEES"], D("0.81")), (ids["GOLD2"], D("0.45"))):
        db_session.add(SecurityTer(security_id=sec.id, nsdl_code=f"G{sec.symbol}", scheme_name=sec.symbol, ter=t, plan_used="etf", matched_via="t", ter_date=date(2026, 9, 30), matched_at=NOW))
    await db_session.commit()
    c = await select_candidates(db_session, EXPECTED)
    assert c["gold"][0]["symbol"] == "GOLD2" and c["gold"][0]["ter"] == 0.45                       # cheaper than the leader and trading 40% as much, so it clears the 20% guard
    assert "cheapest expense ratio among" in c["gold"][0]["why"] and "0.45% a year" in c["gold"][0]["why"]
    a = {"symbol": "LEAD", "turnover": 100.0, "ter": None}
    b = {"symbol": "CHEAP", "turnover": 30.0, "ter": 0.2}
    u = {"symbol": "UNKNOWN", "turnover": 90.0, "ter": None}
    assert choose([a, u, b])[0]["symbol"] == "CHEAP"                                                 # a known cost beats an unknown one
    assert choose([a, u])[0]["symbol"] == "LEAD" and "volume decides" in choose([a, u])[1]            # nothing known: the most traded
    thin = {"symbol": "THIN", "turnover": 10.0, "ter": 0.01}
    assert choose([a, b, thin])[0]["symbol"] == "CHEAP"                                              # 10% of the leader is below the 20% guard
    tie = {"symbol": "TIE", "turnover": 60.0, "ter": 0.2}
    assert choose([a, b, tie])[0]["symbol"] == "TIE"                                                 # equal cost: the more traded wins
    lead = {"symbol": "LEAD2", "turnover": 100.0, "ter": 0.1}
    assert choose([lead, b])[0]["symbol"] == "LEAD2" and "also the cheapest" in choose([lead, b])[1]


async def test_an_amount_below_the_minimum_gets_fund_options_and_an_honest_stock_note_not_an_empty_page(client, db_session):
    from app.models.securities import SecurityTer

    ids = await seed_market_with_user(db_session)
    rows = [("Navi Nifty 50 Index Fund", "Navi", "10"), ("BANDHAN LIQUID Fund", "Bandhan", "11"), ("Some Liquid ETF Fund", "X", "12")]
    funds = []
    for name, amc, code in rows:
        f = Security(source_key=f"amfi:{code}", kind="mutual_fund", scheme_code=code, name=name, amc=amc, plan="direct", option="growth", nav=D("100"),
                     nav_date=date(2026, 9, 30), source="amfi_navall", is_active=True, seen_at=NOW)
        db_session.add(f)
        funds.append(f)
    await db_session.commit()
    for f, t in ((funds[0], D("0.10")), (funds[1], D("0.07"))):
        db_session.add(SecurityTer(security_id=f.id, nsdl_code=f"N{f.scheme_code}", scheme_name=f.name, ter=t, plan_used="direct", matched_via="t", ter_date=date(2026, 9, 30), matched_at=NOW))
    await db_session.commit()

    p = (await client.post("/api/v4/allocation/plan", json={"new_money": "250"})).json()
    sa = p["small_amount"]
    assert p["legs"] == [] and sa is not None and sa["threshold"] == "1003"
    kinds = {o["kind"]: o for o in sa["options"]}
    assert kinds["liquid_fund"]["fund"]["name"] == "BANDHAN LIQUID Fund" and "0.07%" in kinds["liquid_fund"]["detail"] and "AMFI" in kinds["liquid_fund"]["detail"]      # the ETF-named row is not a fund option
    assert kinds["index_fund"]["adds_risk"] is True and "Answer the risk questions" in kinds["index_fund"]["detail"]          # no risk answers yet
    assert all(Decimal(u["price"]) * Decimal("1.003") <= Decimal(250) for u in sa["single_units"])                         # only units that fit the amount
    assert "does not buy individual stocks" in sa["stocks_note"] and "stock ranking" in sa["stocks_note"]
    # at or above the minimum there is no small-amount block, and the plan is unchanged in shape
    big = (await client.post("/api/v4/allocation/plan", json={"new_money": "20000"})).json()
    assert big["small_amount"] is None
    zero = (await client.post("/api/v4/allocation/plan", json={"new_money": "0"})).json()
    assert zero["small_amount"] is None
