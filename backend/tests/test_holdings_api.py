"""Coverage for /api/holdings/* (V3 Phase 03)."""

from app.core.single_user import SINGLE_USER_ID
from app.models.market import Instrument
from app.models.user import User


async def _seed_user(db_session):
    db_session.add(User(id=SINGLE_USER_ID, email="user@local", full_name="User", hashed_password="unused"))
    await db_session.flush()


async def _seed_instrument(db_session, symbol="RELIANCE") -> str:
    instrument = Instrument(symbol=symbol, name=symbol, exchange="NSE")
    db_session.add(instrument)
    await db_session.flush()
    return str(instrument.id)


async def test_preview_flags_duplicate_within_batch(client, db_session):
    await _seed_user(db_session)
    await db_session.commit()

    rows = [
        {
            "raw_identifier_text": "RELIANCE",
            "amount": "1000.00",
            "valuation_date": "2026-09-01",
            "valuation_source": "manual",
            "ownership": "sole",
        },
        {
            "raw_identifier_text": "RELIANCE",
            "amount": "500.00",
            "valuation_date": "2026-09-01",
            "valuation_source": "manual",
            "ownership": "sole",
        },
    ]
    resp = await client.post("/api/holdings/import/preview", json={"rows": rows})
    assert resp.status_code == 200
    body = resp.json()
    reasons = {d["reason"] for d in body["duplicate_candidates"]}
    assert "duplicate_within_batch" in reasons
    # Neither row has an instrument_id, so both should be flagged unresolved too.
    assert len(body["unresolved_identifiers"]) == 2


async def test_preview_flags_duplicate_against_existing_snapshot(client, db_session):
    await _seed_user(db_session)
    await db_session.commit()

    confirm_resp = await client.post(
        "/api/holdings/import/confirm",
        json={
            "idempotency_key": "batch-1",
            "source": "manual",
            "rows": [
                {
                    "raw_identifier_text": "TCS",
                    "amount": "2000.00",
                    "valuation_date": "2026-09-01",
                    "valuation_source": "manual",
                    "ownership": "sole",
                }
            ],
        },
    )
    assert confirm_resp.status_code == 200

    preview_resp = await client.post(
        "/api/holdings/import/preview",
        json={
            "rows": [
                {
                    "raw_identifier_text": "TCS",
                    "amount": "2500.00",
                    "valuation_date": "2026-09-05",
                    "valuation_source": "manual",
                    "ownership": "sole",
                }
            ]
        },
    )
    assert preview_resp.status_code == 200
    body = preview_resp.json()
    assert any(d["reason"] == "matches_existing_snapshot" for d in body["duplicate_candidates"])


async def test_preview_flags_unresolved_identifier(client, db_session):
    await _seed_user(db_session)
    instrument_id = await _seed_instrument(db_session)
    await db_session.commit()

    resp = await client.post(
        "/api/holdings/import/preview",
        json={
            "rows": [
                {
                    "raw_identifier_text": "RELIANCE",
                    "instrument_id": instrument_id,
                    "amount": "1000.00",
                    "valuation_date": "2026-09-01",
                    "valuation_source": "manual",
                    "ownership": "sole",
                },
                {
                    "raw_identifier_text": "UNKNOWN_TICKER",
                    "amount": "300.00",
                    "valuation_date": "2026-09-01",
                    "valuation_source": "manual",
                    "ownership": "sole",
                },
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    unresolved_texts = {u["raw_identifier_text"] for u in body["unresolved_identifiers"]}
    assert unresolved_texts == {"UNKNOWN_TICKER"}


async def test_stale_valuation_date_is_accepted(client, db_session):
    """A past valuation_date must be accepted, not rejected -- staleness is a
    later phase's UI/business concern, not a validation rejection here."""
    await _seed_user(db_session)
    await db_session.commit()

    resp = await client.post(
        "/api/holdings/import/confirm",
        json={
            "idempotency_key": "stale-1",
            "source": "manual",
            "rows": [
                {
                    "raw_identifier_text": "OLDSTOCK",
                    "amount": "100.00",
                    "valuation_date": "2015-01-01",
                    "valuation_source": "manual",
                    "ownership": "sole",
                }
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["positions"][0]["valuation_date"] == "2015-01-01"


async def test_locked_asset_round_trips(client, db_session):
    await _seed_user(db_session)
    await db_session.commit()

    resp = await client.post(
        "/api/holdings/import/confirm",
        json={
            "idempotency_key": "locked-1",
            "source": "manual",
            "rows": [
                {
                    "raw_identifier_text": "ELSS_FUND",
                    "amount": "5000.00",
                    "valuation_date": "2026-09-01",
                    "valuation_source": "manual",
                    "ownership": "sole",
                    "locked": True,
                    "lock_reason": "ELSS 3-year lock-in",
                }
            ],
        },
    )
    assert resp.status_code == 200
    position = resp.json()["positions"][0]
    assert position["locked"] is True
    assert position["lock_reason"] == "ELSS 3-year lock-in"

    latest = await client.get("/api/holdings/latest")
    assert latest.status_code == 200
    latest_position = latest.json()["positions"][0]
    assert latest_position["locked"] is True
    assert latest_position["lock_reason"] == "ELSS 3-year lock-in"


async def test_confirm_import_twice_same_idempotency_key_returns_same_snapshot(client, db_session):
    await _seed_user(db_session)
    await db_session.commit()

    payload = {
        "idempotency_key": "idem-key-1",
        "source": "manual",
        "rows": [
            {
                "raw_identifier_text": "HDFC",
                "amount": "1500.00",
                "valuation_date": "2026-09-01",
                "valuation_source": "manual",
                "ownership": "sole",
            }
        ],
    }
    first = await client.post("/api/holdings/import/confirm", json=payload)
    second = await client.post("/api/holdings/import/confirm", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    # No duplicate snapshot was created -- confirm via count query.
    from sqlalchemy import select

    from app.models.holdings import HoldingsSnapshot

    count = len((await db_session.execute(select(HoldingsSnapshot))).scalars().all())
    assert count == 1


async def test_cost_basis_never_synthesized(client, db_session):
    """cost_basis omitted must stay None -- never derived from amount."""
    await _seed_user(db_session)
    await db_session.commit()

    resp = await client.post(
        "/api/holdings/import/confirm",
        json={
            "idempotency_key": "no-cost-basis",
            "source": "manual",
            "rows": [
                {
                    "raw_identifier_text": "INFY",
                    "amount": "999.99",
                    "valuation_date": "2026-09-01",
                    "valuation_source": "manual",
                    "ownership": "sole",
                }
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["positions"][0]["cost_basis"] is None
