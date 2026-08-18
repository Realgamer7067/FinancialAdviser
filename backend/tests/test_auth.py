"""Integration tests for the auth flow (Phase 5) -- previously zero coverage
existed for signup/login/token validation/rate limiting."""

from datetime import datetime, timedelta, timezone

from jose import jwt

from app.api.auth import _RATE_LIMIT_MAX_ATTEMPTS
from app.core.config import settings
from app.core.security import ALGORITHM

SIGNUP_PAYLOAD = {"email": "trader@example.com", "password": "correct-horse-battery-staple", "full_name": "Trader"}


async def test_signup_returns_token(client):
    res = await client.post("/api/auth/signup", json=SIGNUP_PAYLOAD)
    assert res.status_code == 201
    assert res.json()["token_type"] == "bearer"
    assert res.json()["access_token"]


async def test_signup_duplicate_email_rejected(client):
    await client.post("/api/auth/signup", json=SIGNUP_PAYLOAD)
    res = await client.post("/api/auth/signup", json=SIGNUP_PAYLOAD)
    assert res.status_code == 409


async def test_login_with_correct_password_succeeds(client):
    await client.post("/api/auth/signup", json=SIGNUP_PAYLOAD)
    res = await client.post(
        "/api/auth/login",
        data={"username": SIGNUP_PAYLOAD["email"], "password": SIGNUP_PAYLOAD["password"]},
    )
    assert res.status_code == 200
    assert res.json()["access_token"]


async def test_login_with_wrong_password_rejected(client):
    await client.post("/api/auth/signup", json=SIGNUP_PAYLOAD)
    res = await client.post(
        "/api/auth/login", data={"username": SIGNUP_PAYLOAD["email"], "password": "wrong-password"}
    )
    assert res.status_code == 401


async def test_login_unknown_email_rejected(client):
    res = await client.post("/api/auth/login", data={"username": "nobody@example.com", "password": "whatever"})
    assert res.status_code == 401


async def test_protected_route_rejects_missing_token(client):
    res = await client.get("/api/dashboard")
    assert res.status_code == 401


async def test_protected_route_rejects_malformed_token(client):
    res = await client.get("/api/dashboard", headers={"Authorization": "Bearer not-a-real-token"})
    assert res.status_code == 401


async def test_protected_route_rejects_expired_token(client):
    expired = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.secret_key,
        algorithm=ALGORITHM,
    )
    res = await client.get("/api/dashboard", headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401


async def test_protected_route_accepts_valid_token(client):
    signup_res = await client.post("/api/auth/signup", json=SIGNUP_PAYLOAD)
    token = signup_res.json()["access_token"]
    res = await client.get("/api/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200


async def test_login_rate_limited_after_threshold(client):
    for _ in range(_RATE_LIMIT_MAX_ATTEMPTS):
        await client.post("/api/auth/login", data={"username": "x@example.com", "password": "wrong"})
    res = await client.post("/api/auth/login", data={"username": "x@example.com", "password": "wrong"})
    assert res.status_code == 429
