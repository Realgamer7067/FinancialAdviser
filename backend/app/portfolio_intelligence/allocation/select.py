"""Candidate instruments from the catalogue: one ETF per underlying (the most traded), a Nifty-50 stock satellite, a gold ETF and
a liquid ETF. Rules are explicit and deterministic; nothing here forecasts or ranks by expected return.

- ETF `category` text from NSE is free-form, so the broad indices are matched by explicit patterns.
- Eligibility: active, clean and fresh price history (signals quality `ok`), median turnover at or above the liquidity floor, and a
  last close no older than the engine's price staleness limit.
- Among ETFs of the same underlying the most traded wins (median 20-day turnover from the stored signals). Cost (expense ratio)
  is NOT compared: AMFI's expense-ratio file cannot yet be joined to these schemes without guessing names."""

import re
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import Security, SecurityCandle, SecuritySignal, SecurityTer
from app.portfolio_intelligence.signals.compute import LIQUIDITY_FLOOR_RUPEES

# underlying key -> pattern on (category or name), lower-cased. Exact index names only: "Nifty 50 Equal Weight" must not match "Nifty 50".
CORE_PATTERNS = {
    "large": re.compile(r"^(nifty ?50|nifty 50 tri|sensex|s&p bse sensex|bse sensex)$"),
    "next50": re.compile(r"^(nifty next ?50|nifty next 50 tri)$"),
    "mid150": re.compile(r"^(nifty midcap ?150|nifty midcap 150 tri)$"),
}
LIQUID_PATTERN = re.compile(r"1d rate|liquid|overnight")
GILT_PATTERN = re.compile(r"g-?sec|gilt|bharat bond")
FIXED_NAV_BAND = (Decimal("990"), Decimal("1010"))   # a price pinned near 1,000 is the dividend-unit kind of liquid ETF
PRICE_MAX_AGE_DAYS = 10
LIQUIDITY_SHARE_OF_LEADER = 0.20   # an ETF is a candidate only if it trades at least this share of the most traded one in its group


def payout_type(price: Decimal) -> str:
    return "dividend_units" if FIXED_NAV_BAND[0] <= price <= FIXED_NAV_BAND[1] else "growth"


async def _etfs(db: AsyncSession, asset_class: str, today: date) -> list[dict]:
    latest = (select(SecuritySignal.security_id.label("sid"), func.max(SecuritySignal.as_of_date).label("d")).group_by(SecuritySignal.security_id).subquery())
    rows = (await db.execute(select(Security, SecuritySignal).join(latest, latest.c.sid == Security.id)
                             .join(SecuritySignal, (SecuritySignal.security_id == Security.id) & (SecuritySignal.as_of_date == latest.c.d))
                             .where(Security.is_active.is_(True), Security.kind == "etf", Security.asset_class == asset_class, Security.series == "EQ",
                                    SecuritySignal.quality == "ok", SecuritySignal.liquidity_value.is_not(None)))).all()
    out = []
    for s, g in rows:
        if float(g.liquidity_value) < LIQUIDITY_FLOOR_RUPEES or (today - g.as_of_date).days > PRICE_MAX_AGE_DAYS:
            continue
        px = (await db.execute(select(SecurityCandle.close).where(SecurityCandle.security_id == s.id, SecurityCandle.trade_date == g.as_of_date))).scalar_one_or_none()
        if px is None or px <= 0:
            continue
        t = (await db.execute(select(SecurityTer.ter, SecurityTer.ter_date).where(SecurityTer.security_id == s.id))).first()
        out.append({"id": str(s.id), "symbol": s.symbol, "name": s.name, "kind": "etf", "isin": s.isin, "lot_size": s.lot_size or 1, "price": Decimal(str(px)),
                    "price_as_of": g.as_of_date, "sector": None, "turnover": float(g.liquidity_value), "category": (s.category or "").strip(), "asset_class": s.asset_class,
                    "ter": None if t is None else float(t[0]), "ter_date": None if t is None else t[1]})
    return sorted(out, key=lambda e: (-e["turnover"], e["symbol"]))


def _crore(x: float) -> str:
    return f"₹{x / 1e7:,.0f} crore"


def choose(group: list[dict]) -> tuple[dict, str]:
    """Pick one ETF from a group of the same underlying, already sorted most traded first. COST-AWARE with a liquidity guard:
    candidates are those trading at least LIQUIDITY_SHARE_OF_LEADER of the leader's turnover; among them the lowest KNOWN expense ratio wins
    (ties go to the more traded). An ETF whose expense ratio is unknown is never preferred over one whose is known; if none is known the
    leader is chosen. -> (etf, how)"""
    leader = group[0]["turnover"]
    cands = [e for e in group if e["turnover"] >= LIQUIDITY_SHARE_OF_LEADER * leader]
    known = [e for e in cands if e.get("ter") is not None]
    if not known:
        return group[0], "the most traded (no expense ratio is known for the candidates, so volume decides)"
    best = min(known, key=lambda e: (e["ter"], -e["turnover"]))
    return best, ("the most traded, and also the cheapest" if best is group[0] and best["ter"] <= min(e["ter"] for e in known)
                  else f"the cheapest expense ratio among the {len(cands)} that trade at least {int(LIQUIDITY_SHARE_OF_LEADER * 100)}% as much as the most traded")


def _ter_phrase(e: dict) -> str:
    return f"expense ratio {e['ter']:.2f}% a year (AMFI, {e['ter_date']})" if e.get("ter") is not None else "expense ratio not known (no defensible match to AMFI's file)"


async def _ter_text_unused(db: AsyncSession, security_id: str) -> tuple[str, float | None]:
    """The expense ratio as a phrase for the 'why' text. UNKNOWN is said plainly (never zero, never omitted)."""
    import uuid as _uuid

    t = (await db.execute(select(SecurityTer).where(SecurityTer.security_id == _uuid.UUID(security_id)))).scalar_one_or_none()
    return (f"expense ratio {t.ter:.2f}% a year (AMFI, {t.ter_date})", float(t.ter)) if t is not None else ("expense ratio not known (no defensible match to AMFI's file)", None)


async def select_candidates(db: AsyncSession, today: date, scores: dict | None = None, ranking: dict | None = None, exposure: dict | None = None) -> dict:
    # core Indian equity: one most-traded ETF per qualifying underlying
    equity = await _etfs(db, "equity", today)
    core: dict[str, dict] = {}
    for key, pat in CORE_PATTERNS.items():
        same = [e for e in equity if pat.match(e["category"].lower()) or pat.match(e["name"].lower())]
        if same:
            best, how = choose(same)
            best = dict(best)
            best["why"] = f"{how}, out of {len(same)} ETF(s) tracking this index (median turnover {_crore(best['turnover'])} a day); {_ter_phrase(best)}"
            core[key] = best
    golds = await _etfs(db, "gold", today)
    gold = []
    if golds:
        g, how = choose(golds)
        g = dict(g)
        g["why"] = f"{how}, out of {len(golds)} gold ETFs (median turnover {_crore(g['turnover'])} a day); {_ter_phrase(g)}"
        gold = [g]
    debt_all = [e for e in await _etfs(db, "debt", today) if LIQUID_PATTERN.search((e["category"] + " " + e["name"]).lower()) and not GILT_PATTERN.search((e["category"] + " " + e["name"]).lower())]
    for e in debt_all:
        e["payout"] = payout_type(e["price"])
        e["cash_like"] = True
    growth = [e for e in debt_all if e["payout"] == "growth"]
    pool = growth or debt_all
    debt = []
    if pool:
        d, how = choose(pool)
        d = dict(d)
        d["why"] = (f"{how}, out of {len(pool)} {'growth-NAV ' if d['payout'] == 'growth' else 'dividend-unit '}liquid ETFs (median turnover {_crore(d['turnover'])} a day); {_ter_phrase(d)}. "
                    "It holds overnight/very short-term debt, so its price barely moves")
        debt = [d]
    # satellite stocks: Nifty 50 members (sectors known to the risk engine), clean + liquid, one per sector, ordered by turnover (a liquidity
    # ordering, not a return signal)
    latest = (select(SecuritySignal.security_id.label("sid"), func.max(SecuritySignal.as_of_date).label("d")).group_by(SecuritySignal.security_id).subquery())
    rows = (await db.execute(select(Security, SecuritySignal).join(latest, latest.c.sid == Security.id)
                             .join(SecuritySignal, (SecuritySignal.security_id == Security.id) & (SecuritySignal.as_of_date == latest.c.d))
                             .where(Security.is_active.is_(True), Security.kind == "stock", Security.instrument_id.is_not(None), Security.series == "EQ",
                                    Security.sector.is_not(None), SecuritySignal.quality == "ok", SecuritySignal.liquidity_value.is_not(None)))).all()
    stocks = []
    for sec, g in rows:
        if float(g.liquidity_value) < LIQUIDITY_FLOOR_RUPEES or (today - g.as_of_date).days > PRICE_MAX_AGE_DAYS:
            continue
        px = (await db.execute(select(SecurityCandle.close).where(SecurityCandle.security_id == sec.id, SecurityCandle.trade_date == g.as_of_date))).scalar_one_or_none()
        if px is None or px <= 0:
            continue
        stocks.append({"id": str(sec.id), "instrument_id": str(sec.instrument_id), "symbol": sec.symbol, "name": sec.name, "kind": "stock", "isin": sec.isin, "lot_size": sec.lot_size or 1,
                       "price": Decimal(str(px)), "price_as_of": g.as_of_date, "sector": sec.sector, "turnover": float(g.liquidity_value)})
    liquid = {st["symbol"] for st in stocks}
    if ranking is not None:
        return {"core": core, "gold": gold, "debt": debt, "satellite": _ranked_satellite(stocks, ranking, exposure or {}), "liquid_stocks": liquid}
    if scores is None:
        # No scores supplied (older callers, tests): the original liquidity ordering, one per sector.
        stocks.sort(key=lambda e: (-e["turnover"], e["symbol"]))
        seen, satellite = set(), []
        for st in stocks:
            if st["sector"] in seen:
                continue
            seen.add(st["sector"])
            st["why"] = f"the most traded Nifty 50 stock in {st['sector']} (median turnover {_crore(st['turnover'])} a day); chosen by liquidity, not by any return signal"
            satellite.append(st)
        return {"core": core, "gold": gold, "debt": debt, "satellite": satellite[:10], "liquid_stocks": liquid}
    # With the checklist score: within each sector the highest-scoring liquid stock that clears the floor; sectors with none get no stock. The
    # liquidity gate, one-per-sector, equal weight and the per-stock cap are unchanged. The score is a screen and has not been tested against
    # later prices (see Model evidence); it is stored point-in-time so it can be.
    rows = scores["rows"]
    best: dict[str, dict] = {}
    for st in stocks:
        r = rows.get(st["symbol"])
        if r is None or r["status"] != "eligible" or r["score"] is None:
            continue
        st["score"], st["score_row"] = r["score"], r
        cur = best.get(st["sector"])
        if cur is None or (st["score"], st["turnover"]) > (cur["score"], cur["turnover"]):
            best[st["sector"]] = st
    satellite = sorted(best.values(), key=lambda e: (-e["score"], -e["turnover"], e["symbol"]))
    for st in satellite:
        top = ", ".join(k for k, v in sorted(st["score_row"]["components"].items(), key=lambda kv: -(kv[1]["score"] or 0))[:2])
        st["why"] = (f"the highest checklist score in {st['sector']} among liquid Nifty 50 stocks: {st['score']:.0f} of 100, strongest on {top} "
                     f"(median turnover {_crore(st['turnover'])} a day). The score is a screen on fundamentals and risk, not a forecast")
    return {"core": core, "gold": gold, "debt": debt, "satellite": satellite[:10], "liquid_stocks": liquid}


def _ranked_satellite(stocks: list[dict], ranking: dict, exposure: dict) -> list[dict]:
    """Candidates for direct stocks: ranked by the value / quality / momentum composite, at or above the floor, liquid, not already at the single-stock cap
    through direct holdings plus a Nifty 50 index product, at most SATELLITE_MAX_PER_SECTOR from one sector, and NO forced coverage: a sector with no
    candidate simply has none. Equal weight, the 3% cap and whole units are applied later, in the plan."""
    from app.portfolio_intelligence.allocation import policy as P

    rows = ranking["rows"]
    out, per_sector = [], {}
    cap = float(P.SATELLITE_MAX_WEIGHT_OF_PORTFOLIO)
    for st in sorted(stocks, key=lambda e: (-(rows.get(e["symbol"], {}).get("composite") or -1), -e["turnover"], e["symbol"])):
        r = rows.get(st["symbol"])
        if r is None or r["status"] != "eligible" or r["composite"] is None:
            continue
        held = exposure.get(st["symbol"])
        if held is not None and held["total"] >= cap:
            continue                                   # already at the single-stock cap: another purchase could not be added without breaching it
        if per_sector.get(st["sector"], 0) >= P.SATELLITE_MAX_PER_SECTOR:
            continue
        per_sector[st["sector"]] = per_sector.get(st["sector"], 0) + 1
        st["score"], st["rank_row"] = r["composite"], r
        strong = "; ".join(r["strengths"][:2]) or "no standout measure"
        weak = "; ".join(r["weaknesses"][:2]) or "no clear weakness among the measures used"
        st["why"] = (f"rank {r['rank']} of {r['rank_of']} on value, quality and momentum (composite {r['composite']:.0f}); strengths: {strong}; weaknesses: {weak}. "
                     f"A screen on fundamentals dated {r['dates']['fundamentals_as_of']} and total-return momentum, not a forecast. Median turnover {_crore(st['turnover'])} a day")
        out.append(st)
    return out[:10]


async def fund_alternatives(db: AsyncSession) -> list[dict]:
    """Direct-plan growth index funds on the Nifty 50, for a SIP, ranked by expense ratio WHERE IT IS KNOWN (cheapest first); funds whose expense
    ratio could not be matched are listed after them, marked unknown. No lock-in funds (ELSS / tax-saver are never offered)."""
    rows = (await db.execute(select(Security, SecurityTer).outerjoin(SecurityTer, SecurityTer.security_id == Security.id)
                             .where(Security.kind == "mutual_fund", Security.is_active.is_(True), Security.plan == "direct", Security.option == "growth",
                                    func.lower(Security.name).like("%nifty 50 index%"), func.lower(Security.name).not_like("%elss%"),
                                    func.lower(Security.name).not_like("%tax saver%"), func.lower(Security.name).not_like("%tax saving%")))).all()
    out = [{"name": r.name, "amc": r.amc, "scheme_code": r.scheme_code, "nav": None if r.nav is None else format(r.nav.normalize(), "f"), "nav_date": r.nav_date.isoformat() if r.nav_date else None,
            "ter_percent": None if t is None else float(t.ter), "ter_as_of": None if t is None else t.ter_date.isoformat()} for r, t in rows]
    out.sort(key=lambda f: (f["ter_percent"] is None, f["ter_percent"] if f["ter_percent"] is not None else 0, f["name"]))
    return out[:8]


async def liquid_fund_alternatives(db: AsyncSession) -> list[dict]:
    """Direct-plan growth liquid FUNDS (not ETFs), cheapest known expense ratio first. For a small amount that must stay safe: a fund is bought
    by rupee amount, unlike an ETF unit (about ₹1,100 each here)."""
    rows = (await db.execute(select(Security, SecurityTer).outerjoin(SecurityTer, SecurityTer.security_id == Security.id)
                             .where(Security.kind == "mutual_fund", Security.is_active.is_(True), Security.plan == "direct", Security.option == "growth",
                                    func.lower(Security.name).like("%liquid fund%"), func.lower(Security.name).not_like("%etf%")))).all()
    out = [{"name": r.name, "amc": r.amc, "scheme_code": r.scheme_code, "nav": None if r.nav is None else format(r.nav.normalize(), "f"), "nav_date": r.nav_date.isoformat() if r.nav_date else None,
            "ter_percent": None if t is None else float(t.ter), "ter_as_of": None if t is None else t.ter_date.isoformat()} for r, t in rows]
    out.sort(key=lambda f: (f["ter_percent"] is None, f["ter_percent"] if f["ter_percent"] is not None else 0, f["name"]))
    return out[:4]
