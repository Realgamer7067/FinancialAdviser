"""Official quarterly results from NSE's integrated-filing API, used as a CROSS-CHECK on Yahoo's earnings per share and to show when Yahoo is a quarter behind.

Only quarterly profit and loss is read: revenue, profit and basic EPS (the quarterly filing carries no balance sheet or cash flow). It never replaces a Yahoo
figure. Trailing EPS is the sum of the newest four quarters, and a later bonus or split would make older quarters' per-share figures not comparable, so a
disagreement is a FLAG for a person to look at, not a correction.

Network: NSE's website needs a session cookie that its API hands out on a first request. Only nseindia.com hosts are ever fetched."""

import asyncio
import re
from datetime import date, datetime
from urllib.parse import urlparse

import httpx

BASE = "https://www.nseindia.com"
LIST_URL = BASE + "/api/integrated-filing-results"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MAX_BYTES = 3_000_000
QUARTER_DAYS = (80, 100)


class NseError(Exception):
    pass


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=25, follow_redirects=False, headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"})


def _host_ok(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "https" and (u.hostname or "").endswith("nseindia.com")


async def warm(c: httpx.AsyncClient) -> None:
    """The home page itself may answer 403; what matters is the cookies it sets."""
    try:
        await c.get(BASE + "/")
    except httpx.HTTPError as exc:
        raise NseError(f"NSE not reachable: {type(exc).__name__}") from exc


async def list_filings(c: httpx.AsyncClient, symbol: str) -> list[dict]:
    try:
        r = await c.get(LIST_URL, params={"symbol": symbol, "index": "equities", "type": "Integrated Filing- Financials"},
                        headers={"Referer": BASE + "/companies-listing/corporate-integrated-filing"})
    except httpx.HTTPError as exc:
        raise NseError(f"list failed: {type(exc).__name__}") from exc
    if r.status_code != 200:
        raise NseError(f"list returned HTTP {r.status_code}")
    try:
        data = r.json().get("data")
    except ValueError as exc:
        raise NseError("list was not JSON") from exc
    return data if isinstance(data, list) else []


def group_quarters(rows: list[dict], n: int = 4, per_quarter: int = 3) -> list[list[dict]]:
    """Newest `n` distinct quarter ends, each with its candidate filings best first: consolidated before standalone, then the latest revision.
    A quarter can have a half-year or annual filing beside its quarterly one, so the caller tries candidates until one yields a three-month period."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        if not r.get("xbrl") or not r.get("qe_Date"):
            continue
        try:
            qe = datetime.strptime(r["qe_Date"], "%d-%b-%Y").date().isoformat()
        except ValueError:
            continue
        rank = (1 if str(r.get("consolidated", "")).lower() == "consolidated" else 0, _created(r))
        groups.setdefault(qe, []).append({**r, "_rank": rank, "_qe": qe})
    return [sorted(groups[k], key=lambda x: x["_rank"], reverse=True)[:per_quarter] for k in sorted(groups, reverse=True)[:n]]


def _created(r: dict) -> str:
    """Sortable creation time; NSE writes it as 09-Jul-2026 18:36:20."""
    try:
        return datetime.strptime(str(r.get("creation_Date")), "%d-%b-%Y %H:%M:%S").isoformat()
    except ValueError:
        try:
            return datetime.strptime(str(r.get("creation_Date")), "%d-%b-%Y").isoformat()
        except ValueError:
            return ""


def pick_quarters(rows: list[dict], n: int = 4) -> list[dict]:
    """The best single filing per quarter (kept for callers that want one)."""
    return [g[0] for g in group_quarters(rows, n)]


_CTX = re.compile(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', re.S)


def _fact(xml: str, tag: str, ctx: str) -> float | None:
    m = re.search(r"<[\w-]+:" + re.escape(tag) + r'\s+[^>]*contextRef="' + re.escape(ctx) + r'"[^>]*>\s*([-+0-9.eE]+)\s*<', xml)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def parse_quarter(xml: str) -> dict | None:
    """-> {period_end, eps, profit, revenue, nature} for the filing's own quarter, or None when no three-month period without a dimension is found."""
    ctx = None
    for cid, body in _CTX.findall(xml):
        if "scenario" in body:
            continue
        s, e = re.search(r"<xbrli:startDate>([^<]+)", body), re.search(r"<xbrli:endDate>([^<]+)", body)
        if not (s and e):
            continue
        try:
            d0, d1 = date.fromisoformat(s.group(1).strip()), date.fromisoformat(e.group(1).strip())
        except ValueError:
            continue
        if QUARTER_DAYS[0] <= (d1 - d0).days <= QUARTER_DAYS[1] and (ctx is None or d1 > ctx[1]):
            ctx = (cid, d1)
    if ctx is None:
        return None
    cid, end = ctx
    eps = None
    for tag in ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsLossPerShareFromContinuingOperations",
                "BasicEarningsPerShareAfterExtraordinaryItems", "BasicEarningsPerShareBeforeExtraordinaryItems"):      # the last two are the banking-format names
        eps = _fact(xml, tag, cid)
        if eps is not None:
            break
    profit = _fact(xml, "ProfitOrLossAttributableToOwnersOfParent", cid)
    if profit is None:
        profit = _fact(xml, "ProfitLossForPeriod", cid)
    nature = re.search(r"NatureOfReportStandaloneConsolidated[^>]*>([^<]+)<", xml)
    return {"period_end": end, "eps": eps, "profit": profit, "revenue": _fact(xml, "RevenueFromOperations", cid), "nature": nature.group(1).strip() if nature else None}


async def fetch_quarter(c: httpx.AsyncClient, url: str) -> dict | None:
    if not _host_ok(url):
        raise NseError("refusing a non-NSE address")
    try:
        r = await c.get(url)
    except httpx.HTTPError as exc:
        raise NseError(f"filing failed: {type(exc).__name__}") from exc
    if r.status_code != 200 or len(r.content) > MAX_BYTES:
        raise NseError(f"filing returned HTTP {r.status_code}, {len(r.content)} bytes")
    return parse_quarter(r.text)


def ttm_eps(quarters: list[dict]) -> tuple[float | None, date | None, int]:
    """Sum of basic EPS over the newest four consecutive quarters. Fewer than four, a gap, or a missing figure gives None."""
    qs = sorted((q for q in quarters if q), key=lambda q: q["period_end"], reverse=True)[:4]
    if len(qs) < 4 or any(q["eps"] is None for q in qs):
        return None, (qs[0]["period_end"] if qs else None), len(qs)
    spans = [(qs[i]["period_end"] - qs[i + 1]["period_end"]).days for i in range(3)]
    if any(not (80 <= d <= 100) for d in spans):
        return None, qs[0]["period_end"], len(qs)
    return sum(q["eps"] for q in qs), qs[0]["period_end"], 4


async def check_symbol(c: httpx.AsyncClient, symbol: str, pace: float = 0.6) -> dict:
    """-> {nse_eps_ttm, nse_period_end, nse_quarters}; raises NseError when NSE cannot be read (the caller records it, nothing is guessed)."""
    rows = await list_filings(c, symbol)
    out = []
    for cands in group_quarters(rows):
        got = None
        for p in cands:
            await asyncio.sleep(pace)
            q = await fetch_quarter(c, p["xbrl"])
            if q is not None and q["eps"] is not None:
                got = q
                break
        out.append(got)
    eps, end, n = ttm_eps(out)
    latest = max((q["period_end"] for q in out if q), default=None)
    return {"nse_eps_ttm": eps, "nse_period_end": latest or end, "nse_quarters": n}
