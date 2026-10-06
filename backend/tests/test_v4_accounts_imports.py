"""Phase 01: source accounts, real CSV/manual import, idempotency, identity."""

import io
from decimal import Decimal

from app.core.single_user import SINGLE_USER_ID
from app.models.holdings import HoldingPosition, HoldingsSnapshot
from app.models.market import Instrument
from app.models.user import User
from app.portfolio_intelligence.normalization.identity import is_valid_isin
from app.utils.time import utcnow

RELIANCE_ISIN = "INE002A01018"  # valid checksum
TCS_ISIN = "INE467B01029"


async def _seed(db_session):
    db_session.add(User(id=SINGLE_USER_ID, email="user@local", full_name="User", hashed_password="x"))
    db_session.add(Instrument(symbol="RELIANCE", name="Reliance", exchange="NSE", isin=RELIANCE_ISIN))
    await db_session.commit()


async def _account(client, label="Angel-like", source_type="manual"):
    r = await client.post("/api/v4/accounts", json={"label": label, "source_type": source_type})
    assert r.status_code == 201, r.text
    return r.json()


def _row(**kw):
    base = {"asset_type": "listed_equity", "isin": RELIANCE_ISIN, "units": "10", "value": "25000.50",
            "valuation_date": "2026-09-01"}
    base.update(kw)
    return base


def _csv(*lines):
    header = "asset_type,isin,symbol,description,units,value,valuation_date\n"
    return ("holdings.csv", io.BytesIO((header + "\n".join(lines) + "\n").encode()), "text/csv")


def test_isin_checksum():
    assert is_valid_isin(RELIANCE_ISIN)
    assert not is_valid_isin("INE002A01019")
    assert not is_valid_isin("nope")


async def test_broker_account_not_creatable(client, db_session):
    await _seed(db_session)
    r = await client.post("/api/v4/accounts", json={"label": "x", "source_type": "angel_one"})
    assert r.status_code == 422


async def test_duplicate_label_and_stale_version(client, db_session):
    await _seed(db_session)
    a = await _account(client, "A")
    dup = await client.post("/api/v4/accounts", json={"label": "A"})
    assert dup.status_code == 409
    ok = await client.put(f"/api/v4/accounts/{a['id']}", json={"expected_version": 1, "included": False})
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = await client.put(f"/api/v4/accounts/{a['id']}", json={"expected_version": 1, "included": True})
    assert stale.status_code == 409


async def test_two_accounts_coexist_across_alternating_imports(client, db_session):
    await _seed(db_session)
    a = await _account(client, "A")
    b = await _account(client, "B")

    async def confirm(acct, key, rows):
        r = await client.post(
            "/api/v4/imports/manual/confirm",
            json={"account_id": acct["id"], "rows": rows, "idempotency_key": key},
        )
        assert r.status_code == 200, r.text
        return r.json()

    await confirm(a, "a1", [_row(units="10")])
    await confirm(b, "b1", [{"asset_type": "gold", "description": "SGB", "value": "50000", "valuation_date": "2026-09-01"}])
    await confirm(a, "a2", [_row(units="20"), _row(isin=None, symbol="TCS", asset_type="listed_equity", units="1")])

    pa = (await client.get(f"/api/v4/accounts/{a['id']}/positions")).json()
    pb = (await client.get(f"/api/v4/accounts/{b['id']}/positions")).json()
    assert len(pa["positions"]) == 2 and Decimal(pa["positions"][0]["units"]) == 20  # a2 replaced a1
    assert len(pb["positions"]) == 1 and pb["positions"][0]["asset_type"] == "gold"  # untouched


async def test_idempotency_same_and_different_payload(client, db_session):
    await _seed(db_session)
    a = await _account(client)
    body = {"account_id": a["id"], "rows": [_row()], "idempotency_key": "k1"}
    first = await client.post("/api/v4/imports/manual/confirm", json=body)
    again = await client.post("/api/v4/imports/manual/confirm", json=body)
    assert first.json()["id"] == again.json()["id"]
    assert first.json()["replayed"] is False and again.json()["replayed"] is True
    changed = await client.post(
        "/api/v4/imports/manual/confirm", json={**body, "rows": [_row(units="11")]}
    )
    assert changed.status_code == 409
    # the earlier complete import is still the current one
    pos = (await client.get(f"/api/v4/accounts/{a['id']}/positions")).json()
    assert Decimal(pos["positions"][0]["units"]) == 10


async def test_row_errors_block_confirm_and_are_all_reported(client, db_session):
    await _seed(db_session)
    a = await _account(client)
    rows = [
        _row(valuation_date="01/09/2026"),
        _row(value="-5"),
        _row(units="0"),
        _row(value="NaN"),
        {"asset_type": "bogus", "valuation_date": "2026-09-01"},
    ]
    prev = (await client.post("/api/v4/imports/manual/preview", json={"account_id": a["id"], "rows": rows})).json()
    assert not prev["can_confirm"]
    bad_rows = {e["row"] for e in prev["errors"]}
    assert bad_rows == {1, 2, 3, 4, 5}
    conf = await client.post(
        "/api/v4/imports/manual/confirm", json={"account_id": a["id"], "rows": rows, "idempotency_key": "k"}
    )
    assert conf.status_code == 422
    assert (await client.get(f"/api/v4/accounts/{a['id']}/positions")).json()["positions"] == []


async def test_identity_resolution_and_unknowns_kept(client, db_session):
    await _seed(db_session)
    a = await _account(client)
    rows = [
        _row(),                                        # resolved via ISIN
        _row(isin=TCS_ISIN),                           # valid ISIN, not in universe
        _row(isin=None, symbol="RELIANCE"),            # symbol only -> ambiguous
        _row(isin="INE002A01019"),                     # bad checksum
        {"asset_type": "gold", "description": "coin", "units": "3", "valuation_date": "2026-09-01"},  # no value: unknown
    ]
    r = await client.post(
        "/api/v4/imports/manual/confirm", json={"account_id": a["id"], "rows": rows, "idempotency_key": "k"}
    )
    assert r.status_code == 200, r.text
    pos = r.json()["positions"]
    assert [p["resolution"] for p in pos] == ["resolved", "unresolved", "ambiguous", "unresolved", "not_applicable"]
    assert pos[3]["resolution_note"] == "invalid_isin"
    assert pos[4]["value"] is None  # unknown stays null, not 0
    assert pos[0]["cost_basis"] is None  # never synthesized


async def test_duplicate_rows_need_acknowledgement(client, db_session):
    await _seed(db_session)
    a = await _account(client)
    rows = [_row(), _row(units="5")]
    prev = (await client.post("/api/v4/imports/manual/preview", json={"account_id": a["id"], "rows": rows})).json()
    assert prev["conflicts"][0]["kind"] == "duplicate_within_batch" and prev["can_confirm"]
    body = {"account_id": a["id"], "rows": rows, "idempotency_key": "k"}
    assert (await client.post("/api/v4/imports/manual/confirm", json=body)).status_code == 422
    ok = await client.post("/api/v4/imports/manual/confirm", json={**body, "acknowledge_conflicts": True})
    assert ok.status_code == 200 and ok.json()["row_count"] == 2


async def test_csv_upload_preview_and_confirm(client, db_session):
    await _seed(db_session)
    a = await _account(client, "CSV", "csv")
    f = _csv(f"listed_equity,{RELIANCE_ISIN},,,10,25000,2026-09-01", "deposit,,,FD SBI,,100000,2026-09-01")
    prev = await client.post("/api/v4/imports/csv/preview", data={"account_id": a["id"]}, files={"file": f})
    assert prev.status_code == 200, prev.text
    assert prev.json()["can_confirm"] and prev.json()["row_count"] == 2
    f2 = _csv(f"listed_equity,{RELIANCE_ISIN},,,10,25000,2026-09-01", "deposit,,,FD SBI,,100000,2026-09-01")
    conf = await client.post(
        "/api/v4/imports/csv/confirm", data={"account_id": a["id"], "idempotency_key": "c1"}, files={"file": f2}
    )
    assert conf.status_code == 200, conf.text
    assert conf.json()["content_hash"] == prev.json()["content_hash"]


async def test_csv_rejects_bad_files(client, db_session):
    await _seed(db_session)
    a = await _account(client, "CSV", "csv")

    async def post(name, content):
        return await client.post(
            "/api/v4/imports/csv/preview", data={"account_id": a["id"]}, files={"file": (name, io.BytesIO(content), "text/csv")}
        )

    assert (await post("x.csv", b"")).status_code == 422
    assert (await post("x.csv", b"foo,bar\n1,2\n")).status_code == 422  # unknown/missing columns
    assert (await post("x.csv", b"asset_type,asset_type,valuation_date\n")).status_code == 422  # duplicate header
    assert (await post("x.csv", b"\xff\xfe\x00bad")).status_code == 422  # not utf-8
    assert (await post("x.csv", b"a" * 1_000_001)).status_code == 422  # too large


async def test_coverage_attestation_append_only_with_version(client, db_session):
    await _seed(db_session)
    g = (await client.get("/api/v4/account-coverage")).json()
    assert g["status"] == "unknown" and g["version"] == 0
    r = await client.put(
        "/api/v4/account-coverage",
        json={"expected_version": 0, "status": "partial", "missing_account_types": ["mutual_fund"]},
    )
    assert r.status_code == 200 and r.json()["version"] == 1
    stale = await client.put("/api/v4/account-coverage", json={"expected_version": 0, "status": "complete"})
    assert stale.status_code == 409
    bad = await client.put(
        "/api/v4/account-coverage",
        json={"expected_version": 1, "status": "complete", "missing_account_types": ["ppf"]},
    )
    assert bad.status_code == 422


async def test_legacy_snapshot_adoption_once_and_legacy_unchanged(client, db_session):
    await _seed(db_session)
    snap = HoldingsSnapshot(user_id=SINGLE_USER_ID, source="manual", idempotency_key="legacy-1", created_at=utcnow())
    db_session.add(snap)
    await db_session.flush()
    from datetime import date
    from decimal import Decimal
    db_session.add(
        HoldingPosition(
            snapshot_id=snap.id, raw_identifier_text="Old FD", amount=Decimal("1000"), valuation_date=date(2026, 8, 1),
            valuation_source="manual", ownership="sole", identification_confidence="unresolved",
        )
    )
    await db_session.commit()

    a = await _account(client, "Legacy")
    r = await client.post(f"/api/v4/accounts/{a['id']}/adopt-legacy-snapshot", json={"snapshot_id": str(snap.id)})
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["positions"][0]["value"]) == 1000
    again = await client.post(f"/api/v4/accounts/{a['id']}/adopt-legacy-snapshot", json={"snapshot_id": str(snap.id)})
    assert again.status_code == 409
    legacy = await client.get("/api/holdings/latest")
    assert legacy.status_code == 200 and len(legacy.json()["positions"]) == 1


async def _catalogue(db_session, *rows):
    from app.models.securities import Security

    now = utcnow()
    for sym, kind, isin, name in rows:
        db_session.add(Security(source_key=f"t:{sym}:{kind}:{isin}", kind=kind, symbol=sym, isin=isin, name=name, series="EQ",
                                source="test", is_active=True, seen_at=now))
    await db_session.commit()


async def test_symbol_only_row_is_completed_from_the_catalogue_when_exactly_one_matches(client, db_session):
    await _seed(db_session)
    await _catalogue(db_session, ("NIFTYBEES", "etf", "INF204KB14I2", "Nippon India ETF Nifty 50 BeES"))
    a = await _account(client)
    rows = [_row(isin=None, symbol="NIFTYBEES"), _row(isin=None, symbol="RELIANCE")]
    prev = (await client.post("/api/v4/imports/manual/preview", json={"account_id": a["id"], "rows": rows})).json()
    by = {"NIFTYBEES": prev["rows"][0], "RELIANCE": prev["rows"][1]}
    assert prev["can_confirm"] and len(prev["rows"]) == 2
    assert "Nippon India ETF" in by["NIFTYBEES"]["resolution_note"] and "check that is what you hold" in by["NIFTYBEES"]["resolution_note"]
    assert by["NIFTYBEES"]["resolution"] == "unresolved"       # real ISIN, but not in the old Nifty 50 table: said honestly, not "resolved"
    assert "market catalogue" in by["NIFTYBEES"]["resolution_note"]
    # preview and confirm hash the same content, so the idempotency key still replays
    body = {"account_id": a["id"], "rows": rows, "idempotency_key": "k1"}
    first = await client.post("/api/v4/imports/manual/confirm", json=body)
    again = await client.post("/api/v4/imports/manual/confirm", json=body)
    assert first.status_code in (200, 201) and again.json()["id"] == first.json()["id"] and again.json()["replayed"] is True
    positions = {p["raw_identifier"]: p for p in first.json()["positions"]}
    assert positions["INF204KB14I2"]["resolution"] == "unresolved"   # stored identifier is the catalogue ISIN


async def test_ambiguous_symbol_is_never_guessed(client, db_session):
    await _seed(db_session)
    await _catalogue(db_session, ("DUP", "stock", "INE000A01010", "Dup One Limited"), ("DUP", "etf", "INF000A01012", "Dup ETF"))
    a = await _account(client)
    prev = (await client.post("/api/v4/imports/manual/preview", json={"account_id": a["id"], "rows": [_row(isin=None, symbol="DUP")]})).json()
    row = prev["rows"][0]
    assert row["raw_identifier"] == "DUP" and row["resolution"] == "unresolved"


async def test_preview_reconciles_against_the_latest_import_and_names_goal_claims(client, db_session):
    await _seed(db_session)
    a = await _account(client)
    first = [_row(units="10", value="25000"), _row(isin=TCS_ISIN, units="2", value="7000")]
    pv = (await client.post("/api/v4/imports/manual/preview", json={"account_id": a["id"], "rows": first})).json()
    assert pv["reconcile"]["previous_import_at"] is None and len(pv["reconcile"]["added"]) == 2
    r = await client.post("/api/v4/imports/manual/confirm", json={"account_id": a["id"], "rows": first, "idempotency_key": "r1"})
    assert r.status_code in (200, 201)

    # replacement: RELIANCE units change, TCS disappears, a new gold row appears
    second = [_row(units="12", value="30000"), {"asset_type": "gold", "description": "SGB", "value": "50000", "valuation_date": "2026-09-01"}]
    rec = (await client.post("/api/v4/imports/manual/preview", json={"account_id": a["id"], "rows": second})).json()["reconcile"]
    assert rec["previous_row_count"] == 2 and rec["unchanged"] == 0
    assert [c["identifier"] for c in rec["added"]] == ["SGB"]
    assert [c["identifier"] for c in rec["removed"]] == [TCS_ISIN]
    ch = rec["changed"][0]
    assert ch["before_units"] == "10" and ch["after_units"] == "12"

    same = (await client.post("/api/v4/imports/manual/preview", json={"account_id": a["id"], "rows": first})).json()["reconcile"]
    assert same["unchanged"] == 2 and not same["added"] and not same["removed"] and not same["changed"]
