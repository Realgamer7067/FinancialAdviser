"""Angel client: envelope handling, typed errors, allowlist, batching, redaction."""

import logging

import httpx
import pytest

from app.portfolio_intelligence.sources.angel import client as client_mod
from app.portfolio_intelligence.sources.angel.client import ENDPOINTS, AngelClient, normalize_envelope
from app.portfolio_intelligence.sources.angel.errors import (
    AngelError, AuthExpired, BadResponse, RateLimited, Unavailable,
)
from tests.angel_fixtures import ok, transport

SECRET_JWT = "jwt-SECRET-123"


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(client_mod, "MIN_INTERVAL_SECONDS", 0.0)

    async def no_sleep(_):
        return None
    monkeypatch.setattr(client_mod.asyncio, "sleep", no_sleep)


def make(routes, calls=None, jwt=SECRET_JWT):
    return AngelClient(api_key="key", jwt=jwt, transport=transport(routes, calls))


def test_read_only_surface():
    names = set(ENDPOINTS)
    assert names == {"login", "profile", "holdings", "positions", "rms", "quote", "candles"}  # candles = getCandleData (read-only history), added in P1
    assert not any(w in path.lower() for _, path in ENDPOINTS.values() for w in ("order/v1/place", "modify", "cancel"))
    assert not any(hasattr(AngelClient, n) for n in ("place_order", "modify_order", "cancel_order"))
    assert {method for method, _ in ENDPOINTS.values()} <= {"GET", "POST"} and ENDPOINTS["candles"][1].endswith("/historical/v1/getCandleData")


def test_host_allowlist():
    with pytest.raises(Unavailable):
        client_mod._assert_allowed("https://evil.example/x")
    with pytest.raises(Unavailable):
        client_mod._assert_allowed("http://apiconnect.angelone.in/x")


def test_envelope_variants():
    assert normalize_envelope({"status": True, "data": 1})["ok"] is True
    assert normalize_envelope({"success": False, "errorCode": "E1", "message": "m"})["errorcode"] == "E1"
    with pytest.raises(BadResponse):
        normalize_envelope({"foo": 1})
    with pytest.raises(BadResponse):
        normalize_envelope([1])


async def test_auth_expired_codes_and_status():
    c = make({"getProfile": {"status": False, "message": "Invalid Token", "errorcode": "AG8001", "data": None}})
    with pytest.raises(AuthExpired):
        await c.get_profile()
    c = make({"getProfile": lambda r: httpx.Response(401, json={})})
    with pytest.raises(AuthExpired):
        await c.get_profile()


async def test_no_session_is_auth_expired():
    with pytest.raises(AuthExpired):
        await AngelClient(api_key="key", jwt=None, transport=transport({})).get_profile()


async def test_rate_limit_403_and_429():
    c = make({"getAllHolding": lambda r: httpx.Response(403, text="Access denied because of exceeding access rate")})
    with pytest.raises(RateLimited):
        await c.get_all_holding()
    c = make({"getAllHolding": lambda r: httpx.Response(429, headers={"Retry-After": "3"}, json={})})
    with pytest.raises(RateLimited) as ei:
        await c.get_all_holding()
    assert ei.value.retry_after == 3.0


async def test_server_error_retried_once_then_unavailable():
    calls = []
    c = make({"getAllHolding": lambda r: httpx.Response(503, json={})}, calls)
    with pytest.raises(Unavailable):
        await c.get_all_holding()
    assert len(calls) == 2  # one bounded retry, no more


async def test_auth_error_not_retried():
    calls = []
    c = make({"getAllHolding": {"status": False, "message": "x", "errorcode": "AG8002", "data": None}}, calls)
    with pytest.raises(AuthExpired):
        await c.get_all_holding()
    assert len(calls) == 1


async def test_holdings_data_must_be_object():
    c = make({"getAllHolding": ok(None)})
    with pytest.raises(BadResponse):
        await c.get_all_holding()


async def test_quotes_batched_and_unfetched_surfaced():
    seen = []

    def quote(request):
        import json
        body = json.loads(request.content)
        toks = body["exchangeTokens"]["NSE"]
        seen.append(len(toks))
        return httpx.Response(200, json=ok({"fetched": [{"symbolToken": t} for t in toks[:-1]], "unfetched": [{"symbolToken": toks[-1]}]}))

    c = make({"market/v1/quote": quote})
    res = await c.get_quotes({"NSE": [str(i) for i in range(120)]})
    assert seen == [50, 50, 20]
    assert len(res["unfetched"]) == 3 and len(res["fetched"]) == 117
    with pytest.raises(ValueError):
        await c.get_quotes({"NSE": ["1"]}, mode="BOGUS")


async def test_login_requires_tokens_and_stores_none(caplog):
    c = make({"loginByPassword": ok({"jwtToken": "j", "refreshToken": "r"})}, jwt=None)
    with pytest.raises(BadResponse):
        await c.login("A123", "1234", "654321")
    c = make({"loginByPassword": ok({"jwtToken": "j", "refreshToken": "r", "feedToken": "f"})}, jwt=None)
    assert (await c.login("A123", "1234", "654321"))["jwt"] == "j"


async def test_errors_and_logs_never_contain_secrets(caplog):
    caplog.set_level(logging.DEBUG)
    c = make({"loginByPassword": {"status": False, "message": "Invalid totp for A123 pin 9876", "errorcode": "AB1050", "data": None}}, jwt=None)
    with pytest.raises(AngelError) as ei:
        await c.login("A123", "9876", "111222")
    text = str(ei.value) + caplog.text
    for secret in ("A123", "9876", "111222", SECRET_JWT):
        assert secret not in text


def test_proxy_setting_validated_and_applied(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "angel_proxy_url", "ftp://nope")
    with pytest.raises(Unavailable):
        AngelClient(api_key="k", jwt="j")
    monkeypatch.setattr(settings, "angel_proxy_url", "socks5://127.0.0.1:1")
    c = AngelClient(api_key="k", jwt="j")  # constructs with a SOCKS proxy (needs httpx[socks])
    assert c._http._mounts  # proxy mounts present
    assert c._http.trust_env is False


async def test_dead_proxy_fails_closed_never_direct(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "angel_proxy_url", "socks5://127.0.0.1:1")  # nothing listens on port 1
    c = AngelClient(api_key="k", jwt="j")
    with pytest.raises(Unavailable):
        await c.get_profile()
