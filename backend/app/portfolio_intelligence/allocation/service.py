"""Gather real inputs, build the plan, evaluate it through the SAME gates the action lab uses, store it immutably."""

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.api.v4.constraints import risk_constraints
from app.api.v4.personal import profile_view
from app.api.v4.risk import claims_by_position, twin_positions
from app.core.single_user import SINGLE_USER_ID
from app.models.securities import AllocationPlan, Security
from app.portfolio_intelligence.allocation import policy as P
from app.portfolio_intelligence.allocation.classify import classify_positions
from app.portfolio_intelligence.allocation.plan import build_plan
from app.portfolio_intelligence.allocation.select import fund_alternatives, liquid_fund_alternatives, select_candidates
from app.portfolio_intelligence.scoring import checklist as CK
from app.portfolio_intelligence.allocation.overlap import exposure as holdings_exposure
from app.portfolio_intelligence.scoring.service import current_ranking, current_scores
from app.portfolio_intelligence.decisions import engine
from app.portfolio_intelligence.sources.angel.token_store import IST
from app.portfolio_intelligence.state.build import active_liabilities, active_preferences, latest_profile, latest_state, latest_valuation
from app.utils.time import utcnow

DEFAULT_ACCOUNT_LABEL = "New purchases (your demat account)"


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


async def _holdings_inputs(db: AsyncSession):
    state = await latest_state(db, SINGLE_USER_ID)
    valuation = await latest_valuation(db, state.id) if state else None
    if state is None or valuation is None:
        return None, None, [], {}
    positions = await twin_positions(db, state, valuation)
    labels = {a["label"] for a in state.account_inputs}
    return state, valuation, positions, labels


async def _by_isin(db: AsyncSession, positions: list[dict]) -> dict:
    isins = sorted({(p.get("isin") or "").upper() for p in positions if p.get("isin")})
    if not isins:
        return {}
    out = {}
    for sec in (await db.execute(select(Security).where(or_(Security.isin.in_(isins), Security.isin_reinvest.in_(isins))))).scalars():
        for key in (sec.isin, sec.isin_reinvest):
            if key and key in isins and key not in out:
                out[key] = {"asset_class": sec.asset_class, "kind": sec.kind, "symbol": sec.symbol}
    return out


def _fmt_inr(x: Decimal) -> str:
    return f"₹{x.quantize(Decimal('1')):,}"


def _ter_text(f: dict) -> str:
    return f"Expense ratio {f['ter_percent']:.2f}% a year (AMFI {f['ter_as_of']})" if f["ter_percent"] is not None else "Expense ratio unknown (no defensible match to AMFI's file)"


def small_amount_block(new_money: Decimal, candidates: dict, equity_funds: list[dict], liquid_funds: list[dict], risk_ok: bool) -> dict | None:
    """What to say when the amount is below the smallest purchase the planner will propose. Never a ranking of stocks."""
    if not (Decimal(0) < new_money < P.SMALL_AMOUNT_FLOOR):
        return None
    seen, units = set(), []
    pool = list(candidates["core"].values()) + list(candidates["gold"]) + list(candidates["debt"])
    for i in sorted(pool, key=lambda x: x["price"]):
        if i["id"] in seen or i["price"] * (1 + P.FEE_PCT) > new_money:
            continue
        seen.add(i["id"])
        units.append({"symbol": i["symbol"], "name": i["name"], "kind": i["kind"], "price": format(i["price"].normalize(), "f"), "price_as_of": i["price_as_of"].isoformat(), "why": i.get("why")})
    options = []
    if liquid_funds:
        f = liquid_funds[0]
        options.append({"kind": "liquid_fund", "title": "Keep it safe: a liquid fund", "adds_risk": False, "fund": f,
                        "detail": f"{f['name']} (direct, growth) invests in very short-term debt and can be bought for any rupee amount in the Angel One app. {_ter_text(f)}. Its value moves very little, and it is not guaranteed."})
    if equity_funds:
        f = equity_funds[0]
        options.append({"kind": "index_fund", "title": "Grow it slowly: a Nifty 50 index fund", "adds_risk": True, "fund": f,
                        "detail": f"{f['name']} (direct, growth) follows the 50 largest companies, can be bought by rupee amount, and an SIP can start from about ₹100 in the Angel One app (minimums differ by fund; check its page). {_ter_text(f)}. Its value can fall as well as rise."
                                  + ("" if risk_ok else " Answer the risk questions in Financial profile first: until then this app treats added risk as not cleared for you.")})
    return {
        "threshold": format(P.SMALL_AMOUNT_FLOOR.quantize(Decimal("1")), "f"),
        "message": f"{_fmt_inr(new_money)} is below the smallest purchase this planner suggests ({_fmt_inr(P.SMALL_AMOUNT_FLOOR)}). Brokerage and fixed charges would eat too much of a very small order, and it cannot be spread over several holdings. What does work at any size is a fund bought by rupee amount.",
        "options": options,
        "single_units": units,
        "single_units_note": ("You could also buy whole units of an exchange-traded fund within this amount (below), but one unit is one product, charges weigh more on small orders, and a fixed fee on selling later can be large relative to it."
                              if units else "No exchange-traded fund the planner would suggest costs this little per unit."),
        "stocks_note": "At this size a plan does not buy individual stocks: it cannot spread the money over several companies. With enough money it picks three to five liquid Nifty 50 stocks, at most two per sector, the best-ranked on value, quality and momentum (a screen, not a forecast; see the stock ranking on this page). You can look up any stock yourself in Market and sort by price.",
        "version": P.SMALL_AMOUNT_VERSION,
    }


def stock_screen(scores: dict, candidates: dict, legs: list[dict], *, in_plan: bool = True) -> dict:
    """Every scored Nifty 50 stock with its score, key measures and one plain status: picked / eligible but not picked (with the reason) / low score
    (with the reasons) / not scored. Low scorers are information about the stock; nothing here ever suggests selling one the owner holds."""
    picked = {l["symbol"] for l in legs if l["role"] == "satellite"}
    liquid = candidates.get("liquid_stocks", set())
    winners = {st["sector"]: st["symbol"] for st in candidates["satellite"]}
    out = []
    for sym, r in scores["rows"].items():
        c = r["components"]
        status, note = r["status"], None
        if sym in picked:
            status, note = "picked", "in this plan"
        elif not in_plan and winners.get(r["sector"]) == sym:
            status, note = "top_in_sector", "the highest-scoring liquid stock in its sector; a plan with enough money picks from these"
        elif r["status"] == "eligible":
            if sym not in liquid:
                status, note = "not_picked", "does not trade enough rupees a day to pass the liquidity check"
            elif winners.get(r["sector"]) not in (None, sym):
                status, note = "not_picked", f"{winners[r['sector']]} scores higher in {r['sector']} and the plan holds one stock per sector"
            else:
                status, note = "not_picked", "not needed at this amount: the plan holds only as many stocks as the money sensibly spreads over"
        elif r["status"] == "below_floor":
            status, note = "low_score", f"scores {r['score']:.0f}, below the {CK.FLOOR:.0f} floor, so it is not picked for new money"
        else:
            status, note = "not_scored", "too little data to score (" + ", ".join(r["missing"]) + " not known)" if r["missing"] else "too little data to score"
        inp = {k: v for comp in c.values() for k, v in comp["inputs"].items()}
        out.append({"symbol": sym, "name": r["name"], "sector": r["sector"], "financial": r["financial"], "score": r["score"], "coverage": r["coverage"], "status": status, "note": note,
                    "reasons": r["reasons"], "flags": r["flags"], "missing": r["missing"], "pe": r["pe"], "pb": inp.get("pb"), "roe": inp.get("roe"), "debt_to_equity": inp.get("debt_to_equity"),
                    "volatility_1y": inp.get("vol_252"), "components": {k: v["score"] for k, v in c.items()}, "price": r["price"], "trend": r["shown_only"].get("trend"),
                    "momentum_rank": r["shown_only"].get("momentum_rank"), "security_id": r["security_id"]})
    order = {"picked": 0, "top_in_sector": 0, "not_picked": 1, "low_score": 2, "not_scored": 3}
    out.sort(key=lambda x: (order[x["status"]], -(x["score"] if x["score"] is not None else -1), x["symbol"]))
    return {"version": scores["version"], "floor": CK.FLOOR, "weights": CK.WEIGHTS, "fundamentals_as_of": scores["fundamentals_as_of"], "rows": out,
            "note": ("A screen on fundamentals (P/E, P/B, EV/EBITDA, returns, margins, growth, debt) and on how rough the price has been. It is not a forecast and it has not yet been tested "
                     "against what prices did afterwards (each score is saved with its date so that test can be run). Trend, momentum and the price-forecast model are shown but add no points, "
                     "because the tests found no return effect in them.")}


async def risk_beside_rank(db: AsyncSession, picks: list[str], held_symbols: list[str]) -> dict | None:
    """Shrunk-covariance description of the proposed stocks next to the stocks already held (informational; it never changes a pick)."""
    import pandas as pd

    from app.portfolio_intelligence.risk import shrinkage as SH
    from app.portfolio_intelligence.scoring.momentum import tr_series_for

    if len(picks) < 2:
        return None
    syms = list(dict.fromkeys([*picks, *held_symbols]))
    secs = (await db.execute(select(Security).where(Security.symbol.in_(syms), Security.kind == "stock", Security.is_active.is_(True), Security.series == "EQ"))).scalars().all()
    series = {}
    tr = await tr_series_for(db, list(secs))
    by_id = {s_.id: s_.symbol for s_ in secs}
    for sid, x in tr.items():
        series[by_id[sid]] = pd.Series(x["tr"], index=pd.to_datetime(x["dates"]))
    try:
        return SH.analyse(series, picks, [h for h in held_symbols if h not in picks])
    except Exception as exc:  # noqa: BLE001 -- a description must never break a plan
        return {"status": "unavailable", "reason": type(exc).__name__}


def _money(x) -> str:
    return f"₹{Decimal(str(x)).quantize(Decimal('1')):,}"


def stock_ranking_block(ranking: dict, candidates: dict, plan: dict, held: dict, new_money: Decimal, *, in_plan: bool = True) -> dict:
    """Every Nifty 50 stock with its rank, the three components, strengths and weaknesses, coverage, source dates, risk beside the rank, how it fits what is
    already held, and for picked stocks the estimated cost. Passing the safety checks says nothing about whether a stock will be profitable."""
    legs = {l["symbol"]: l for l in plan["legs"] if l["role"] == "satellite"}
    cand = {c["symbol"] for c in candidates["satellite"]}
    liquid = candidates.get("liquid_stocks", set())
    cap = float(P.SATELLITE_MAX_WEIGHT_OF_PORTFOLIO)
    rows = []
    for sym, r in ranking["rows"].items():
        h = held.get(sym)
        role, note = None, None
        if sym in legs:
            role, note = "picked", "in this plan"
        elif r["status"] == "not_ranked":
            role, note = "not_ranked", "not ranked: " + "; ".join(r["reasons_not_ranked"])
        elif r["status"] == "below_floor":
            role, note = "below_floor", f"composite {r['composite']:.0f} is below the {ranking['floor']:.0f} floor, so it is not a candidate for new money"
        elif sym not in liquid:
            role, note = "excluded", "does not trade enough rupees a day to pass the liquidity check"
        elif h is not None and h["total"] >= cap:
            role, note = "excluded", f"you already hold about {h['total']:.1%} of the portfolio in it, at or above the {cap:.0%} single-stock cap"
        elif not in_plan:
            role, note = "candidate", "a candidate for new money; a plan picks from these, 3 to 5 at a time, at most two per sector"
        elif sym not in cand:
            role, note = "not_picked", f"already {P.SATELLITE_MAX_PER_SECTOR} better-ranked {r['sector']} stocks are candidates, and this plan holds at most {P.SATELLITE_MAX_PER_SECTOR} per sector"
        else:
            role, note = "not_picked", "a candidate, but the plan holds only as many stocks as the money sensibly spreads over (3 to 5, at least ₹5,000 each)"
        leg = legs.get(sym)
        cost = None
        if leg is not None:
            trade = Decimal(leg["price"]) * leg["units"]
            cost = {"units": leg["units"], "price": leg["price"], "price_as_of": leg["price_as_of"], "trade_value": format(trade.normalize(), "f"), "planned_debit": leg["planned_debit"],
                    "assumed_charges": format((Decimal(leg["planned_debit"]) - trade).quantize(Decimal("0.01")), "f"), "note": f"charges are an assumed {P.FEE_PCT:.1%}, not a quote; whole units only"}
        fit = None
        if h is not None:
            fit = {"direct": round(h["direct"], 4), "lookthrough": round(h["lookthrough"], 4), "total": round(h["total"], 4),
                   "note": (f"you hold about {h['direct']:.1%} directly" if h["direct"] > 0 else "") + (" and " if h["direct"] > 0 and h["lookthrough"] > 0 else "") +
                           (f"about {h['lookthrough']:.1%} through your Nifty 50 index fund or ETF (approximate: cap-weighted, free float ignored)" if h["lookthrough"] > 0 else "")}
        rows.append({"symbol": sym, "name": r["name"], "sector": r["sector"], "financial": r["financial"], "rank": r["rank"], "rank_of": r["rank_of"], "composite": r["composite"], "status": role, "note": note,
                     "components": {k: {"score": c["score"], "coverage": c["coverage"], "measures_used": c["n_measures"], "measures_possible": c["n_active"], "missing": c["missing"], "inactive": c["inactive"],
                                        "measures": {m: {"value": g["raw"], "percentile": g["percentile"], "peers": g["peer_n"]} for m, g in c["measures"].items()}} for k, c in r["components"].items()},
                     "coverage": r["coverage"], "strengths": r["strengths"], "weaknesses": r["weaknesses"], "flags": r["flags"], "risk": r["risk"], "dates": r["dates"],
                     "momentum_basis": r["momentum_basis"], "fit": fit, "cost": cost, "price": r["price"], "security_id": r["security_id"]})
    order = {"picked": 0, "candidate": 0, "not_picked": 1, "excluded": 2, "below_floor": 3, "not_ranked": 4}
    rows.sort(key=lambda x: (order[x["status"]], x["rank"] if x["rank"] is not None else 10**6, x["symbol"]))
    picked = [r for r in rows if r["status"] == "picked"]
    n_cand = len(cand)
    inactive = sorted({m for r in ranking["rows"].values() for c in r["components"].values() for m in c["inactive"]})
    return {"version": ranking["version"], "weights": ranking["weights"], "floor": ranking["floor"], "policy_note": ranking["policy_note"], "fundamentals_as_of": ranking["fundamentals_as_of"], "momentum_caution": ranking.get("momentum_caution"), "rows": rows,
            "candidates": n_cand, "inactive_measures": inactive,
            "inactive_note": ("Not used because the inputs are not stored for these companies (total assets, capex, cash, EBIT, and cash flow for most): " + ", ".join(inactive) + ". They switch on by themselves if the data appears.") if inactive else None,
            "selection_rule": (f"Candidates are stocks ranked on all three components with a composite of at least {ranking['floor']:.0f}, liquid, and not already at the {cap:.0%} cap through what you hold; at most "
                               f"{P.SATELLITE_MAX_PER_SECTOR} per sector and none forced from a sector without a candidate. Fewer than {P.SATELLITE_MIN_STOCKS} candidates, or too little money, means no direct stock and the money goes to the index ETFs."),
            "no_stock_reason": None if (picked or not in_plan) else ("fewer than three stocks are candidates" if n_cand < P.SATELLITE_MIN_STOCKS else "the amount is too small to spread over three or more stocks of at least ₹5,000"),
            "safety_note": "Passing the safety checks means a purchase fits your limits and the data is usable. It does not mean the stock is expected to make money: the ranking is an unvalidated screen that has not been tested against later prices."}


def _short_horizon_claimed(constraints: dict) -> Decimal:
    for c in constraints["ceilings"]:
        if c["source"] == "goal_horizon":
            return sum((Decimal(g["claimed"]) for g in c.get("short_horizon_goals", [])), Decimal(0))
    return Decimal(0)


async def generate_plan(db: AsyncSession, *, new_money: Decimal, what_if_band: str | None = None, now: datetime | None = None) -> tuple[AllocationPlan, bool]:
    now = now or utcnow()
    today = now.astimezone(IST).date()
    if not new_money.is_finite() or new_money < 0:
        raise ValueError("new_money must be zero or a positive amount")
    state, valuation, positions, labels = await _holdings_inputs(db)
    pv = profile_view(await latest_profile(db, SINGLE_USER_ID), await active_liabilities(db, SINGLE_USER_ID))
    constraints = await risk_constraints(db)
    restrictions = [{"kind": p.kind, "value": p.value} for p in await active_preferences(db, SINGLE_USER_ID)]
    claims = await claims_by_position(db) if state is not None else {}
    holdings = classify_positions(positions, await _by_isin(db, positions))
    ranking = await current_ranking(db, now=now)
    classified_total = sum(holdings["buckets"].values(), Decimal(0))
    held = await holdings_exposure(db, positions, ranking["rows"], classified_total + new_money)
    candidates = await select_candidates(db, today, ranking=ranking, exposure=held)
    funds = await fund_alternatives(db)
    liquid_funds = await liquid_fund_alternatives(db) if Decimal(0) < new_money < P.SMALL_AMOUNT_FLOOR else []

    plan = build_plan(tolerance=pv["tolerance"], constraints=constraints, what_if_band=what_if_band, new_money=new_money, holdings=holdings,
                      short_horizon_claimed=_short_horizon_claimed(constraints), candidates=candidates)

    account = next(iter(sorted(labels)), DEFAULT_ACCOUNT_LABEL) if labels else DEFAULT_ACCOUNT_LABEL
    insts, prices, actions = {}, {}, []
    for leg in plan["legs"]:
        key = leg["engine_key"]
        asset_type = "listed_equity" if leg["kind"] == "stock" else "etf"
        sector = leg["sector"]
        insts[key] = {"symbol": leg["symbol"], "sector": sector, "isin": leg["isin"], "lot_size": 1, "asset_type": asset_type, "cash_like": leg["cash_like"]}
        prices[key] = {"price": Decimal(leg["price"]), "as_of": datetime.fromisoformat(leg["price_as_of"]).date()}
        actions.append({"type": "BUY", "instrument_id": key, "amount": Decimal(leg["budget_for_engine"]), "funding": "new_money", "account_label": account})
    # real lot sizes
    for sec in (await db.execute(select(Security).where(Security.id.in_([uuid.UUID(l["instrument_id"]) for l in plan["legs"]])))).scalars() if plan["legs"] else []:
        for leg in plan["legs"]:
            if leg["instrument_id"] == str(sec.id):
                insts[leg["engine_key"]]["lot_size"] = sec.lot_size or 1
    ctx = {"baseline": positions, "claims": claims, "capacity": pv["capacity"], "constraints": constraints, "restrictions": restrictions, "instruments": insts, "prices": prices,
           "commitments": {}, "goals": {}, "budget": {}, "contribution": new_money, "withdrawal": Decimal(0), "actions": actions, "priorities": [], "fee_pct": P.FEE_PCT, "today": today}
    evaluation = engine.evaluate_plan(ctx) if actions else None
    result = {**plan, "engine": evaluation, "fund_alternatives": funds, "fund_note": "Direct-plan growth index funds on the Nifty 50, for a SIP, cheapest expense ratio first where AMFI's file could be matched to the fund; a fund marked unknown has no defensible match, so check its cost in the Angel One app before choosing.",
              "holdings_classification": {"rows": [{**r, "value": None if r["value"] is None else format(r["value"].normalize(), "f")} for r in holdings["rows"]], "unvalued": holdings["unvalued"]},
              "generated_at": now.isoformat(), "disclaimer": "A proposal for your own money, computed by fixed rules from public data. It is not advice from a registered adviser; you place any order yourself in Angel One."}
    result["stock_ranking"] = stock_ranking_block(ranking, candidates, plan, held, new_money)
    result["stock_ranking"]["risk_beside_rank"] = await risk_beside_rank(db, [l["symbol"] for l in plan["legs"] if l["role"] == "satellite"], [k for k, v in held.items() if v["direct"] > 0])
    result["small_amount"] = small_amount_block(new_money, candidates, funds, liquid_funds, bool(pv["tolerance"]["status"] == "ready" and constraints["risk_increasing_allowed"]))
    if evaluation is not None and plan["status"] == "ready" and evaluation["status"] != "gates_pass":
        result["status"] = "needs_input" if evaluation["status"] == "needs_input" else "blocked"
        result["reasons"] = plan["reasons"] + evaluation["reasons"]
    price_pins = {k: [str(v["price"]), v["as_of"].isoformat()] for k, v in sorted(prices.items())}
    params = {"new_money": str(new_money), "what_if_band": what_if_band}
    inputs = {"params": params, "prices": price_pins, "tolerance": pv["tolerance"], "constraints": {"allowed": constraints["risk_increasing_allowed"], "limiting": constraints["limiting_factors"]},
              "restrictions": restrictions, "positions": engine.candidate_hash(positions), "policy": P.POLICY_VERSION, "engine": engine.ENGINE_VERSION,
              "candidates": sorted(l["instrument_id"] for l in plan["legs"]), "ranking": ranking["version"], "ranking_weights": ranking["weights"], "ranking_floor": ranking["floor"],
              "ranks": sorted((k, v["composite"]) for k, v in ranking["rows"].items()), "held": sorted((k, round(v["total"], 4)) for k, v in held.items()), "funds": [(f["scheme_code"], f["ter_percent"]) for f in funds], "small_amount_v": P.SMALL_AMOUNT_VERSION,
              "liquid_funds": [(f["scheme_code"], f["ter_percent"]) for f in liquid_funds]}
    h = _hash(inputs)
    q = select(AllocationPlan).where(AllocationPlan.user_id == SINGLE_USER_ID, AllocationPlan.inputs_hash == h)
    existing = (await db.execute(q)).scalar_one_or_none()
    if existing is not None:
        return existing, False
    row = AllocationPlan(user_id=SINGLE_USER_ID, inputs_hash=h, policy_version=P.POLICY_VERSION, engine_version=engine.ENGINE_VERSION, state_id=state.id if state else None,
                         valuation_id=valuation.id if valuation else None, new_money=new_money, what_if_band=what_if_band, status=result["status"], origin="what_if" if what_if_band else "owner", params=params, prices=price_pins,
                         result=result, created_at=now)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return (await db.execute(q)).scalar_one(), False
    return row, True
