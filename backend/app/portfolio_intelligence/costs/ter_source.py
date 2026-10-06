"""AMFI total expense ratio (TER) download: official, public, no key.

Verified facts (2026-10-01): `populate-mf` lists the AMCs; `populate-te-rdata-revised?MF_ID&Month=MM-YYYY&strCat=-1&strType=1` returns the
month's DAILY TER rows for an AMC (one row per scheme per day), at most 100 per page, with `meta.total` and `meta.pageCount`; one row carries
both the Regular (`R_TER`) and Direct (`D_TER`) ratios. The API answers HTTP 200 with malformed JSON when it is throttling, so unparseable
JSON is treated as throttling (backoff and retry), never as an empty result. Hitting 1 call per second or slower is stable.

Only the LATEST row per scheme is kept: a TER is a current cost, and a daily history of it is not needed here."""

import asyncio
import json
import logging
from datetime import date, datetime

import httpx

logger = logging.getLogger("ter")
BASE = "https://www.amfiindia.com/api"
HOSTS = {"www.amfiindia.com"}
POLITE_SECONDS = 1.2
BACKOFF = (2.0, 6.0, 15.0)
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


class TerError(RuntimeError):
    pass


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=False, trust_env=False, headers={"User-Agent": _UA, "Accept": "application/json"})


async def _json(c: httpx.AsyncClient, url: str, params: dict | None, sleep=asyncio.sleep) -> dict | list:
    """GET and parse. Non-200, a transport error, or malformed JSON (the throttle signature) is retried with backoff, then raised."""
    last = "unknown"
    for attempt in range(len(BACKOFF) + 1):
        try:
            r = await c.get(url, params=params)
            if r.status_code == 200:
                try:
                    return json.loads(r.content)
                except ValueError:
                    last = "malformed JSON (AMFI throttling)"
            else:
                last = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            last = f"request failed: {type(exc).__name__}"
        if attempt < len(BACKOFF):
            await sleep(BACKOFF[attempt])
    raise TerError(last)


async def list_amcs(c: httpx.AsyncClient, sleep=asyncio.sleep) -> list[dict]:
    data = await _json(c, f"{BASE}/populate-mf", None, sleep)
    if not isinstance(data, list) or not data:
        raise TerError("AMC list is empty or not a list")
    return [{"mf_id": int(x["mfId"]), "name": str(x["mfName"]).strip()} for x in data if x.get("mfId") and x.get("mfName")]


async def fetch_amc_month(c: httpx.AsyncClient, mf_id: int, month: str, sleep=asyncio.sleep, page_size: int = 100) -> list[dict]:
    """Every page of one AMC-month. Pagination is driven by `meta.pageCount`; a page that parses but has no `data` list is an error, not the end."""
    rows, page, count = [], 1, 1
    while page <= count:
        d = await _json(c, f"{BASE}/populate-te-rdata-revised", {"MF_ID": mf_id, "Month": month, "strCat": -1, "strType": 1, "page": page, "pageSize": page_size}, sleep)
        if not isinstance(d, dict) or not isinstance(d.get("data"), list) or not isinstance(d.get("meta"), dict):
            raise TerError(f"unexpected TER response shape (AMC {mf_id}, page {page})")
        rows += d["data"]
        count = int(d["meta"].get("pageCount") or 1)
        page += 1
        if page <= count:
            await sleep(POLITE_SECONDS)
    expected = int(d["meta"].get("total") or 0)
    if expected and len(rows) < expected:
        raise TerError(f"AMC {mf_id}: got {len(rows)} of {expected} rows")     # a truncated download must never look complete
    return rows


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x >= 0 else None


def latest_per_scheme(rows: list[dict], mf_id: int) -> list[dict]:
    """One row per scheme (NSDL scheme code), the newest TER date. TERs are percentages of assets per year."""
    best: dict[str, dict] = {}
    for r in rows:
        code = str(r.get("NSDLSchemeCode") or "").strip()
        name = str(r.get("Scheme_Name") or "").strip()
        try:
            dt = datetime.fromisoformat(str(r["TER_Date"]).replace("Z", "+00:00")).date()
        except (KeyError, ValueError):
            continue
        if not code or not name:
            continue
        if code not in best or dt > best[code]["ter_date"]:
            best[code] = {"mf_id": mf_id, "nsdl_code": code, "scheme_name": name, "category": str(r.get("SchemeCat_Desc") or "").strip(), "ter_date": dt,
                          "regular_ter": _num(r.get("R_TER")), "direct_ter": _num(r.get("D_TER")), "regular_ber": _num(r.get("R_BER")), "direct_ber": _num(r.get("D_BER"))}
    return list(best.values())


def current_month(today: date) -> str:
    return today.strftime("%m-%Y")


def previous_month(today: date) -> str:
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return f"{m:02d}-{y}"
