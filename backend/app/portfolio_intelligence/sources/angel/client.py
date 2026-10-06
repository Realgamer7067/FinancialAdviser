"""Read-only Angel One SmartAPI client (plan section 3).

Read-only is enforced HERE, in code: only the endpoints in ENDPOINTS exist,
no order/modify/cancel method is defined, and requests may only go to
ALLOWED_HOSTS over https. No SDK is imported. Nothing here logs request or
response bodies, headers or credentials; errors carry only a code and a short
fixed message."""

import asyncio
import logging
import random
import time
import uuid
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.portfolio_intelligence.sources.angel.errors import (
    AngelError,
    AuthExpired,
    BadResponse,
    RateLimited,
    Unavailable,
)

logger = logging.getLogger("angel")

BASE_URL = "https://apiconnect.angelone.in"
ALLOWED_HOSTS = {"apiconnect.angelone.in"}

# name -> (HTTP method, path). The complete surface of this client.
ENDPOINTS = {
    "login": ("POST", "/rest/auth/angelbroking/user/v1/loginByPassword"),
    "profile": ("GET", "/rest/secure/angelbroking/user/v1/getProfile"),
    "holdings": ("GET", "/rest/secure/angelbroking/portfolio/v1/getAllHolding"),
    "positions": ("GET", "/rest/secure/angelbroking/order/v1/getPosition"),
    "rms": ("GET", "/rest/secure/angelbroking/user/v1/getRMS"),
    "quote": ("POST", "/rest/secure/angelbroking/market/v1/quote"),
    "candles": ("POST", "/rest/secure/angelbroking/historical/v1/getCandleData"),
}

# Conservative: the docs disagree (1/s in prose vs 10/s in a table).
MIN_INTERVAL_SECONDS = 1.0
QUOTE_BATCH_MAX = 50
_AUTH_CODES = {"AG8001", "AG8002", "AG8003", "AB8050", "AB8051"}
TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _assert_allowed(url: str) -> None:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise Unavailable("request blocked: host not allowlisted")


def normalize_envelope(body: object) -> dict:
    """Angel responses use status/errorcode in most places but success/errorCode
    in some. Normalize the documented variants; reject anything else."""
    if not isinstance(body, dict):
        raise BadResponse("response is not a JSON object")
    if "status" in body:
        ok = body["status"]
    elif "success" in body:
        ok = body["success"]
    else:
        raise BadResponse("unrecognized response envelope")
    if isinstance(ok, str):
        ok = ok.strip().lower() in ("true", "success")
    if not isinstance(ok, bool):
        raise BadResponse("unrecognized response envelope")
    code = body.get("errorcode") or body.get("errorCode") or ""
    return {"ok": ok, "errorcode": str(code), "message": str(body.get("message", ""))[:120], "data": body.get("data")}


class AngelClient:
    """One instance per process/job. `transport` is injectable for tests."""

    def __init__(self, api_key: str | None = None, jwt: str | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        self._api_key = api_key if api_key is not None else settings.angel_api_key
        self._jwt = jwt
        proxy = settings.angel_proxy_url.strip() or None
        if proxy is not None and not proxy.lower().startswith(("socks5://", "socks5h://", "http://")):
            raise Unavailable("ANGEL_PROXY_URL must start with socks5://, socks5h:// or http://")
        # trust_env=False: never pick up an ambient HTTP(S)_PROXY / skip the allowlisted route.
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT, follow_redirects=False, trust_env=False,
                                       **({"transport": transport} if transport is not None else {"proxy": proxy}))
        self._last_call: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    def _headers(self) -> dict[str, str]:
        mac = ":".join(f"{(uuid.getnode() >> s) & 0xFF:02x}" for s in range(40, -1, -8))
        h = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": settings.angel_client_public_ip,
            "X-MACAddress": mac,
            "X-PrivateKey": self._api_key,
        }
        if self._jwt:
            h["Authorization"] = f"Bearer {self._jwt}"
        return h

    async def _throttle(self, name: str) -> None:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - self._last_call.get(name, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call[name] = time.monotonic()

    async def _call(self, name: str, json_body: dict | None = None) -> dict:
        method, path = ENDPOINTS[name]
        _assert_allowed(BASE_URL + path)
        if not self._api_key:
            raise Unavailable("ANGEL_API_KEY is not configured")
        if name != "login" and not self._jwt:
            raise AuthExpired("no session")
        attempts = 0
        while True:
            attempts += 1
            await self._throttle(name)
            started = time.monotonic()
            try:
                resp = await self._http.request(method, path, headers=self._headers(), json=json_body)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempts < 2:
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    continue
                raise Unavailable("network error contacting broker")
            logger.info("angel %s status=%s elapsed=%.2fs", name, resp.status_code, time.monotonic() - started)
            try:
                return self._interpret(name, resp)
            except Unavailable:
                # one bounded retry for transient server errors, reads/quotes only
                if attempts < 2 and (method == "GET" or name in ("quote", "candles")):
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    continue
                raise

    def _interpret(self, name: str, resp: httpx.Response) -> dict:
        if resp.status_code == 429 or (resp.status_code == 403 and "rate" in resp.text[:300].lower()):
            ra = resp.headers.get("Retry-After")
            raise RateLimited("broker rate limit", retry_after=float(ra) if ra and ra.replace(".", "", 1).isdigit() else None)
        if resp.status_code in (401, 403):
            raise AuthExpired("broker rejected the session")
        if resp.status_code >= 500:
            raise Unavailable("broker unavailable")
        try:
            body = resp.json()
        except ValueError:
            raise BadResponse("response is not JSON")
        env = normalize_envelope(body)
        if not env["ok"]:
            if env["errorcode"] in _AUTH_CODES:
                raise AuthExpired("broker session invalid or expired")
            if "rate" in env["message"].lower() and "limit" in env["message"].lower():
                raise RateLimited("broker rate limit")
            # The broker's own message can be a login failure; keep code only.
            raise AngelError(f"broker returned an error ({env['errorcode'] or 'no code'})")
        return env

    # -- allowlisted operations -------------------------------------------

    async def login(self, client_code: str, pin: str, totp: str) -> dict:
        """Returns {'jwt','refresh_token','feed_token'}. Credentials are used
        for this one request and never stored or logged."""
        env = await self._call("login", {"clientcode": client_code, "password": pin, "totp": totp})
        data = env["data"]
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data.get(k) for k in ("jwtToken", "refreshToken", "feedToken")):
            raise BadResponse("login response missing tokens")
        self._jwt = data["jwtToken"]
        return {"jwt": data["jwtToken"], "refresh_token": data["refreshToken"], "feed_token": data["feedToken"]}

    async def get_profile(self) -> dict:
        data = (await self._call("profile"))["data"]
        if not isinstance(data, dict) or not data.get("clientcode"):
            raise BadResponse("profile response missing clientcode")
        return data

    async def get_all_holding(self) -> dict:
        """Returns the raw `data` object; parsing/validation lives in holdings.py."""
        data = (await self._call("holdings"))["data"]
        if not isinstance(data, dict):
            raise BadResponse("holdings response has no data object")
        return data

    async def get_positions(self) -> list:
        data = (await self._call("positions"))["data"]
        if data is None:
            return []
        if not isinstance(data, list):
            raise BadResponse("positions response is not a list")
        return data

    async def get_rms(self) -> dict:
        data = (await self._call("rms"))["data"]
        if not isinstance(data, dict):
            raise BadResponse("rms response has no data object")
        return data

    async def get_quotes(self, exchange_tokens: dict[str, list[str]], mode: str = "LTP") -> dict:
        """exchange_tokens: {"NSE": ["3045", ...]}. Splits into <=50-token
        batches. Returns {'fetched': [...], 'unfetched': [...]} -- callers must
        handle `unfetched`; it is never silently dropped."""
        if mode not in ("LTP", "OHLC", "FULL"):
            raise ValueError("bad quote mode")
        fetched: list = []
        unfetched: list = []
        for exchange, tokens in exchange_tokens.items():
            for i in range(0, len(tokens), QUOTE_BATCH_MAX):
                data = (await self._call("quote", {"mode": mode, "exchangeTokens": {exchange: tokens[i : i + QUOTE_BATCH_MAX]}}))["data"]
                if not isinstance(data, dict):
                    raise BadResponse("quote response has no data object")
                fetched.extend(data.get("fetched") or [])
                unfetched.extend(data.get("unfetched") or [])
        return {"fetched": fetched, "unfetched": unfetched}

    async def get_daily_candles(self, exchange: str, token: str, from_date: str, to_date: str) -> list:
        """Daily candles [[timestamp, o, h, l, c, v], ...] for one instrument, oldest first, UNADJUSTED for
        corporate actions. Dates are 'YYYY-MM-DD'. Parsing/validation lives in market/candles.py."""
        body = {"exchange": exchange, "symboltoken": token, "interval": "ONE_DAY",
                "fromdate": f"{from_date} 09:15", "todate": f"{to_date} 15:30"}
        data = (await self._call("candles", body))["data"]
        if data is None:
            return []
        if not isinstance(data, list):
            raise BadResponse("candle response is not a list")
        return data
