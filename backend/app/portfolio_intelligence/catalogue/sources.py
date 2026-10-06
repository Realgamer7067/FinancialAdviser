"""Downloads for the public reference files. Allowlisted hosts only, no redirects, bounded size, no
credentials. These are the only network calls the catalogue makes; parsing and storage live elsewhere so
tests run on saved fixtures."""

import asyncio
from datetime import date
from urllib.parse import urlparse

import httpx

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
ALLOWED_HOSTS = {"nsearchives.nseindia.com", "www.niftyindices.com", "portal.amfiindia.com", "www.nseindia.com"}
MAX_BYTES = 30_000_000

URLS = {
    "equity_l": "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "etf_list": "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv",
    "sector_map": "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv",
    "amfi": "https://portal.amfiindia.com/spages/NAVAll.txt",
}
NSE_ACTIONS_URL = "https://www.nseindia.com/api/corporates-corporateActions"
NSE_HOLIDAYS_URL = "https://www.nseindia.com/api/holiday-master"
NSE_POLITE_SECONDS = 1.0


class SourceError(RuntimeError):
    pass


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=False, trust_env=False,
                             headers={"User-Agent": _UA, "Accept": "*/*"})


RETRY_DELAYS = (2.0, 6.0)  # transient connect/DNS errors and 429/5xx are retried; anything else fails at once


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None, retry_delays: tuple = RETRY_DELAYS) -> httpx.Response:
    if urlparse(url).hostname not in ALLOWED_HOSTS:
        raise SourceError("host not allowlisted")
    host, last = urlparse(url).hostname, "unknown"
    for attempt in range(len(retry_delays) + 1):
        try:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                if len(r.content) > MAX_BYTES:
                    raise SourceError("response unexpectedly large")
                return r
            last = f"HTTP {r.status_code} from {host}"
            if r.status_code != 429 and r.status_code < 500:
                raise SourceError(last)
        except httpx.HTTPError as exc:
            last = f"request failed: {type(exc).__name__}"
        if attempt < len(retry_delays):
            await asyncio.sleep(retry_delays[attempt])
    raise SourceError(last)


async def fetch_text(name: str, client: httpx.AsyncClient | None = None) -> str:
    own = client is None
    client = client or _client()
    try:
        return (await _get(client, URLS[name])).content.decode("utf-8", errors="replace")
    finally:
        if own:
            await client.aclose()


async def fetch_actions(from_date: date, to_date: date, client: httpx.AsyncClient | None = None) -> list[dict]:
    """NSE corporate actions with ex-dates in [from_date, to_date] (all equities). Works without cookies from
    the VPN IP at the time of writing; NSE may change that, so any non-JSON answer is a SourceError."""
    own = client is None
    client = client or _client()
    try:
        r = await _get(client, NSE_ACTIONS_URL, {"index": "equities", "from_date": from_date.strftime("%d-%m-%Y"),
                                                   "to_date": to_date.strftime("%d-%m-%Y")})
        try:
            data = r.json()
        except ValueError as exc:
            raise SourceError("NSE did not return JSON") from exc
        if not isinstance(data, list):
            raise SourceError("unexpected NSE response shape")
        return data
    finally:
        if own:
            await client.aclose()


async def fetch_holidays(client: httpx.AsyncClient | None = None) -> dict:
    own = client is None
    client = client or _client()
    try:
        r = await _get(client, NSE_HOLIDAYS_URL, {"type": "trading"})
        try:
            return r.json()
        except ValueError as exc:
            raise SourceError("NSE did not return JSON for holidays") from exc
    finally:
        if own:
            await client.aclose()


def date_chunks(start: date, end: date, days: int = 92) -> list[tuple[date, date]]:
    """Quarter-sized windows, so one answer stays small and a failed window is retried alone."""
    from datetime import timedelta

    out, cur = [], start
    while cur <= end:
        nxt = min(cur + timedelta(days=days - 1), end)
        out.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return out


async def polite_sleep() -> None:
    await asyncio.sleep(NSE_POLITE_SECONDS)
