"""Coverage for /api/goals* (V3 Phase 03) -- versioned edits and earmark
over-allocation enforcement."""

from datetime import date
from decimal import Decimal

from app.core.single_user import SINGLE_USER_ID
from app.models.holdings import HoldingPosition, HoldingsSnapshot
from app.models.user import User
from app.utils.time import utcnow


async def _seed_user(db_session):
    db_session.add(User(id=SINGLE_USER_ID, email="user@local", full_name="User", hashed_password="unused"))
    await db_session.flush()


async def _seed_holding_position(db_session, amount="10000.00") -> str:
    snapshot = HoldingsSnapshot(
        user_id=SINGLE_USER_ID, source="manual", idempotency_key=f"seed-{amount}", created_at=utcnow()
    )
    db_session.add(snapshot)
    await db_session.flush()
    position = HoldingPosition(
        snapshot_id=snapshot.id,
        raw_identifier_text="RELIANCE",
        amount=amount,
        valuation_date=date(2026, 9, 1),
        valuation_source="manual",
        ownership="sole",
        identification_confidence="low",
    )
    db_session.add(position)
    await db_session.flush()
    return str(position.id)


def _goal_payload(**overrides):
    payload = {
        "description": "Retirement corpus",
        "target_amount": "5000000.00",
        "target_basis": "future_money",
        "target_date": "2050-01-01",
        "priority": 1,
        "flexibility": "flexible",
    }
    payload.update(overrides)
    return payload


async def test_create_goal(client, db_session):
    await _seed_user(db_session)
    await db_session.commit()

    resp = await client.post("/api/goals", json=_goal_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 1
    assert body["superseded_at"] is None
    assert body["earmarked_total"] == "0"


async def test_goal_edit_creates_new_version_and_supersedes_old(client, db_session):
    await _seed_user(db_session)
    await db_session.commit()

    created = (await client.post("/api/goals", json=_goal_payload())).json()
    goal_id = created["id"]

    edited_resp = await client.put(
        f"/api/goals/{goal_id}", json=_goal_payload(description="Retirement corpus (revised)")
    )
    assert edited_resp.status_code == 200
    edited = edited_resp.json()
    assert edited["version"] == 2
    assert edited["id"] != goal_id
    assert edited["description"] == "Retirement corpus (revised)"

    listing = (await client.get("/api/goals")).json()
    ids = [g["id"] for g in listing]
    assert goal_id not in ids
    assert edited["id"] in ids
    assert len(listing) == 1


async def test_valid_partial_earmark_succeeds(client, db_session):
    await _seed_user(db_session)
    position_id = await _seed_holding_position(db_session, amount="10000.00")
    await db_session.commit()

    goal = (await client.post("/api/goals", json=_goal_payload(target_amount="20000.00"))).json()

    resp = await client.post(
        f"/api/goals/{goal['id']}/earmarks", json={"holding_position_id": position_id, "amount": "4000.00"}
    )
    assert resp.status_code == 200

    listing = (await client.get("/api/goals")).json()
    # SQLite's generic Numeric type (no explicit scale) round-trips with a
    # padded decimal_return_scale (e.g. "4000.0000000000") -- compare by
    # Decimal VALUE, not string formatting; no precision is actually lost.
    assert Decimal(listing[0]["earmarked_total"]) == Decimal("4000.00")
    assert Decimal(listing[0]["remaining_unearmarked_target"]) == Decimal("16000.00")


async def test_double_earmark_exceeding_holding_amount_is_rejected(client, db_session):
    await _seed_user(db_session)
    position_id = await _seed_holding_position(db_session, amount="10000.00")
    await db_session.commit()

    goal_a = (await client.post("/api/goals", json=_goal_payload(description="Goal A"))).json()
    goal_b = (await client.post("/api/goals", json=_goal_payload(description="Goal B"))).json()

    first = await client.post(
        f"/api/goals/{goal_a['id']}/earmarks", json={"holding_position_id": position_id, "amount": "7000.00"}
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/goals/{goal_b['id']}/earmarks", json={"holding_position_id": position_id, "amount": "5000.00"}
    )
    assert second.status_code == 422
    assert "exceed" in second.json()["detail"].lower()
