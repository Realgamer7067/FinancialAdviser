"""Mutual fund NAV history from mfapi.in (free, no key), used only after it agrees with AMFI.

Verified 2026-10-01: `https://api.mfapi.in/mf/<AMFI scheme code>` returns `meta` (fund house, category, scheme code, ISINs) and `data`, newest
first, as {date: DD-MM-YYYY, nav: string}; the scheme code is AMFI's, which is our `Security.scheme_code` (the join key). The ISIN in `meta` is
only a cross-check.

TRUST RULES: (1) mfapi must agree with AMFI for the same scheme: exactly on AMFI's own date when mfapi has it, otherwise (mfapi trails AMFI by a day
or so) by matching ISIN and a NAV within 5% on a date at most 4 days earlier; when neither can be checked the fund is DEFERRED to the next run, not stored; (2) only GROWTH
options get a history: an IDCW NAV falls on every payout and is not a return series; (3) a history that fails basic sanity (non-positive, absurd
daily moves) is rejected, never repaired."""

import asyncio
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

BASE = "https://api.mfapi.in/mf"
HOST = "api.mfapi.in"
BACKOFF = (2.0, 6.0)
MAX_DAILY_MOVE = Decimal("0.5")        # a single-day NAV change beyond +/-50% is treated as a bad series (a split/merger would need review)
NAV_TOLERANCE = Decimal("0.0005")      # mfapi vs AMFI on the same date, relative


class NavError(RuntimeError):
    pass


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=False, trust_env=False, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})


async def fetch_scheme(c: httpx.AsyncClient, scheme_code: str, sleep=asyncio.sleep) -> dict:
    last = "unknown"
    for attempt in range(len(BACKOFF) + 1):
        try:
            r = await c.get(f"{BASE}/{scheme_code}")
            if r.status_code == 200:
                try:
                    d = json.loads(r.content)
                except ValueError:
                    last = "malformed JSON"
                else:
                    if isinstance(d, dict) and isinstance(d.get("data"), list) and isinstance(d.get("meta"), dict):
                        return d
                    last = "unexpected response shape"
            elif r.status_code == 404:
                raise NavError("scheme not found at mfapi")
            else:
                last = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            last = f"request failed: {type(exc).__name__}"
        if attempt < len(BACKOFF):
            await sleep(BACKOFF[attempt])
    raise NavError(last)


def parse_history(data: list) -> tuple[list[dict], int]:
    """-> (ascending candle-shaped rows with open=high=low=close=NAV and no volume, rejected count). Duplicate dates keep the last."""
    out: dict[date, dict] = {}
    bad = 0
    for r in data:
        try:
            d = datetime.strptime(str(r["date"]), "%d-%m-%Y").date()
            nav = Decimal(str(r["nav"]))
        except (KeyError, ValueError, InvalidOperation):
            bad += 1
            continue
        if not nav.is_finite() or nav <= 0:
            bad += 1
            continue
        out[d] = {"trade_date": d, "open": nav, "high": nav, "low": nav, "close": nav, "volume": None}
    return [out[d] for d in sorted(out)], bad


def sane(rows: list[dict]) -> str | None:
    """None if the series is plausible, else the reason it is rejected."""
    for a, b in zip(rows, rows[1:]):
        if abs(b["close"] / a["close"] - 1) > MAX_DAILY_MOVE:
            return f"a {abs(b['close'] / a['close'] - 1):.0%} one-day NAV change on {b['trade_date']}"
    return None


NEAR_DATE_DAYS = 4
NEAR_NAV_TOLERANCE = Decimal("0.05")


def verify_against_amfi(rows: list[dict], amfi_nav: Decimal | None, amfi_date: date | None, meta_isin: str | None, our_isin: str | None) -> tuple[str, str | None]:
    """-> (verdict, detail). verdict: `exact` (same date, same NAV), `isin_near_date` (ISIN agrees and the nearest earlier NAV is within 5%), `deferred`
    (cannot be checked yet; retry later) or `rejected` (it disagrees)."""
    if amfi_nav is None or amfi_date is None:
        return "deferred", "no AMFI NAV on file to verify against"
    if meta_isin and our_isin and meta_isin.upper() != our_isin.upper():
        return "rejected", f"ISIN mismatch (mfapi {meta_isin} vs ours {our_isin})"
    hit = next((r for r in rows if r["trade_date"] == amfi_date), None)
    if hit is not None:
        if abs(hit["close"] - amfi_nav) / amfi_nav > NAV_TOLERANCE:
            return "rejected", f"mfapi NAV {hit['close']} differs from AMFI's {amfi_nav} on {amfi_date}"
        return "exact", None
    earlier = [r for r in rows if r["trade_date"] < amfi_date and (amfi_date - r["trade_date"]).days <= NEAR_DATE_DAYS]
    if not earlier:
        return "deferred", f"mfapi has no NAV within {NEAR_DATE_DAYS} days before AMFI's date {amfi_date} yet"
    if not meta_isin or not our_isin:
        return "deferred", "mfapi does not have AMFI's date yet and no ISIN is available to confirm the scheme"
    near = earlier[-1]
    if abs(near["close"] - amfi_nav) / amfi_nav > NEAR_NAV_TOLERANCE:
        return "rejected", f"mfapi NAV {near['close']} on {near['trade_date']} is more than 5% from AMFI's {amfi_nav} on {amfi_date}"
    return "isin_near_date", None
