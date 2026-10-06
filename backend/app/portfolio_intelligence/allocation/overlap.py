"""What the owner already holds of each Nifty 50 stock: directly, and through a Nifty 50 index fund or ETF (the only look-through this app supports).

The fund view is an APPROXIMATION: an index product holds the index in roughly its weights, which this app approximates by each constituent's share of
the total market cap among the constituents whose stored market cap passed the consistency check. Free-float adjustment is ignored. It is used to annotate
a candidate and to leave out one that is already at the single-stock cap; it never changes a safety gate."""

import re
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.securities import Security

# "Nifty 50" exactly (not equal weight, next 50, value, alpha ...). Funds are named "... Nifty 50 Index Fund".
_ETF_CATEGORY = re.compile(r"^(nifty ?50|nifty 50 tri|sensex|s&p bse sensex|bse sensex)$")
_FUND_NAME = re.compile(r"nifty ?50 (index|etf)", re.I)
_NOT_PLAIN = re.compile(r"equal|next|value|alpha|quality|momentum|low vol|dividend|shariah|50:50|midcap|smallcap|arbitrage|bond|g-?sec|gilt|debt|liquid", re.I)


def is_nifty50_product(name: str | None, category: str | None, kind: str) -> bool:
    name, category = (name or ""), (category or "")
    if kind == "etf":
        return bool(_ETF_CATEGORY.match(category.lower().strip()) or _ETF_CATEGORY.match(name.lower().strip()))
    if kind == "mutual_fund":
        return bool(_FUND_NAME.search(name)) and not _NOT_PLAIN.search(name)
    return False


def lookthrough_weights(fund_values: list[float], caps: dict[str, float], base_total: float) -> dict[str, float]:
    """{symbol: share of the whole portfolio held through the funds}, cap-weighted over the constituents whose market cap is known and trusted."""
    total_cap = sum(c for c in caps.values() if c and c > 0)
    if total_cap <= 0 or base_total <= 0:
        return {}
    value = sum(v for v in fund_values if v and v > 0)
    return {sym: value / base_total * (c / total_cap) for sym, c in caps.items() if c and c > 0}


async def exposure(db: AsyncSession, positions: list[dict], ranking_rows: dict, base_total: Decimal) -> dict[str, dict]:
    """-> {symbol: {"direct": w, "lookthrough": w, "total": w}} as shares of `base_total` (the portfolio after the plan). Only stocks with a weight above zero appear."""
    base = float(base_total)
    direct: dict[str, float] = {}
    isins = {(p.get("isin") or "").upper() for p in positions if p.get("isin") and p.get("value") is not None and p["asset_type"] in ("etf", "mutual_fund", "listed_equity")}
    meta = {}
    if isins:
        for sec in (await db.execute(select(Security).where(or_(Security.isin.in_(isins), Security.isin_reinvest.in_(isins)), Security.is_active.is_(True)))).scalars():
            for key in (sec.isin, sec.isin_reinvest):
                if key in isins and (key not in meta or sec.kind == "etf"):
                    meta[key] = sec
    fund_values = []
    for p in positions:
        if p.get("value") is None:
            continue
        v = float(p["value"])
        sec = meta.get((p.get("isin") or "").upper())
        if p["asset_type"] == "listed_equity" and (sec is None or sec.kind == "stock") and p.get("label"):
            direct[p["label"]] = direct.get(p["label"], 0.0) + v
        elif sec is not None and is_nifty50_product(sec.name, sec.category, sec.kind):
            fund_values.append(v)
    caps = {sym: r["market_cap"] for sym, r in ranking_rows.items() if r.get("market_cap")}
    look = lookthrough_weights(fund_values, caps, base)
    out = {}
    for sym in set(direct) | set(look):
        d, l = (direct.get(sym, 0.0) / base if base > 0 else 0.0), look.get(sym, 0.0)
        out[sym] = {"direct": d, "lookthrough": l, "total": d + l}
    return out
