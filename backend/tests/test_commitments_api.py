"""Coverage for /api/commitments (V3 Phase 03) -- budget_interpretation must
be explicit, never silently defaulted."""

from app.core.single_user import SINGLE_USER_ID
from app.models.user import User


async def _seed_user(db_session):
    db_session.add(User(id=SINGLE_USER_ID, email="user@local", full_name="User", hashed_password="unused"))
    await db_session.flush()


def _commitment_payload(**overrides):
    payload = {
        "amount": "5000.00",
        "frequency": "monthly",
        "start_date": "2026-09-01",
        "contribution_timing": "start_of_period",
        "status": "active",
        "source": "existing_user_reported",
        "budget_interpretation": "additional_to_existing_commitments",
    }
    payload.update(overrides)
    return payload


async def test_create_commitment_with_explicit_budget_interpretation(client, db_session):
    await _seed_user(db_session)
    await db_session.commit()

    resp = await client.post("/api/commitments", json=_commitment_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["budget_interpretation"] == "additional_to_existing_commitments"


async def test_missing_budget_interpretation_is_rejected(client, db_session):
    await _seed_user(db_session)
    await db_session.commit()

    payload = _commitment_payload()
    del payload["budget_interpretation"]

    resp = await client.post("/api/commitments", json=payload)
    assert resp.status_code == 422


async def test_null_budget_interpretation_is_rejected(client, db_session):
    await _seed_user(db_session)
    await db_session.commit()

    payload = _commitment_payload(budget_interpretation=None)
    resp = await client.post("/api/commitments", json=payload)
    assert resp.status_code == 422


async def test_list_commitments(client, db_session):
    await _seed_user(db_session)
    await db_session.commit()

    await client.post("/api/commitments", json=_commitment_payload())
    await client.post("/api/commitments", json=_commitment_payload(frequency="quarterly", amount="15000.00"))

    resp = await client.get("/api/commitments")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
