"""Gather the Nifty 50 inputs, score them, and store each score point-in-time (insert-only)."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fundamentals import FundamentalMetrics
from app.models.securities import Security, SecurityCandle, SecurityScore, SecuritySignal
from app.portfolio_intelligence.scoring import checklist as C
from app.portfolio_intelligence.scoring.checklist import StockInput
from app.utils.time import utcnow


async def load_inputs(db: AsyncSession) -> list[tuple[Security, StockInput]]:
    """Nifty 50 stocks (securities linked to the instrument table), with the latest fundamentals, the latest stored price and signals."""
    secs = (await db.execute(select(Security).where(Security.kind == "stock", Security.is_active.is_(True), Security.instrument_id.is_not(None)))).scalars().all()
    funds = await _latest_fundamentals(db)
    latest_s = (select(SecuritySignal.security_id.label("sid"), func.max(SecuritySignal.as_of_date).label("d")).group_by(SecuritySignal.security_id).subquery())
    sigs = {g.security_id: g for g in (await db.execute(select(SecuritySignal).join(latest_s, (latest_s.c.sid == SecuritySignal.security_id) & (latest_s.c.d == SecuritySignal.as_of_date)))).scalars()}
    out = []
    for s in secs:
        f, g = funds.get(s.instrument_id), sigs.get(s.id)
        last = (await db.execute(select(SecurityCandle.trade_date, SecurityCandle.close).where(SecurityCandle.security_id == s.id).order_by(SecurityCandle.trade_date.desc()).limit(1))).first()
        price = float(last[1]) if last else None
        ok = g is not None and g.quality == "ok"
        out.append((s, StockInput(
            symbol=s.symbol, name=s.name, sector=s.sector, price=price,
            eps=getattr(f, "eps", None), pe_stored=getattr(f, "pe", None), pb=getattr(f, "pb", None), ev_ebitda=getattr(f, "ev_ebitda", None), roe=getattr(f, "roe", None),
            net_margin=getattr(f, "net_margin", None), eps_growth=getattr(f, "eps_growth", None), revenue_growth=getattr(f, "revenue_growth", None),
            free_cash_flow=getattr(f, "free_cash_flow", None), debt_to_equity=getattr(f, "debt_to_equity", None),
            vol_252=float(g.vol_252) if ok and g.vol_252 is not None else None, max_dd_1y=float(g.max_dd_1y) if ok and g.max_dd_1y is not None else None,
            fundamentals_as_of=f.as_of_date.isoformat() if f is not None else None,
            shown_only={"trend": g.trend_state if g is not None else None, "momentum_rank": float(g.mom_12_1_rank) if g is not None and g.mom_12_1_rank is not None else None,
                        "price_as_of": last[0].isoformat() if last else None})))
    return out


async def current_scores(db: AsyncSession, *, persist: bool = True, now: datetime | None = None) -> dict:
    """{symbol: score row} for the whole scored universe, plus the universe facts. Persisting is insert-only: a score already stored for its
    (security, price date, method version) is left exactly as it was."""
    now = now or utcnow()
    pairs = await load_inputs(db)
    rows = C.score_universe([p[1] for p in pairs])
    by_symbol = {r["symbol"]: r for r in rows}
    if persist:
        for sec, inp in pairs:
            r = by_symbol[inp.symbol]
            asof = inp.shown_only.get("price_as_of")
            if asof is None:
                continue
            from datetime import date as _date

            d = _date.fromisoformat(asof)
            exists = (await db.execute(select(SecurityScore.security_id).where(SecurityScore.security_id == sec.id, SecurityScore.as_of_date == d,
                                                                                SecurityScore.method_version == C.CHECKLIST_VERSION))).first()
            if exists is None:
                db.add(SecurityScore(security_id=sec.id, as_of_date=d, method_version=C.CHECKLIST_VERSION, computed_at=now, score=r["score"], coverage=r["coverage"], status=r["status"],
                                     fundamentals_as_of=_date.fromisoformat(r["fundamentals_as_of"]) if r["fundamentals_as_of"] else None, detail={k: v for k, v in r.items() if k not in ("symbol", "name")}))
        await db.commit()
    ids = {inp.symbol: str(sec.id) for sec, inp in pairs}
    for sym, r in by_symbol.items():
        r["security_id"] = ids[sym]
    fdates = sorted({r["fundamentals_as_of"] for r in rows if r["fundamentals_as_of"]})
    return {"version": C.CHECKLIST_VERSION, "rows": by_symbol, "fundamentals_as_of": {"oldest": fdates[0] if fdates else None, "newest": fdates[-1] if fdates else None}}


# ------------------------------------------------------------------------------------------------ value / quality / momentum ranking

async def _latest_fundamentals(db: AsyncSession) -> dict:
    """Each company's NEWEST fetch (by retrieval time). Not the largest as-of date: older rows carried the fetch day in that column, which can sort after a real quarter end."""
    newest = select(FundamentalMetrics.instrument_id.label("iid"), func.max(FundamentalMetrics.retrieved_at).label("t")).group_by(FundamentalMetrics.instrument_id).subquery()
    rows = (await db.execute(select(FundamentalMetrics).join(newest, (newest.c.iid == FundamentalMetrics.instrument_id) & (newest.c.t == FundamentalMetrics.retrieved_at)))).scalars()
    return {f.instrument_id: f for f in rows}


def _avg_assets(f) -> float | None:
    a, b = getattr(f, "total_assets", None), getattr(f, "total_assets_prior", None)
    return (a + b) / 2.0 if a is not None and b is not None and a > 0 and b > 0 else None


async def load_rank_inputs(db: AsyncSession) -> list[tuple[Security, "R.RankInput"]]:
    from app.portfolio_intelligence.scoring import ranking as R
    from app.portfolio_intelligence.scoring.momentum import momentum_for

    secs = (await db.execute(select(Security).where(Security.kind == "stock", Security.is_active.is_(True), Security.instrument_id.is_not(None)))).scalars().all()
    funds = await _latest_fundamentals(db)
    latest_s = (select(SecuritySignal.security_id.label("sid"), func.max(SecuritySignal.as_of_date).label("d")).group_by(SecuritySignal.security_id).subquery())
    sigs = {g.security_id: g for g in (await db.execute(select(SecuritySignal).join(latest_s, (latest_s.c.sid == SecuritySignal.security_id) & (latest_s.c.d == SecuritySignal.as_of_date)))).scalars()}
    mom = await momentum_for(db, list(secs))
    out = []
    for s in secs:
        f, g, m = funds.get(s.instrument_id), sigs.get(s.id), mom.get(s.id)
        last = (await db.execute(select(SecurityCandle.trade_date, SecurityCandle.close).where(SecurityCandle.security_id == s.id).order_by(SecurityCandle.trade_date.desc()).limit(1))).first()
        ok = g is not None and g.quality == "ok"
        out.append((s, R.RankInput(
            symbol=s.symbol, name=s.name, sector=s.sector, price=float(last[1]) if last else None,
            eps=getattr(f, "eps", None), pat=getattr(f, "pat", None), market_cap=getattr(f, "market_cap", None), pb=getattr(f, "pb", None), ev_ebitda=getattr(f, "ev_ebitda", None),
            free_cash_flow=getattr(f, "annual_free_cash_flow", None), operating_cash_flow=getattr(f, "annual_operating_cash_flow", None),
            avg_total_assets=_avg_assets(f), annual_net_income=getattr(f, "annual_net_income", None),
            annual_period_end=f.annual_period_end.isoformat() if getattr(f, "annual_period_end", None) else None,
            nse_eps_ttm=getattr(f, "nse_eps_ttm", None), nse_period_end=f.nse_period_end.isoformat() if getattr(f, "nse_period_end", None) else None,
            net_margin=getattr(f, "net_margin", None), ebitda_margin=getattr(f, "ebitda_margin", None), revenue_growth=getattr(f, "revenue_growth", None), eps_growth=getattr(f, "eps_growth", None),
            debt_to_equity=getattr(f, "debt_to_equity", None), roe_stored=getattr(f, "roe", None),
            dividend_ttm=None if m is None else m.get("dps_ttm"), dividend_reliable=False if m is None else bool(m.get("dps_reliable")),
            mom_12_1=None if m is None else m["mom_12_1"], mom_6_1=None if m is None else m["mom_6_1"], momentum_basis=None if m is None else m["basis"],
            fundamentals_as_of=f.as_of_date.isoformat() if f is not None else None, price_as_of=last[0].isoformat() if last else None,
            risk={"vol_252": float(g.vol_252) if ok and g.vol_252 is not None else None, "max_dd_1y": float(g.max_dd_1y) if ok and g.max_dd_1y is not None else None,
                  "liquidity_value": float(g.liquidity_value) if ok and g.liquidity_value is not None else None, "circuit_days_20": g.circuit_days_20 if ok else None,
                  "signal_quality": g.quality if g is not None else None})))
    return out


async def market_regime(db: AsyncSession) -> dict:
    """Momentum-crash state from the NIFTYBEES price series (price, not total return: it is only a market-state label)."""
    from app.portfolio_intelligence.scoring.momentum import momentum_regime

    sid = (await db.execute(select(Security.id).where(Security.symbol == "NIFTYBEES", Security.kind == "etf"))).scalar_one_or_none()
    if sid is None:
        return momentum_regime([])
    closes = [float(c) for (c,) in (await db.execute(select(SecurityCandle.close).where(SecurityCandle.security_id == sid).order_by(SecurityCandle.trade_date))).all()]
    return {**momentum_regime(closes), "proxy": "NIFTYBEES"}


async def current_ranking(db: AsyncSession, *, persist: bool = True, now: datetime | None = None) -> dict:
    """The value / quality / momentum ranking of the Nifty 50, stored point-in-time (insert-only) under its own method version."""
    from datetime import date as _date

    from app.core.config import settings
    from app.portfolio_intelligence.scoring import ranking as R

    now = now or utcnow()
    weights = R.parse_weights(settings.stock_rank_weights)
    floor = float(settings.stock_rank_floor)
    pairs = await load_rank_inputs(db)
    rows = R.score_universe([p[1] for p in pairs], weights, floor)
    by_symbol = {r["symbol"]: r for r in rows}
    if persist:
        for sec, inp in pairs:
            r = by_symbol[inp.symbol]
            if inp.price_as_of is None:
                continue
            d = _date.fromisoformat(inp.price_as_of)
            exists = (await db.execute(select(SecurityScore.security_id).where(SecurityScore.security_id == sec.id, SecurityScore.as_of_date == d, SecurityScore.method_version == R.RANK_VERSION))).first()
            if exists is None:
                status = {"eligible": "eligible", "below_floor": "below_floor", "not_ranked": "not_scored"}[r["status"]]
                db.add(SecurityScore(security_id=sec.id, as_of_date=d, method_version=R.RANK_VERSION, computed_at=now, score=r["composite"], coverage=r["coverage"], status=status,
                                     fundamentals_as_of=_date.fromisoformat(inp.fundamentals_as_of) if inp.fundamentals_as_of else None,
                                     detail={k: v for k, v in r.items() if k not in ("symbol", "name")}))
        await db.commit()
    ids = {inp.symbol: str(sec.id) for sec, inp in pairs}
    for sym, r in by_symbol.items():
        r["security_id"] = ids[sym]
    fdates = sorted({r["dates"]["fundamentals_as_of"] for r in rows if r["dates"]["fundamentals_as_of"]})
    return {"version": R.RANK_VERSION, "weights": weights, "floor": floor, "rows": by_symbol, "fundamentals_as_of": {"oldest": fdates[0] if fdates else None, "newest": fdates[-1] if fdates else None},
            "policy_note": "An unvalidated policy: equal weights by default, configurable, not an optimised strategy. It has not been tested against later prices.",
            "momentum_caution": await market_regime(db)}
