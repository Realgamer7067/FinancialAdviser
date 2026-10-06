"""Preview/confirm imports into a named source account (Portfolio Intelligence
Engine Phase 01). Preview is stateless. Confirm writes one immutable
SourceImport for that account only, idempotent per (account, key): same key +
same content returns the original import; same key + different content is 409.
The account's current holdings are its latest import, so another account's
holdings are never touched."""

import uuid
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio_intelligence.goals.service import holding_key
from app.portfolio_intelligence.goals.store import latest_allocations
from app.api.v4.accounts import (
    PositionOut,
    get_owned_account,
    latest_import,
    position_out,
)
from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import PositionObservation, SourceAccount, SourceImport
from app.models.holdings import HoldingPosition, HoldingsSnapshot
from app.models.market import Instrument
from app.models.securities import Security
from app.portfolio_intelligence.state.build import safe_refresh
from app.portfolio_intelligence.normalization.identity import Resolution, resolve_identity
from app.portfolio_intelligence.sources.import_rows import (
    SCHEMA_VERSION,
    CsvError,
    ImportRow,
    RowResult,
    content_hash,
    parse_csv,
    validate_row,
    validate_rows,
)
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-imports"])

IMPORTABLE_TYPES = {"manual", "csv"}


class PreviewRowOut(BaseModel):
    ordinal: int
    asset_type: str
    raw_identifier: str | None
    units: str | None
    value: str | None
    valuation_date: date
    resolution: str
    resolution_note: str | None


class RowErrorOut(BaseModel):
    row: int
    field: str
    message: str


class ConflictOut(BaseModel):
    row: int
    kind: str
    detail: str


class ChangeOut(BaseModel):
    identifier: str
    asset_type: str
    before_units: str | None = None
    after_units: str | None = None
    before_value: str | None = None
    after_value: str | None = None
    goal_claims: int = 0          # active goal set-asides on this holding that the replacement touches


class ReconcileOut(BaseModel):
    """What replacing this account's holdings would change, against its latest complete import. Never guessed:
    a row counts as the same holding only when its ISIN or symbol matches the earlier row."""
    previous_import_at: datetime | None
    previous_row_count: int
    added: list[ChangeOut]
    removed: list[ChangeOut]
    changed: list[ChangeOut]
    unchanged: int
    goal_claims_affected: int


class PreviewOut(BaseModel):
    account_id: uuid.UUID
    row_count: int
    rows: list[PreviewRowOut]
    errors: list[RowErrorOut]
    conflicts: list[ConflictOut]
    unresolved_count: int
    content_hash: str | None
    can_confirm: bool
    reconcile: ReconcileOut | None = None


class ImportOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    created_at: datetime
    row_count: int
    content_hash: str
    replayed: bool
    positions: list[PositionOut]


class ManualPreviewIn(BaseModel):
    account_id: uuid.UUID
    rows: list[dict] = Field(max_length=2000)


class ManualConfirmIn(ManualPreviewIn):
    idempotency_key: str = Field(min_length=1, max_length=200)
    acknowledge_conflicts: bool = False


class Prepared:
    def __init__(self, account: SourceAccount, results: list[RowResult], resolutions: dict[int, Resolution]):
        self.account = account
        self.results = results
        self.resolutions = resolutions
        self.errors = [
            RowErrorOut(row=r.ordinal, field=e["field"], message=e["message"])
            for r in results
            for e in r.errors
        ]
        self.rows = [r for r in results if r.row is not None]
        self.conflicts = self._conflicts()
        self.unresolved_count = sum(
            1 for r in self.rows if resolutions[r.ordinal].status in ("unresolved", "ambiguous")
        )
        self.hash = content_hash([r.row for r in self.rows]) if not self.errors and self.rows else None  # type: ignore[misc]

    def _conflicts(self) -> list[ConflictOut]:
        seen: dict[tuple[str, str], int] = {}
        out: list[ConflictOut] = []
        for r in self.rows:
            key = r.row.dedup_key()  # type: ignore[union-attr]
            if not key[1]:
                continue
            if key in seen:
                out.append(
                    ConflictOut(
                        row=r.ordinal,
                        kind="duplicate_within_batch",
                        detail=f"same identifier as row {seen[key]}; may be separate lots or a double entry",
                    )
                )
            else:
                seen[key] = r.ordinal
        return out


async def _fill_isins_from_catalogue(db: AsyncSession, results: list[RowResult]) -> dict[int, str]:
    """A symbol typed without an ISIN is completed from the market catalogue ONLY when exactly one active stock or ETF carries that exact symbol.
    Two or more, or none, leave the row as it was. The preview names what it matched so the owner can check it before confirming."""
    want = {
        r.row.symbol.strip().upper()
        for r in results
        if r.row is not None and not r.row.isin and r.row.symbol and r.row.asset_type in ("listed_equity", "etf")
    }
    if not want:
        return {}
    found = (
        await db.execute(
            select(Security).where(
                func.upper(Security.symbol).in_(list(want)), Security.kind.in_(("stock", "etf")), Security.is_active.is_(True)
            )
        )
    ).scalars().all()
    by_symbol: dict[str, list[Security]] = {}
    for sec in found:
        if sec.isin:
            by_symbol.setdefault(sec.symbol.upper(), []).append(sec)
    filled: dict[int, str] = {}
    for r in results:
        if r.row is None or r.row.isin or not r.row.symbol:
            continue
        hits = by_symbol.get(r.row.symbol.strip().upper(), [])
        if len(hits) == 1:
            filled[r.ordinal] = f"{r.row.symbol} is {hits[0].name} ({hits[0].isin}): check that is what you hold"
            r.row = replace(r.row, isin=hits[0].isin)
    return filled


async def _explain_catalogue_matches(db: AsyncSession, results: list[RowResult], resolutions: dict[int, Resolution], filled: dict[int, str]) -> None:
    """The old Nifty 50 table is only one source of identity. An ISIN that is in the market catalogue (any stock, ETF or fund) is real; say so, rather than
    calling it unmatched, and keep the status honest: price checks work from the ISIN, the old Nifty 50 universe just does not contain it."""
    isins = {r.row.isin for r in results if r.row is not None and r.row.isin}
    names = {}
    if isins:
        names = {x.isin: x for x in (await db.execute(select(Security).where(Security.isin.in_(isins)))).scalars().all()}
    for r in results:
        if r.row is None:
            continue
        res = resolutions[r.ordinal]
        sec = names.get(r.row.isin) if r.row.isin else None
        if r.ordinal in filled:
            note = filled[r.ordinal] if res.status == "resolved" else f"{filled[r.ordinal]}; in the market catalogue, not in the old Nifty 50 list"
            resolutions[r.ordinal] = replace(res, note=note)
        elif sec is not None and res.status == "unresolved" and res.note == "isin_not_in_universe":
            resolutions[r.ordinal] = replace(res, note=f"{sec.name} is in the market catalogue; not in the old Nifty 50 list")


async def _prepare(db: AsyncSession, account_id: uuid.UUID, raw_rows: list[dict]) -> Prepared:
    account = await get_owned_account(db, account_id)
    if account.source_type not in IMPORTABLE_TYPES:
        raise HTTPException(422, "this account type cannot be imported into manually")
    try:
        results = validate_rows(raw_rows)
    except CsvError as exc:
        raise HTTPException(422, str(exc))
    instruments = (await db.execute(select(Instrument))).scalars().all()
    filled = await _fill_isins_from_catalogue(db, results)
    resolutions = {
        r.ordinal: resolve_identity(
            asset_type=r.row.asset_type,
            isin=r.row.isin,
            symbol=r.row.symbol,
            approved_instrument_id=r.row.approved_instrument_id,
            instruments=instruments,
        )
        for r in results
        if r.row is not None
    }
    await _explain_catalogue_matches(db, results, resolutions, filled)
    return Prepared(account, results, resolutions)


def _preview_out(p: Prepared) -> PreviewOut:
    rows = [
        PreviewRowOut(
            ordinal=r.ordinal,
            asset_type=r.row.asset_type,  # type: ignore[union-attr]
            raw_identifier=r.row.raw_identifier,  # type: ignore[union-attr]
            units=None if r.row.units is None else str(r.row.units),  # type: ignore[union-attr]
            value=None if r.row.value is None else str(r.row.value),  # type: ignore[union-attr]
            valuation_date=r.row.valuation_date,  # type: ignore[union-attr]
            resolution=p.resolutions[r.ordinal].status,
            resolution_note=p.resolutions[r.ordinal].note,
        )
        for r in p.rows
    ]
    return PreviewOut(
        account_id=p.account.id,
        row_count=len(p.results),
        rows=rows,
        errors=p.errors,
        conflicts=p.conflicts,
        unresolved_count=p.unresolved_count,
        content_hash=p.hash,
        can_confirm=not p.errors and bool(p.rows),
    )


async def _import_out(db: AsyncSession, imp: SourceImport, replayed: bool) -> ImportOut:
    obs = (
        (
            await db.execute(
                select(PositionObservation)
                .where(PositionObservation.import_id == imp.id)
                .order_by(PositionObservation.row_ordinal)
            )
        )
        .scalars()
        .all()
    )
    return ImportOut(
        id=imp.id,
        account_id=imp.account_id,
        created_at=imp.created_at,
        row_count=imp.row_count,
        content_hash=imp.content_hash,
        replayed=replayed,
        positions=[position_out(o) for o in obs],
    )


async def _existing_for_key(
    db: AsyncSession, account_id: uuid.UUID, key: str, new_hash: str
) -> SourceImport | None:
    existing = (
        await db.execute(
            select(SourceImport).where(
                SourceImport.account_id == account_id, SourceImport.idempotency_key == key
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.content_hash != new_hash:
        raise HTTPException(409, "idempotency key already used with different content")
    return existing


async def _confirm(
    db: AsyncSession, p: Prepared, key: str, acknowledge_conflicts: bool, legacy_snapshot_id: uuid.UUID | None = None
) -> ImportOut:
    if p.errors:
        raise HTTPException(422, {"message": "fix row errors before confirming", "errors": [e.model_dump() for e in p.errors]})
    if not p.rows or p.hash is None:
        raise HTTPException(422, "no rows to import")
    existing = await _existing_for_key(db, p.account.id, key, p.hash)
    if existing is not None:
        return await _import_out(db, existing, replayed=True)
    if p.conflicts and not acknowledge_conflicts:
        raise HTTPException(
            422,
            {
                "message": "conflicts need acknowledgement (acknowledge_conflicts=true)",
                "conflicts": [c.model_dump() for c in p.conflicts],
            },
        )

    # Plain locals only from here on: after a rollback the ORM objects are
    # expired and touching p.account would lazy-load (MissingGreenlet).
    account_id = p.account.id
    content = p.hash
    try:
        imp = SourceImport(
            account_id=account_id,
            idempotency_key=key,
            content_hash=content,
            schema_version=SCHEMA_VERSION,
            status="complete",
            row_count=len(p.rows),
            legacy_snapshot_id=legacy_snapshot_id,
            created_at=utcnow(),
        )
        db.add(imp)
        await db.flush()  # Postgres enforces uq_source_imports_account_key here
        for r in p.rows:
            row: ImportRow = r.row  # type: ignore[assignment]
            res = p.resolutions[r.ordinal]
            db.add(
                PositionObservation(
                    import_id=imp.id,
                    row_ordinal=r.ordinal,
                    asset_type=row.asset_type,
                    raw_identifier=row.raw_identifier,
                    isin=row.isin,
                    symbol=row.symbol,
                    instrument_id=res.instrument_id,
                    resolution=res.status,
                    resolution_note=res.note,
                    units=row.units,
                    value=row.value,
                    valuation_date=row.valuation_date,
                    cost_basis=row.cost_basis,  # only what was explicitly given
                    locked=row.locked,
                    ownership=row.ownership,
                )
            )
        await db.commit()
    except IntegrityError:
        # Concurrent request with the same key won the race: replay it.
        await db.rollback()
        existing = await _existing_for_key(db, account_id, key, content)
        if existing is None:
            raise HTTPException(409, "import conflicted with a concurrent request; retry")
        return await _import_out(db, existing, replayed=True)
    out = await _import_out(db, imp, replayed=False)
    await safe_refresh(db, SINGLE_USER_ID)
    return out


def _norm_num(v) -> str | None:
    return None if v is None else format(Decimal(str(v)).normalize(), "f")


def _idents(isin: str | None, symbol: str | None, raw: str | None) -> set[str]:
    return {x.strip().lower() for x in (isin, symbol, raw) if x and x.strip()}


async def _reconcile(db: AsyncSession, p: Prepared) -> ReconcileOut:
    prev = await latest_import(db, p.account.id)
    old: list[PositionObservation] = []
    if prev is not None:
        old = list((await db.execute(select(PositionObservation).where(PositionObservation.import_id == prev.id)
                                     .order_by(PositionObservation.row_ordinal))).scalars().all())
    claims: dict[str, int] = {}
    for a in await latest_allocations(db, SINGLE_USER_ID):
        if a.source_account_id == p.account.id and a.status in ("active", "needs_review"):
            claims[a.holding_key] = claims.get(a.holding_key, 0) + 1

    def claim_count(asset_type: str, ident: str) -> int:
        return claims.get(holding_key(p.account.id, asset_type, ident), 0)

    unmatched_old = list(old)
    added: list[ChangeOut] = []
    changed: list[ChangeOut] = []
    unchanged = 0
    for r in p.rows:
        row = r.row
        ids = _idents(row.isin, row.symbol, row.description)
        hit = next((o for o in unmatched_old if o.asset_type == row.asset_type and ids & _idents(o.isin, o.symbol, o.raw_identifier)), None)
        label = row.symbol or row.isin or row.description or "unnamed"
        if hit is None:
            added.append(ChangeOut(identifier=label, asset_type=row.asset_type, after_units=_norm_num(row.units), after_value=_norm_num(row.value)))
            continue
        unmatched_old.remove(hit)
        if _norm_num(hit.units) == _norm_num(row.units) and _norm_num(hit.value) == _norm_num(row.value):
            unchanged += 1
        else:
            ident = hit.isin or hit.symbol or hit.raw_identifier or ""
            changed.append(ChangeOut(identifier=label, asset_type=row.asset_type, before_units=_norm_num(hit.units), after_units=_norm_num(row.units),
                                     before_value=_norm_num(hit.value), after_value=_norm_num(row.value), goal_claims=claim_count(hit.asset_type, ident)))
    removed = [ChangeOut(identifier=o.symbol or o.isin or o.raw_identifier or "unnamed", asset_type=o.asset_type, before_units=_norm_num(o.units),
                         before_value=_norm_num(o.value), goal_claims=claim_count(o.asset_type, o.isin or o.symbol or o.raw_identifier or ""))
               for o in unmatched_old]
    return ReconcileOut(previous_import_at=prev.created_at if prev else None, previous_row_count=len(old), added=added, removed=removed,
                        changed=changed, unchanged=unchanged,
                        goal_claims_affected=sum(c.goal_claims for c in removed) + sum(c.goal_claims for c in changed))


@router.post("/imports/manual/preview", response_model=PreviewOut)
async def manual_preview(payload: ManualPreviewIn, db: AsyncSession = Depends(get_db)):
    prepared = await _prepare(db, payload.account_id, payload.rows)
    out = _preview_out(prepared)
    out.reconcile = await _reconcile(db, prepared) if not prepared.errors else None
    return out


@router.post("/imports/manual/confirm", response_model=ImportOut)
async def manual_confirm(payload: ManualConfirmIn, db: AsyncSession = Depends(get_db)):
    p = await _prepare(db, payload.account_id, payload.rows)
    return await _confirm(db, p, payload.idempotency_key, payload.acknowledge_conflicts)


async def _csv_rows(file: UploadFile) -> list[dict]:
    data = await file.read(1_000_001)
    try:
        return parse_csv(data)
    except CsvError as exc:
        raise HTTPException(422, str(exc))


@router.post("/imports/csv/preview", response_model=PreviewOut)
async def csv_preview(
    account_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    prepared = await _prepare(db, account_id, await _csv_rows(file))
    out = _preview_out(prepared)
    out.reconcile = await _reconcile(db, prepared) if not prepared.errors else None
    return out


@router.post("/imports/csv/confirm", response_model=ImportOut)
async def csv_confirm(
    account_id: uuid.UUID = Form(...),
    idempotency_key: str = Form(..., min_length=1, max_length=200),
    acknowledge_conflicts: bool = Form(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    p = await _prepare(db, account_id, await _csv_rows(file))
    return await _confirm(db, p, idempotency_key, acknowledge_conflicts)


class AdoptLegacyIn(BaseModel):
    snapshot_id: uuid.UUID


@router.post("/accounts/{account_id}/adopt-legacy-snapshot", response_model=ImportOut)
async def adopt_legacy_snapshot(
    account_id: uuid.UUID, payload: AdoptLegacyIn, db: AsyncSession = Depends(get_db)
):
    """Copies an old /api/holdings snapshot into this account as one import.
    Explicit and user-initiated only; the legacy rows are never modified and a
    snapshot can be adopted once."""
    account = await get_owned_account(db, account_id)
    if account.source_type not in IMPORTABLE_TYPES:
        raise HTTPException(422, "this account type cannot be imported into manually")
    snap = (
        await db.execute(
            select(HoldingsSnapshot).where(
                HoldingsSnapshot.id == payload.snapshot_id, HoldingsSnapshot.user_id == SINGLE_USER_ID
            )
        )
    ).scalar_one_or_none()
    if snap is None:
        raise HTTPException(404, "legacy snapshot not found")
    already = (
        await db.execute(select(SourceImport).where(SourceImport.legacy_snapshot_id == snap.id))
    ).scalar_one_or_none()
    if already is not None:
        raise HTTPException(409, "this legacy snapshot was already adopted")
    legacy = (
        (await db.execute(select(HoldingPosition).where(HoldingPosition.snapshot_id == snap.id)))
        .scalars()
        .all()
    )
    raw_rows = [
        {
            "asset_type": "unclassified",
            "symbol": lp.raw_identifier_text if lp.instrument_id is None else None,
            "description": lp.raw_identifier_text or "legacy holding",
            "units": None if lp.units is None or lp.units <= 0 else str(lp.units),
            "value": str(lp.amount),
            "valuation_date": lp.valuation_date.isoformat(),
            "cost_basis": None if lp.cost_basis is None else str(lp.cost_basis),
            "locked": lp.locked,
            "ownership": lp.ownership if lp.ownership in ("sole", "joint", "other") else "other",
            "instrument_id": None if lp.instrument_id is None else str(lp.instrument_id),
        }
        for lp in legacy
    ]
    p = await _prepare_legacy(db, account, raw_rows)
    return await _confirm(db, p, f"legacy-{snap.id}", True, legacy_snapshot_id=snap.id)


async def _prepare_legacy(db: AsyncSession, account: SourceAccount, raw_rows: list[dict]) -> Prepared:
    """Like _prepare, but maps legacy rows (which never recorded an asset type)
    to the internal 'unclassified' type and keeps any instrument the legacy
    row was already linked to."""
    results = []
    for i, raw in enumerate(raw_rows):
        r = validate_row(i + 1, {**raw, "asset_type": "other"})
        if r.row is not None:
            r = RowResult(r.ordinal, replace(r.row, asset_type="unclassified"))
        results.append(r)
    resolutions = {
        r.ordinal: Resolution("resolved", r.row.approved_instrument_id, "legacy_instrument")
        if r.row.approved_instrument_id
        else Resolution("unresolved", None, "legacy_row_without_instrument")
        for r in results
        if r.row is not None
    }
    return Prepared(account, results, resolutions)
