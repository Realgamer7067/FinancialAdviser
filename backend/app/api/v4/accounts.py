"""Source accounts and account-coverage attestation (Portfolio Intelligence
Engine Phase 01). Broker (angel_one) accounts are NOT creatable here: their
identity comes from verified operator setup, never a browser-supplied value."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import (
    AccountCoverageAttestation,
    PositionObservation,
    SourceAccount,
    SourceImport,
)
from app.portfolio_intelligence.state.build import safe_refresh
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-accounts"])

CREATABLE_TYPES = {"manual", "csv"}
COVERAGE_STATUSES = {"complete", "partial", "unknown"}


class LatestImportOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    row_count: int


class AccountOut(BaseModel):
    id: uuid.UUID
    source_type: str
    label: str
    included: bool
    status: str
    version: int
    created_at: datetime
    latest_import: LatestImportOut | None


class AccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    source_type: str = "manual"


class AccountUpdate(BaseModel):
    expected_version: int
    label: str | None = Field(default=None, min_length=1, max_length=80)
    included: bool | None = None


async def get_owned_account(db: AsyncSession, account_id: uuid.UUID) -> SourceAccount:
    account = (
        await db.execute(
            select(SourceAccount).where(
                SourceAccount.id == account_id, SourceAccount.user_id == SINGLE_USER_ID
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(404, "account not found")
    return account


async def latest_import(db: AsyncSession, account_id: uuid.UUID) -> SourceImport | None:
    return (
        await db.execute(
            select(SourceImport)
            .where(SourceImport.account_id == account_id, SourceImport.status == "complete")
            .order_by(SourceImport.created_at.desc(), SourceImport.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _to_out(db: AsyncSession, account: SourceAccount) -> AccountOut:
    imp = await latest_import(db, account.id)
    return AccountOut(
        id=account.id,
        source_type=account.source_type,
        label=account.label,
        included=account.included,
        status=account.status,
        version=account.version,
        created_at=account.created_at,
        latest_import=None
        if imp is None
        else LatestImportOut(id=imp.id, created_at=imp.created_at, row_count=imp.row_count),
    )


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    accounts = (
        (
            await db.execute(
                select(SourceAccount)
                .where(SourceAccount.user_id == SINGLE_USER_ID)
                .order_by(SourceAccount.created_at, SourceAccount.id)
            )
        )
        .scalars()
        .all()
    )
    return [await _to_out(db, a) for a in accounts]


@router.post("/accounts", response_model=AccountOut, status_code=201)
async def create_account(payload: AccountCreate, db: AsyncSession = Depends(get_db)):
    if payload.source_type not in CREATABLE_TYPES:
        raise HTTPException(
            422,
            f"source_type must be one of {sorted(CREATABLE_TYPES)}; broker accounts are set up by the operator, not created here",
        )
    label = payload.label.strip()
    if not label:
        raise HTTPException(422, "label must not be blank")
    account = SourceAccount(
        user_id=SINGLE_USER_ID,
        source_type=payload.source_type,
        label=label,
        included=True,
        status="active",
        version=1,
        created_at=utcnow(),
    )
    db.add(account)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "an account with this label already exists")
    return await _to_out(db, account)


@router.put("/accounts/{account_id}", response_model=AccountOut)
async def update_account(account_id: uuid.UUID, payload: AccountUpdate, db: AsyncSession = Depends(get_db)):
    account = await get_owned_account(db, account_id)
    if payload.expected_version != account.version:
        raise HTTPException(409, f"stale version: account is at version {account.version}")
    if payload.label is not None:
        label = payload.label.strip()
        if not label:
            raise HTTPException(422, "label must not be blank")
        account.label = label
    if payload.included is not None:
        account.included = payload.included
    account.version += 1
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "an account with this label already exists")
    out = await _to_out(db, account)
    await safe_refresh(db, SINGLE_USER_ID)  # inclusion changes the twin's inputs
    return out


class PositionOut(BaseModel):
    display_name: str | None = None
    identity: str | None = None      # "catalogue" when the ISIN is a known security though the Nifty 50 table does not list it
    security_id: uuid.UUID | None = None
    row_ordinal: int
    asset_type: str
    raw_identifier: str | None
    isin: str | None
    symbol: str | None
    instrument_id: uuid.UUID | None
    resolution: str
    resolution_note: str | None
    units: str | None
    value: str | None
    valuation_date: str
    cost_basis: str | None
    locked: bool
    ownership: str


class AccountPositionsOut(BaseModel):
    account_id: uuid.UUID
    import_id: uuid.UUID | None
    imported_at: datetime | None
    positions: list[PositionOut]


def position_out(p: PositionObservation, symbol: str | None = None, catalogue: dict[str, str] | None = None) -> PositionOut:
    def s(v):
        return None if v is None else str(v)

    from app.portfolio_intelligence.state.catalogue_identity import effective_identity

    cat = catalogue or {}
    return PositionOut(
        identity=effective_identity(p.resolution, p.isin, cat),
        security_id=uuid.UUID(cat[p.isin]) if p.isin and p.isin in cat else None,
        display_name=symbol or p.raw_identifier,
        row_ordinal=p.row_ordinal,
        asset_type=p.asset_type,
        raw_identifier=p.raw_identifier,
        isin=p.isin,
        symbol=p.symbol,
        instrument_id=p.instrument_id,
        resolution=p.resolution,
        resolution_note=p.resolution_note,
        units=s(p.units),
        value=s(p.value),
        valuation_date=p.valuation_date.isoformat(),
        cost_basis=s(p.cost_basis),
        locked=p.locked,
        ownership=p.ownership,
    )


@router.get("/accounts/{account_id}/positions", response_model=AccountPositionsOut)
async def account_positions(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Current holdings of this account = its latest complete import."""
    account = await get_owned_account(db, account_id)
    imp = await latest_import(db, account.id)
    if imp is None:
        return AccountPositionsOut(account_id=account.id, import_id=None, imported_at=None, positions=[])
    rows = (
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
    inst_ids = {r.instrument_id for r in rows if r.instrument_id}
    from app.models.market import Instrument

    symbols = {i.id: i.symbol for i in (await db.execute(select(Instrument).where(Instrument.id.in_(inst_ids)))).scalars()} if inst_ids else {}
    from app.portfolio_intelligence.state.catalogue_identity import unique_catalogue_isins

    cat = await unique_catalogue_isins(db, {r.isin for r in rows if r.isin})
    return AccountPositionsOut(
        account_id=account.id,
        import_id=imp.id,
        imported_at=imp.created_at,
        positions=[position_out(r, symbols.get(r.instrument_id), cat) for r in rows],
    )


class CoverageOut(BaseModel):
    version: int
    status: str
    missing_account_types: list[str]
    confirmed_at: datetime | None


class CoverageIn(BaseModel):
    expected_version: int
    status: str
    missing_account_types: list[str] = Field(default_factory=list, max_length=20)


async def _current_coverage(db: AsyncSession) -> AccountCoverageAttestation | None:
    return (
        await db.execute(
            select(AccountCoverageAttestation)
            .where(AccountCoverageAttestation.user_id == SINGLE_USER_ID)
            .order_by(AccountCoverageAttestation.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _coverage_out(row: AccountCoverageAttestation | None) -> CoverageOut:
    if row is None:
        return CoverageOut(version=0, status="unknown", missing_account_types=[], confirmed_at=None)
    return CoverageOut(
        version=row.version,
        status=row.status,
        missing_account_types=list(row.missing_account_types or []),
        confirmed_at=row.confirmed_at,
    )


@router.get("/account-coverage", response_model=CoverageOut)
async def get_coverage(db: AsyncSession = Depends(get_db)):
    return _coverage_out(await _current_coverage(db))


@router.put("/account-coverage", response_model=CoverageOut)
async def put_coverage(payload: CoverageIn, db: AsyncSession = Depends(get_db)):
    """Append-only: each PUT adds a new attestation version."""
    if payload.status not in COVERAGE_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(COVERAGE_STATUSES)}")
    missing = [m.strip() for m in payload.missing_account_types if m.strip()]
    if payload.status == "complete" and missing:
        raise HTTPException(422, "status 'complete' cannot list missing account types")
    current = await _current_coverage(db)
    current_version = current.version if current else 0
    if payload.expected_version != current_version:
        raise HTTPException(409, f"stale version: coverage is at version {current_version}")
    row = AccountCoverageAttestation(
        user_id=SINGLE_USER_ID,
        version=current_version + 1,
        status=payload.status,
        missing_account_types=missing,
        confirmed_at=utcnow(),
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "coverage changed concurrently; reload and retry")
    out = _coverage_out(row)
    await safe_refresh(db, SINGLE_USER_ID)
    return out
