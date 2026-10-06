"""Build the "what changed" view for held and watched securities. READ-ONLY: this module writes nothing (the worker persists via
persist.py). Inputs are the stored signal rows (their quality gate decides whether any change is claimed at all) and the same audited,
adjusted candles the signals use.

Wording rule, tested: observations describe past prices ("below its 200-day average", "52-week high") and never say buy, sell or
should. Options are things the owner can do with their own judgement; "keep it" is always first because doing nothing is the default."""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.single_user import SINGLE_USER_ID
from app.models.securities import CorporateAction, Security, SecurityCandle, SecuritySignal
from app.models.watchlist import BrokerInstrument, Watchlist, WatchlistItem
from app.portfolio_intelligence.allocation import policy as AP
from app.portfolio_intelligence.allocation.classify import classify_positions
from app.portfolio_intelligence.allocation.plan import build_plan
from app.portfolio_intelligence.market import adjust as adjust_mod
from app.portfolio_intelligence.signals import compute as sig
from app.portfolio_intelligence.suggestions import detect as D

MEASURED = {"measured_on": "2026-10-01", "stocks": 587, "sessions": "about 1,240 each (5 years, adjusted)",
            "trend_plain_crossings_per_year": {"median": 7.5, "p90": 11.9},
            "trend_rule_changes_per_year": {"median": 1.7, "p90": 2.7},
            "drawdown_20_entries_per_year": {"median": 1.3, "p90": 2.5}, "drawdown_30_entries_per_year": {"median": 0.8, "p90": 1.8},
            "volatility_spike_entries_per_year": {"median": 0.0, "p90": 0.3}}

NO_ADVICE = ("buy", "sell", "should", "recommend", "target price", "will rise", "will fall", "you must")


def declared() -> dict:
    return {"policy_version": D.POLICY_VERSION, "method_version": D.METHOD_VERSION, "status": "unreviewed placeholders",
            "trend": {"average_days": D.SMA_DAYS, "margin": D.TREND_MARGIN, "dwell_closes": D.TREND_DWELL, "recent_sessions": D.FRESH_SESSIONS},
            "drawdown": {"enter": D.DD_ENTER, "clear_above": D.DD_CLEAR}, "deep_drawdown": {"enter": D.DEEP_ENTER, "clear_above": D.DEEP_CLEAR},
            "volatility_ratio": {"enter": D.VOL_ENTER, "clear_below": D.VOL_CLEAR}, "measured_flip_rates": MEASURED,
            "note": "Margins were chosen from these measured rates so that the median stock produces fewer than about two changes a year."}


def _pct(x: float, digits: int = 0) -> str:
    return f"{abs(x) * 100:.{digits}f}%"


def options_for(context: str, instrument_id: str | None) -> list[dict]:
    held = context in ("held", "both")
    opts = [{"id": "keep", "text": "Keep things as they are. Doing nothing is the default, and these checks only describe the past."}]
    if held:
        opts += [{"id": "new_money_elsewhere", "text": "Hold off adding more to it, and put new money elsewhere first."},
                 {"id": "preview_reduction", "text": "Preview a reduction in the action lab to see what it would do to your concentration. "
                                                      "The tax on a sale cannot be estimated without your purchase records.", "href": "/simulate"}]
    elif instrument_id:
        opts.append({"id": "compare_adding", "text": "See how adding some would change your portfolio's concentration, in the comparison lab.", "href": f"/simulate?buy={instrument_id}"})
    return opts


def _obs(kind: str, context: str, *, title: str, detail: str, attention: str, since: date | None, sessions_since: int | None, measure: float | None,
         instrument_id: str | None, extra: dict | None = None) -> dict:
    return {"kind": kind, "severity": "information", "attention": attention, "title": title, "detail": detail,
            "since": since.isoformat() if since else None, "sessions_since": sessions_since, "measure": None if measure is None else round(float(measure), 4),
            "options": options_for(context, instrument_id), **(extra or {})}


def observations(symbol: str, context: str, a: dict, g: SecuritySignal, instrument_id: str | None) -> list[dict]:
    held = context in ("held", "both")
    out: list[dict] = []
    if a.get("status") != "ok":
        return out
    t, dd, deep, v = a["trend"], a["drawdown"], a["deep_drawdown"], a["volatility"]
    recent = t["changed"] and (t["sessions_since"] is not None and t["sessions_since"] <= D.FRESH_SESSIONS)
    if t["state"] is not None:
        side = "below" if t["state"] == "below" else "above"
        base = (f"By the plain rule (any crossing) its price crossed its {D.SMA_DAYS}-day average {t['raw_crossings_1y']} time(s) in the last year; by the rule used here "
                f"({D.TREND_MARGIN:.0%} margin, {D.TREND_DWELL} closes) it changed side {t['changes_1y']} time(s). "
                "That shows how often this check changes its mind. It describes the past; this app has not measured whether acting on it helps.")
        if recent:
            title = f"{symbol}: its price changed from {t['previous']} to {side} its {D.SMA_DAYS}-day average (confirmed {t['since']})"
        else:
            title = f"{symbol}: its price has been on the {'lower' if side == 'below' else 'upper'} side of its {D.SMA_DAYS}-day average since {t['since']}"
            base = (f"That was confirmed on {t['since']}, when it had been more than {D.TREND_MARGIN:.0%} {side} the average for {D.TREND_DWELL} closes in a row; "
                    f"it stays on this side until it moves the same distance the other way. ") + base
        out.append(_obs("trend_below" if side == "below" else "trend_above", context, title=title, detail=base,
                        attention="look" if (held and side == "below" and recent) else "context", since=t["since"], sessions_since=t["sessions_since"],
                        measure=abs(t["ratio_to_average"] or 0), instrument_id=instrument_id,
                        extra={"recent_change": bool(recent), "changes_1y": t["changes_1y"], "raw_crossings_1y": t["raw_crossings_1y"]}))
    if deep["on"]:
        out.append(_obs("deep_drawdown", context, title=f"{symbol}: more than {_pct(D.DEEP_ENTER)} below its 52-week high ({_pct(dd['value'])} now)",
                        detail=f"This started on {deep['since']}, and it has not yet come back within {abs(D.DEEP_CLEAR):.0%} of the high. It entered this zone {deep['entries_1y']} time(s) in the last year; the typical stock does so about once every year and a quarter.",
                        attention="look" if held else "context", since=deep["since"], sessions_since=deep["sessions_since"], measure=abs(dd["value"] or 0), instrument_id=instrument_id))
    elif dd["on"]:
        out.append(_obs("drawdown", context, title=f"{symbol}: more than {_pct(D.DD_ENTER)} below its 52-week high ({_pct(dd['value'])} now)",
                        detail=f"This started on {dd['since']}, and it has not yet come back within {abs(D.DD_CLEAR):.0%} of the high. A fall of this size from the high is common: the typical stock enters this zone about {MEASURED['drawdown_20_entries_per_year']['median']:.1f} times a year.",
                        attention="context", since=dd["since"], sessions_since=dd["sessions_since"], measure=abs(dd["value"] or 0), instrument_id=instrument_id))
    if v["on"]:
        out.append(_obs("volatility_elevated", context, title=f"{symbol}: its price has swung {v['value']:.1f} times more than usual over the last 60 days",
                        detail=f"Compared with its own last year, since {v['since']}. This is rare: the typical stock almost never reaches {D.VOL_ENTER:.1f} times.",
                        attention="context", since=v["since"], sessions_since=v["sessions_since"], measure=v["value"], instrument_id=instrument_id))
    liq = sig.liquidity_flag(None if g.liquidity_value is None else float(g.liquidity_value))
    if liq == "thin" or (g.circuit_days_20 or 0) >= 3:
        why = "it trades fewer rupees a day than the liquidity floor" if liq == "thin" else f"{g.circuit_days_20} of the last 20 sessions were locked at the price limit"
        out.append(_obs("thin_liquidity", context, title=f"{symbol}: hard to trade freely right now ({why})", detail="A small order can move the price, and a locked price may not let you trade at all.",
                        attention="context", since=g.as_of_date, sessions_since=0, measure=None, instrument_id=instrument_id))
    return out


async def _targets(db: AsyncSession):
    """-> (positions, held_by_security, watched_by_security, fund_labels, unresolved)"""
    from app.api.v4.risk import twin_positions
    from app.portfolio_intelligence.state.build import latest_state, latest_valuation

    state = await latest_state(db, SINGLE_USER_ID)
    valuation = await latest_valuation(db, state.id) if state else None
    positions = await twin_positions(db, state, valuation) if state and valuation else []
    isins = sorted({(p.get("isin") or "").upper() for p in positions if p.get("isin")})
    by_isin: dict[str, Security] = {}
    if isins:
        # An ETF is listed twice (NSE listing and AMFI's fund row for the same ISIN): the traded listing is the one that has prices.
        found = (await db.execute(select(Security).where(or_(Security.isin.in_(isins), Security.isin_reinvest.in_(isins))))).scalars().all()
        for sec in sorted(found, key=lambda x: x.kind not in ("stock", "etf")):
            for key in (sec.isin, sec.isin_reinvest):
                if key and key in isins:
                    by_isin.setdefault(key, sec)
    held: dict = defaultdict(list)
    funds, unresolved = [], 0
    for p in positions:
        if p["asset_type"] in ("cash", "deposit", "gold", "other") or p.get("value") is None:
            continue
        sec = by_isin.get((p.get("isin") or "").upper())
        if sec is None:
            unresolved += 1
        elif sec.kind in ("stock", "etf", "mutual_fund"):
            held[sec.id].append({"position_id": p["position_id"], "label": p.get("label"), "account": p["account_label"]})
    watched: dict = defaultdict(list)
    for sid, wl_name in (await db.execute(select(BrokerInstrument.security_id, Watchlist.name).join(WatchlistItem, WatchlistItem.broker_instrument_id == BrokerInstrument.id)
                                          .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id).where(Watchlist.user_id == SINGLE_USER_ID, BrokerInstrument.security_id.is_not(None)))).all():
        watched[sid].append(wl_name)
    return positions, held, watched, funds, unresolved


async def _series_for(db: AsyncSession, sid, symbol: str, as_of: date):
    rows = [{"trade_date": r.trade_date, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume}
            for r in (await db.execute(select(SecurityCandle).where(SecurityCandle.security_id == sid, SecurityCandle.trade_date <= as_of).order_by(SecurityCandle.trade_date))).scalars()]
    events = [{"ex_date": a.ex_date, "kind": a.kind, "price_factor": a.price_factor, "needs_review": a.needs_review}
              for a in (await db.execute(select(CorporateAction).where(CorporateAction.symbol == symbol))).scalars()] if symbol else []
    adj = adjust_mod.adjust_series(rows, events) if events else {"rows": rows, "unreliable": []}
    return [r["trade_date"] for r in adj["rows"]], [float(r["close"]) for r in adj["rows"]]


async def portfolio_items(db: AsyncSession, positions: list[dict]) -> list[dict]:
    from app.api.v4.constraints import risk_constraints
    from app.api.v4.personal import profile_view
    from app.portfolio_intelligence.allocation.service import _by_isin, _short_horizon_claimed
    from app.portfolio_intelligence.state.build import active_liabilities, latest_profile

    if not positions:
        return [{"kind": "no_holdings", "title": "No holdings are recorded yet", "detail": "Add an account and import or connect your holdings to see how your mix compares with a target.",
                 "href": "/holdings", "severity": "information"}]
    pv = profile_view(await latest_profile(db, SINGLE_USER_ID), await active_liabilities(db, SINGLE_USER_ID))
    if pv["tolerance"]["status"] != "ready":
        return [{"kind": "needs_risk_answers", "title": "Answer the three risk questions to see how your mix compares with a target",
                 "detail": "A target mix depends on your own tolerance for a fall; until it is known nothing can be said about drift.", "href": "/finances", "severity": "information"}]
    constraints = await risk_constraints(db)
    holdings = classify_positions(positions, await _by_isin(db, positions))
    plan = build_plan(tolerance=pv["tolerance"], constraints=constraints, what_if_band=None, new_money=Decimal(0), holdings=holdings,
                      short_horizon_claimed=_short_horizon_claimed(constraints), candidates={"core": {}, "satellite": [], "gold": [], "debt": []})
    out = []
    for d in plan["drift"]:
        if d["outside_band"]:
            tw, cw = Decimal(d["target_weight"]), Decimal(d["current_weight"])
            out.append({"kind": "mix_drift", "bucket": d["bucket"], "severity": "information",
                        "title": f"{d['label']} is {cw * 100:.0f}% of what you hold; the target for your answers is {tw * 100:.0f}% ({d['direction']})",
                        "detail": "A bucket within 5 points of its target needs no move. No sale is suggested, because the tax on a sale cannot be estimated.",
                        "options": [{"id": "keep", "text": "Keep things as they are."},
                                    {"id": "new_money_to_gaps", "text": "Point your next new money at the buckets that are below target. The Invest page builds that plan.", "href": "/allocate"}]})
    if not out:
        out.append({"kind": "mix_within_band", "title": "Your mix is within 5 points of its target in every bucket", "detail": f"Based on the {plan['mix']['band']} band from your answers.", "severity": "information"})
    if plan["unknown_share"] and Decimal(plan["unknown_share"]) > AP.UNKNOWN_SHARE_LIMIT:
        out.append({"kind": "unclassified_share", "title": f"{Decimal(plan['unknown_share']) * 100:.0f}% of what you hold could not be placed in a bucket", "detail": "Drift cannot be trusted until those holdings are identified.", "severity": "information"})
    return out


async def build_suggestions(db: AsyncSession, now: datetime) -> dict:
    positions, held, watched, funds, unresolved = await _targets(db)
    ids = list(set(held) | set(watched))
    latest = (select(SecuritySignal.security_id.label("sid"), func.max(SecuritySignal.as_of_date).label("d")).where(SecuritySignal.method_version == sig.METHOD_VERSION)
              .group_by(SecuritySignal.security_id).subquery())
    sigs = {}
    if ids:
        for sec, g in (await db.execute(select(Security, SecuritySignal).join(latest, latest.c.sid == Security.id)
                                        .join(SecuritySignal, (SecuritySignal.security_id == Security.id) & (SecuritySignal.as_of_date == latest.c.d) & (SecuritySignal.method_version == sig.METHOD_VERSION))
                                        .where(Security.id.in_(ids)))).all():
            sigs[sec.id] = (sec, g)
    secs = {s.id: s for s in (await db.execute(select(Security).where(Security.id.in_(ids)))).scalars()} if ids else {}
    items = {"held": [], "watched": []}
    for sid in ids:
        sec = secs[sid]
        context = "both" if sid in held and sid in watched else "held" if sid in held else "watched"
        base = {"security_id": str(sid), "symbol": sec.symbol, "name": sec.name, "isin": sec.isin, "kind": sec.kind, "context": context,
                "instrument_id": str(sec.instrument_id) if sec.instrument_id else None, "position_ids": [p["position_id"] for p in held.get(sid, [])],
                "watchlists": watched.get(sid, []), "observations": []}
        if sid not in sigs:
            base.update(quality="no_signals", signal_as_of=None, note=("no price history is stored for this fund yet (NAV history is fetched for the funds on the SIP list and the ones you hold)" if sec.kind == "mutual_fund"
                                                                        else "no stored signals yet for this security (they are computed nightly for securities with price history)"))
        else:
            _, g = sigs[sid]
            base.update(quality=g.quality, signal_as_of=g.as_of_date.isoformat(), signal_input_marker=g.input_marker)
            if g.quality != "ok":
                reasons = (g.detail or {}).get("reasons") or []
                unrel = (g.detail or {}).get("unreliable") or []
                base["note"] = ("price history is not reliable enough to say what changed: " + "; ".join(reasons + [u["reason"] for u in unrel])) if (reasons or unrel) else "price history is not reliable enough to say what changed"
            else:
                dates, closes = await _series_for(db, sid, sec.symbol, g.as_of_date)
                a = D.analyze(dates, closes)
                base["observations"] = observations(sec.symbol or sec.name, context, a, g, base["instrument_id"])
        for ctx in (["held"] if sid in held else []) + (["watched"] if sid in watched else []):
            items[ctx].append(base)
    for k in items:
        items[k].sort(key=lambda i: (0 if any(o["attention"] == "look" for o in i["observations"]) else 1, i["symbol"] or ""))
    funds = [i["name"] for i in items["held"] if i["kind"] == "mutual_fund" and i["quality"] == "no_signals"]
    as_of = max((g.as_of_date for _, g in sigs.values()), default=None)
    return {"generated_at": now.isoformat(), "as_of": as_of.isoformat() if as_of else None, "policy": declared(), "held": items["held"], "watched": items["watched"],
            "portfolio": await portfolio_items(db, positions), "funds_without_price_signals": funds, "unresolved_holdings": unresolved,
            "note": "These describe past prices. They are not forecasts, and no sale is ever suggested here."}
