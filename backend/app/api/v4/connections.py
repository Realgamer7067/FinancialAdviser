"""Angel connection status, account sync and job polling (Portfolio
Intelligence Engine Phase 02). There is deliberately NO endpoint that starts or
completes a broker login: the session is established by the operator CLI
(app.portfolio_intelligence.sources.angel.setup). These routes only report
status and enqueue a typed sync job; they never see or return tokens."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v4.accounts import get_owned_account
from app.core.config import settings
from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.accounts import SourceAccount, SourceImport
from app.models.portfolio_jobs import PortfolioJob
from app.portfolio_intelligence.sources.angel.token_store import load_session
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-connections"])

SETUP_HINT = "Run in your own terminal: python -m app.portfolio_intelligence.sources.angel.setup connect"


class AngelAccountStatus(BaseModel):
    id: uuid.UUID
    label: str
    masked_external_id: str | None
    status: str
    last_sync_at: datetime | None
    last_error: str | None


class AngelStatusOut(BaseModel):
    api_key_configured: bool
    fingerprint_key_configured: bool
    session: str  # "connected" | "reconnect_required" | "not_connected"
    session_expires_at: datetime | None
    accounts: list[AngelAccountStatus]
    reconnect_instructions: str | None


@router.get("/connections/angel/status", response_model=AngelStatusOut)
async def angel_status(db: AsyncSession = Depends(get_db)):
    accounts = (
        (await db.execute(select(SourceAccount).where(
            SourceAccount.user_id == SINGLE_USER_ID, SourceAccount.source_type == "angel_one")
            .order_by(SourceAccount.created_at)))
        .scalars().all()
    )
    sess = load_session()
    if sess is not None:
        state = "connected"
    elif accounts:
        state = "reconnect_required"
    else:
        state = "not_connected"
    return AngelStatusOut(
        api_key_configured=bool(settings.angel_api_key),
        fingerprint_key_configured=bool(settings.angel_fingerprint_key),
        session=state,
        session_expires_at=sess.expires_at if sess else None,
        accounts=[AngelAccountStatus(id=a.id, label=a.label, masked_external_id=a.masked_external_id,
                                     status=a.status, last_sync_at=a.last_sync_at, last_error=a.last_error)
                  for a in accounts],
        reconnect_instructions=None if state == "connected" else SETUP_HINT,
    )


class FundsOut(BaseModel):
    available: str | None            # rupees Angel reports as available cash, or null when it is unknown
    as_of: datetime | None           # when the figure was read from Angel
    age_minutes: int | None
    account_id: uuid.UUID | None
    account_label: str | None
    fields: dict[str, str]           # the raw fields Angel returned, shown as received
    stale: bool
    note: str


@router.get("/connections/angel/funds", response_model=FundsOut)
async def angel_funds(db: AsyncSession = Depends(get_db)):
    """The cash Angel's funds report shows for the connected account, read at the last sync. It is a figure to start from, not a promise: Angel's own
    app is where the real buying power is confirmed (pending orders, margin and settlement can change it). Nothing here moves money."""
    from decimal import Decimal, InvalidOperation

    from app.models.accounts import SourceImport
    from app.utils.time import utcnow

    note = ("Angel's funds report as read at the last sync. Pending orders and settlements can change it, so confirm the buying power in the Angel One app before ordering. "
            "This app cannot see your orders.")
    acct = (await db.execute(select(SourceAccount).where(SourceAccount.user_id == SINGLE_USER_ID, SourceAccount.source_type == "angel_one", SourceAccount.included.is_(True))
                             .order_by(SourceAccount.created_at))).scalars().first()
    if acct is None:
        return FundsOut(available=None, as_of=None, age_minutes=None, account_id=None, account_label=None, fields={}, stale=True,
                        note="No Angel account is connected. " + note)
    imp = (await db.execute(select(SourceImport).where(SourceImport.account_id == acct.id, SourceImport.status == "complete", SourceImport.provider_summary.is_not(None))
                            .order_by(SourceImport.created_at.desc()).limit(1))).scalar_one_or_none()
    rms = (imp.provider_summary or {}).get("rms_raw") if imp else None
    if not isinstance(rms, dict) or rms.get("fetched") is False or "availablecash" not in rms:
        return FundsOut(available=None, as_of=None, age_minutes=None, account_id=acct.id, account_label=acct.label, fields={}, stale=True,
                        note="Angel's funds report has not been read yet; press Sync now on Holdings. " + note)
    try:
        amount = Decimal(str(rms["availablecash"]))
        available = None if not amount.is_finite() or amount < 0 else format(amount.normalize(), "f")
    except (InvalidOperation, ValueError):
        available = None
    as_of = datetime.fromisoformat(imp.provider_summary["retrieved_at"]) if imp.provider_summary.get("retrieved_at") else imp.created_at
    age = int((utcnow() - as_of).total_seconds() // 60)
    return FundsOut(available=available, as_of=as_of, age_minutes=age, account_id=acct.id, account_label=acct.label,
                    fields={k: str(v) for k, v in rms.items()}, stale=age > 24 * 60 or load_session() is None, note=note)


class SyncIn(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    account_id: uuid.UUID | None
    status: str  # queued | running | done | failed
    error_code: str | None
    error: str | None
    result_import_id: uuid.UUID | None
    result_import_status: str | None
    result_outcome_id: uuid.UUID | None = None
    created_at: datetime
    completed_at: datetime | None


async def _job_out(db: AsyncSession, job: PortfolioJob) -> JobOut:
    imp_status = None
    if job.result_import_id is not None:
        imp = await db.get(SourceImport, job.result_import_id)
        imp_status = imp.status if imp else None
    return JobOut(id=job.id, kind=job.kind, account_id=job.account_id, status=job.status,
                  error_code=job.error_code, error=job.error, result_import_id=job.result_import_id,
                  result_import_status=imp_status, result_outcome_id=job.result_outcome_id, created_at=job.created_at, completed_at=job.completed_at)


@router.post("/accounts/{account_id}/sync", response_model=JobOut, status_code=202)
async def sync_account(account_id: uuid.UUID, payload: SyncIn, db: AsyncSession = Depends(get_db)):
    account = await get_owned_account(db, account_id)
    if account.source_type != "angel_one":
        raise HTTPException(422, "only broker accounts can be synced; use imports for manual/CSV accounts")
    # Same request key => same job (idempotent), regardless of session state.
    same_key = (await db.execute(select(PortfolioJob).where(
        PortfolioJob.kind == "account_sync", PortfolioJob.account_id == account.id,
        PortfolioJob.request_key == payload.idempotency_key))).scalar_one_or_none()
    if same_key is not None:
        return await _job_out(db, same_key)
    # One active sync per account: coalesce onto it instead of stacking requests.
    active = (await db.execute(select(PortfolioJob).where(
        PortfolioJob.kind == "account_sync", PortfolioJob.account_id == account.id,
        PortfolioJob.status.in_(("queued", "running"))).limit(1))).scalar_one_or_none()
    if active is not None:
        return await _job_out(db, active)
    if load_session() is None:
        raise HTTPException(409, {"message": "reconnect_required: no valid Angel session", "instructions": SETUP_HINT})
    job = PortfolioJob(user_id=SINGLE_USER_ID, kind="account_sync", account_id=account.id,
                       request_key=payload.idempotency_key, status="queued", attempts=0, created_at=utcnow())
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        job = (await db.execute(select(PortfolioJob).where(
            PortfolioJob.kind == "account_sync", PortfolioJob.account_id == account_id,
            PortfolioJob.request_key == payload.idempotency_key))).scalar_one()
    return await _job_out(db, job)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    job = (await db.execute(select(PortfolioJob).where(
        PortfolioJob.id == job_id, PortfolioJob.user_id == SINGLE_USER_ID))).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    return await _job_out(db, job)
