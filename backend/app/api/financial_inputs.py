"""Financial-input API: typed holdings snapshots, goals with earmarking, and
recurring contribution instructions (V3 Phase 03,
docs/V3-IMPLEMENTATION-PLAN.md sections 5.2/5.3/5.4, 10.1/10.2).

Design principle enforced throughout (matches the rest of this codebase,
CLAUDE.md): deterministic code, no fabricated defaults. `budget_interpretation`
on a commitment and `import_hash`/`idempotency_key` on a snapshot are never
silently inferred -- see the per-endpoint docstrings below.
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.commitments import RecurringCommitment
from app.models.goals import Goal, GoalEarmark
from app.models.holdings import HoldingPosition, HoldingsSnapshot
from app.models.market import Instrument
from app.utils.time import utcnow

router = APIRouter(prefix="/api", tags=["financial-inputs"])

VALID_TARGET_BASIS = {"today_money", "future_money"}
VALID_FLEXIBILITY = {"fixed", "flexible"}
VALID_FREQUENCY = {"monthly", "quarterly", "annual"}
VALID_TIMING = {"start_of_period", "end_of_period"}
VALID_STATUS = {"active", "paused", "ended"}
VALID_COMMITMENT_SOURCE = {"existing_user_reported", "proposed"}
VALID_BUDGET_INTERPRETATION = {"includes_existing_commitments", "additional_to_existing_commitments"}


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------


class HoldingRowIn(BaseModel):
    """One row of manually-entered or already-parsed-CSV holding data. Real
    CSV file upload/parsing is out of scope for this task (follow-up) -- this
    endpoint accepts already-structured JSON rows."""

    raw_identifier_text: str | None = None
    instrument_id: uuid.UUID | None = None
    account_label: str | None = None
    units: Decimal | None = None
    amount: Decimal
    valuation_date: date
    valuation_source: str
    cost_basis: Decimal | None = None
    locked: bool = False
    lock_reason: str | None = None
    ownership: str = "sole"
    include_in_planning: bool = True

    @field_validator("amount")
    @classmethod
    def _amount_non_negative(cls, v: Decimal) -> Decimal:
        if v < 0 or not v.is_finite():
            raise ValueError("amount must be a finite, non-negative Decimal")
        return v


class HoldingsPreviewRequest(BaseModel):
    rows: list[HoldingRowIn]


class DuplicateCandidate(BaseModel):
    row_index: int
    raw_identifier_text: str | None
    reason: str  # "duplicate_within_batch" | "matches_existing_snapshot"


class UnresolvedIdentifier(BaseModel):
    row_index: int
    raw_identifier_text: str | None


class HoldingsPreviewResponse(BaseModel):
    rows: list[HoldingRowIn]
    duplicate_candidates: list[DuplicateCandidate]
    unresolved_identifiers: list[UnresolvedIdentifier]


async def _latest_snapshot_positions(db: AsyncSession, user_id: uuid.UUID) -> list[HoldingPosition]:
    """Positions belonging to the user's newest snapshot (by created_at) --
    used both by the preview duplicate-check and by GET /holdings/latest."""
    latest = (
        await db.execute(
            select(HoldingsSnapshot)
            .where(HoldingsSnapshot.user_id == user_id)
            .order_by(HoldingsSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        return []
    return (
        (await db.execute(select(HoldingPosition).where(HoldingPosition.snapshot_id == latest.id)))
        .scalars()
        .all()
    )


@router.post("/holdings/import/preview", response_model=HoldingsPreviewResponse)
async def preview_holdings_import(payload: HoldingsPreviewRequest, db: AsyncSession = Depends(get_db)):
    """Shows duplicate candidates and unresolved identifiers BEFORE anything
    is persisted (V3 section 5.2: 'Show duplicate candidates and unresolved
    identifiers before publishing a new immutable holdings snapshot.')."""
    duplicates: list[DuplicateCandidate] = []
    unresolved: list[UnresolvedIdentifier] = []

    seen_within_batch: dict[str, int] = {}
    existing_positions = await _latest_snapshot_positions(db, SINGLE_USER_ID)
    existing_identifiers = {p.raw_identifier_text for p in existing_positions if p.raw_identifier_text}

    instrument_ids = {row.instrument_id for row in payload.rows if row.instrument_id is not None}
    resolved_instrument_ids: set[uuid.UUID] = set()
    if instrument_ids:
        found = (
            (await db.execute(select(Instrument.id).where(Instrument.id.in_(instrument_ids))))
            .scalars()
            .all()
        )
        resolved_instrument_ids = set(found)

    for idx, row in enumerate(payload.rows):
        identifier = row.raw_identifier_text
        if identifier is not None:
            if identifier in seen_within_batch:
                duplicates.append(
                    DuplicateCandidate(row_index=idx, raw_identifier_text=identifier, reason="duplicate_within_batch")
                )
            elif identifier in existing_identifiers:
                duplicates.append(
                    DuplicateCandidate(
                        row_index=idx, raw_identifier_text=identifier, reason="matches_existing_snapshot"
                    )
                )
            seen_within_batch[identifier] = idx

        if row.instrument_id is None or row.instrument_id not in resolved_instrument_ids:
            unresolved.append(UnresolvedIdentifier(row_index=idx, raw_identifier_text=identifier))

    return HoldingsPreviewResponse(rows=payload.rows, duplicate_candidates=duplicates, unresolved_identifiers=unresolved)


class HoldingsConfirmRequest(BaseModel):
    rows: list[HoldingRowIn]
    idempotency_key: str
    source: str = "manual"  # "manual" | "csv_import"
    import_hash: str | None = None


class HoldingPositionOut(BaseModel):
    id: uuid.UUID
    instrument_id: uuid.UUID | None
    raw_identifier_text: str | None
    account_label: str | None
    units: Decimal | None
    amount: Decimal
    valuation_date: date
    valuation_source: str
    cost_basis: Decimal | None
    locked: bool
    lock_reason: str | None
    ownership: str
    include_in_planning: bool
    identification_confidence: str


class HoldingsSnapshotOut(BaseModel):
    id: uuid.UUID
    source: str
    import_hash: str | None
    idempotency_key: str
    created_at: str
    positions: list[HoldingPositionOut]


def _confidence_for(row: HoldingRowIn, resolved: bool) -> str:
    if resolved:
        return "high"
    if row.raw_identifier_text:
        return "low"
    return "unresolved"


@router.post("/holdings/import/confirm", response_model=HoldingsSnapshotOut)
async def confirm_holdings_import(payload: HoldingsConfirmRequest, db: AsyncSession = Depends(get_db)):
    """Idempotent: a retried identical import (same idempotency_key) must not
    create a duplicate snapshot -- matches the exact-key-match idempotency
    style already established for candle re-imports
    (app/pipelines/recommendation_pipeline.py::_persist_candles), simplified
    here to a direct unique-key lookup rather than content diffing."""
    existing = (
        await db.execute(
            select(HoldingsSnapshot).where(HoldingsSnapshot.idempotency_key == payload.idempotency_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        positions = (
            (await db.execute(select(HoldingPosition).where(HoldingPosition.snapshot_id == existing.id)))
            .scalars()
            .all()
        )
        return _snapshot_to_out(existing, positions)

    instrument_ids = {row.instrument_id for row in payload.rows if row.instrument_id is not None}
    resolved_instrument_ids: set[uuid.UUID] = set()
    if instrument_ids:
        found = (
            (await db.execute(select(Instrument.id).where(Instrument.id.in_(instrument_ids))))
            .scalars()
            .all()
        )
        resolved_instrument_ids = set(found)

    snapshot = HoldingsSnapshot(
        user_id=SINGLE_USER_ID,
        source=payload.source,
        import_hash=payload.import_hash,
        idempotency_key=payload.idempotency_key,
        created_at=utcnow(),
    )
    db.add(snapshot)
    await db.flush()

    positions: list[HoldingPosition] = []
    for row in payload.rows:
        resolved = row.instrument_id is not None and row.instrument_id in resolved_instrument_ids
        position = HoldingPosition(
            snapshot_id=snapshot.id,
            instrument_id=row.instrument_id if resolved else None,
            raw_identifier_text=row.raw_identifier_text,
            account_label=row.account_label,
            units=row.units,
            amount=row.amount,
            valuation_date=row.valuation_date,
            valuation_source=row.valuation_source,
            cost_basis=row.cost_basis,  # never synthesized from amount -- only what was explicitly given
            locked=row.locked,
            lock_reason=row.lock_reason,
            ownership=row.ownership,
            include_in_planning=row.include_in_planning,
            identification_confidence=_confidence_for(row, resolved),
        )
        db.add(position)
        positions.append(position)

    await db.commit()
    await db.refresh(snapshot)
    for p in positions:
        await db.refresh(p)
    return _snapshot_to_out(snapshot, positions)


def _snapshot_to_out(snapshot: HoldingsSnapshot, positions: list[HoldingPosition]) -> HoldingsSnapshotOut:
    return HoldingsSnapshotOut(
        id=snapshot.id,
        source=snapshot.source,
        import_hash=snapshot.import_hash,
        idempotency_key=snapshot.idempotency_key,
        created_at=snapshot.created_at.isoformat(),
        positions=[
            HoldingPositionOut(
                id=p.id,
                instrument_id=p.instrument_id,
                raw_identifier_text=p.raw_identifier_text,
                account_label=p.account_label,
                units=p.units,
                amount=p.amount,
                valuation_date=p.valuation_date,
                valuation_source=p.valuation_source,
                cost_basis=p.cost_basis,
                locked=p.locked,
                lock_reason=p.lock_reason,
                ownership=p.ownership,
                include_in_planning=p.include_in_planning,
                identification_confidence=p.identification_confidence,
            )
            for p in positions
        ],
    )


@router.get("/holdings/latest", response_model=HoldingsSnapshotOut)
async def latest_holdings(db: AsyncSession = Depends(get_db)):
    latest = (
        await db.execute(
            select(HoldingsSnapshot)
            .where(HoldingsSnapshot.user_id == SINGLE_USER_ID)
            .order_by(HoldingsSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        raise HTTPException(status_code=404, detail="No holdings snapshot yet")
    positions = (
        (await db.execute(select(HoldingPosition).where(HoldingPosition.snapshot_id == latest.id)))
        .scalars()
        .all()
    )
    return _snapshot_to_out(latest, positions)


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------


class GoalCreateRequest(BaseModel):
    description: str
    target_amount: Decimal
    target_basis: str
    target_date: date
    priority: int
    flexibility: str
    inflation_assumption: Decimal | None = None
    inflation_assumption_version: str | None = None

    @field_validator("target_amount")
    @classmethod
    def _target_amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0 or not v.is_finite():
            raise ValueError("target_amount must be a finite positive Decimal")
        return v

    @field_validator("target_basis")
    @classmethod
    def _valid_target_basis(cls, v: str) -> str:
        if v not in VALID_TARGET_BASIS:
            raise ValueError(f"target_basis must be one of {sorted(VALID_TARGET_BASIS)}")
        return v

    @field_validator("flexibility")
    @classmethod
    def _valid_flexibility(cls, v: str) -> str:
        if v not in VALID_FLEXIBILITY:
            raise ValueError(f"flexibility must be one of {sorted(VALID_FLEXIBILITY)}")
        return v


class GoalOut(BaseModel):
    id: uuid.UUID
    description: str
    target_amount: Decimal
    target_basis: str
    target_date: date
    priority: int
    flexibility: str
    inflation_assumption: Decimal | None
    inflation_assumption_version: str | None
    version: int
    superseded_at: str | None
    created_at: str
    earmarked_total: Decimal
    remaining_unearmarked_target: Decimal


def _goal_to_out(goal: Goal, earmarked_total: Decimal) -> GoalOut:
    return GoalOut(
        id=goal.id,
        description=goal.description,
        target_amount=goal.target_amount,
        target_basis=goal.target_basis,
        target_date=goal.target_date,
        priority=goal.priority,
        flexibility=goal.flexibility,
        inflation_assumption=goal.inflation_assumption,
        inflation_assumption_version=goal.inflation_assumption_version,
        version=goal.version,
        superseded_at=goal.superseded_at.isoformat() if goal.superseded_at else None,
        created_at=goal.created_at.isoformat(),
        earmarked_total=earmarked_total,
        remaining_unearmarked_target=goal.target_amount - earmarked_total,
    )


async def _earmarked_total_for_goal(db: AsyncSession, goal_id: uuid.UUID) -> Decimal:
    rows = (await db.execute(select(GoalEarmark.amount).where(GoalEarmark.goal_id == goal_id))).scalars().all()
    total = Decimal("0")
    for amount in rows:
        total += amount
    return total


@router.post("/goals", response_model=GoalOut)
async def create_goal(payload: GoalCreateRequest, db: AsyncSession = Depends(get_db)):
    goal = Goal(
        user_id=SINGLE_USER_ID,
        description=payload.description,
        target_amount=payload.target_amount,
        target_basis=payload.target_basis,
        target_date=payload.target_date,
        priority=payload.priority,
        flexibility=payload.flexibility,
        inflation_assumption=payload.inflation_assumption,
        inflation_assumption_version=payload.inflation_assumption_version,
        version=1,
        superseded_at=None,
        created_at=utcnow(),
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return _goal_to_out(goal, Decimal("0"))


@router.put("/goals/{goal_id}", response_model=GoalOut)
async def edit_goal(goal_id: uuid.UUID, payload: GoalCreateRequest, db: AsyncSession = Depends(get_db)):
    """Append-only edit (V3 section 10.2): creates a NEW Goal row with
    version = old.version + 1, stamps superseded_at on the old row, and does
    NOT mutate the old row's other fields.

    Known follow-up (out of scope here, needs product-policy decisions):
    existing GoalEarmarks pointing at the OLD goal id become orphaned by this
    -- they are not automatically carried forward to the new version. A
    caller who wants them preserved must re-create them against the new
    goal id.
    """
    old = await db.get(Goal, goal_id)
    if old is None or old.superseded_at is not None:
        raise HTTPException(status_code=404, detail="Goal not found (or already superseded)")

    new_goal = Goal(
        user_id=old.user_id,
        description=payload.description,
        target_amount=payload.target_amount,
        target_basis=payload.target_basis,
        target_date=payload.target_date,
        priority=payload.priority,
        flexibility=payload.flexibility,
        inflation_assumption=payload.inflation_assumption,
        inflation_assumption_version=payload.inflation_assumption_version,
        version=old.version + 1,
        superseded_at=None,
        created_at=utcnow(),
    )
    old.superseded_at = utcnow()
    db.add(new_goal)
    await db.commit()
    await db.refresh(new_goal)
    return _goal_to_out(new_goal, Decimal("0"))


@router.get("/goals", response_model=list[GoalOut])
async def list_goals(db: AsyncSession = Depends(get_db)):
    goals = (
        (
            await db.execute(
                select(Goal).where(Goal.user_id == SINGLE_USER_ID, Goal.superseded_at.is_(None))
                .order_by(Goal.priority.asc())
            )
        )
        .scalars()
        .all()
    )
    out = []
    for g in goals:
        total = await _earmarked_total_for_goal(db, g.id)
        out.append(_goal_to_out(g, total))
    return out


class EarmarkCreateRequest(BaseModel):
    holding_position_id: uuid.UUID
    amount: Decimal

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0 or not v.is_finite():
            raise ValueError("amount must be a finite positive Decimal")
        return v


class EarmarkOut(BaseModel):
    id: uuid.UUID
    goal_id: uuid.UUID
    holding_position_id: uuid.UUID
    amount: Decimal
    created_at: str


@router.post("/goals/{goal_id}/earmarks", response_model=EarmarkOut)
async def create_earmark(goal_id: uuid.UUID, payload: EarmarkCreateRequest, db: AsyncSession = Depends(get_db)):
    """Hard invariant (V3 section 5.3): the sum of ALL non-orphaned earmarks
    against a holding, plus this new one, must never exceed that holding's
    amount. Enforced here with a real summing query against every Goal that
    is not superseded -- an earmark against a superseded goal is orphaned
    (see edit_goal's docstring) and excluded from the sum."""
    goal = await db.get(Goal, goal_id)
    if goal is None or goal.superseded_at is not None:
        raise HTTPException(status_code=404, detail="Goal not found (or already superseded)")

    position = await db.get(HoldingPosition, payload.holding_position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Holding position not found")

    existing_total_rows = (
        await db.execute(
            select(GoalEarmark.amount)
            .join(Goal, GoalEarmark.goal_id == Goal.id)
            .where(
                GoalEarmark.holding_position_id == payload.holding_position_id,
                Goal.superseded_at.is_(None),
            )
        )
    ).scalars().all()
    existing_total = Decimal("0")
    for amount in existing_total_rows:
        existing_total += amount

    if existing_total + payload.amount > position.amount:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Earmark of {payload.amount} would exceed holding {payload.holding_position_id}'s "
                f"available amount ({position.amount}); already earmarked {existing_total} across "
                f"other current goals."
            ),
        )

    earmark = GoalEarmark(
        goal_id=goal_id,
        holding_position_id=payload.holding_position_id,
        amount=payload.amount,
        created_at=utcnow(),
    )
    db.add(earmark)
    await db.commit()
    await db.refresh(earmark)
    return EarmarkOut(
        id=earmark.id,
        goal_id=earmark.goal_id,
        holding_position_id=earmark.holding_position_id,
        amount=earmark.amount,
        created_at=earmark.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Recurring commitments
# ---------------------------------------------------------------------------


class CommitmentCreateRequest(BaseModel):
    instrument_id: uuid.UUID | None = None
    category: str | None = None
    amount: Decimal
    frequency: str
    start_date: date
    end_date: date | None = None
    contribution_timing: str
    step_up_rule: dict | None = None
    status: str = "active"
    goal_id: uuid.UUID | None = None
    source: str
    # No default -- V3 section 7.1 requires this be explicit, never assumed.
    # Pydantic's `...` (required, no default) makes a missing/null value a
    # 422 validation error rather than a silently-defaulted one.
    budget_interpretation: str

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0 or not v.is_finite():
            raise ValueError("amount must be a finite positive Decimal")
        return v

    @field_validator("frequency")
    @classmethod
    def _valid_frequency(cls, v: str) -> str:
        if v not in VALID_FREQUENCY:
            raise ValueError(f"frequency must be one of {sorted(VALID_FREQUENCY)}")
        return v

    @field_validator("contribution_timing")
    @classmethod
    def _valid_timing(cls, v: str) -> str:
        if v not in VALID_TIMING:
            raise ValueError(f"contribution_timing must be one of {sorted(VALID_TIMING)}")
        return v

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        if v not in VALID_STATUS:
            raise ValueError(f"status must be one of {sorted(VALID_STATUS)}")
        return v

    @field_validator("source")
    @classmethod
    def _valid_source(cls, v: str) -> str:
        if v not in VALID_COMMITMENT_SOURCE:
            raise ValueError(f"source must be one of {sorted(VALID_COMMITMENT_SOURCE)}")
        return v

    @field_validator("budget_interpretation")
    @classmethod
    def _valid_budget_interpretation(cls, v: str) -> str:
        if v not in VALID_BUDGET_INTERPRETATION:
            raise ValueError(f"budget_interpretation must be one of {sorted(VALID_BUDGET_INTERPRETATION)}")
        return v


class CommitmentOut(BaseModel):
    id: uuid.UUID
    instrument_id: uuid.UUID | None
    category: str | None
    amount: Decimal
    frequency: str
    start_date: date
    end_date: date | None
    contribution_timing: str
    step_up_rule: dict | None
    status: str
    goal_id: uuid.UUID | None
    source: str
    budget_interpretation: str | None
    created_at: str


def _commitment_to_out(c: RecurringCommitment) -> CommitmentOut:
    return CommitmentOut(
        id=c.id,
        instrument_id=c.instrument_id,
        category=c.category,
        amount=c.amount,
        frequency=c.frequency,
        start_date=c.start_date,
        end_date=c.end_date,
        contribution_timing=c.contribution_timing,
        step_up_rule=c.step_up_rule,
        status=c.status,
        goal_id=c.goal_id,
        source=c.source,
        budget_interpretation=c.budget_interpretation,
        created_at=c.created_at.isoformat(),
    )


@router.post("/commitments", response_model=CommitmentOut)
async def create_commitment(payload: CommitmentCreateRequest, db: AsyncSession = Depends(get_db)):
    commitment = RecurringCommitment(
        user_id=SINGLE_USER_ID,
        instrument_id=payload.instrument_id,
        category=payload.category,
        amount=payload.amount,
        frequency=payload.frequency,
        start_date=payload.start_date,
        end_date=payload.end_date,
        contribution_timing=payload.contribution_timing,
        step_up_rule=payload.step_up_rule,
        status=payload.status,
        goal_id=payload.goal_id,
        source=payload.source,
        budget_interpretation=payload.budget_interpretation,
        created_at=utcnow(),
    )
    db.add(commitment)
    await db.commit()
    await db.refresh(commitment)
    return _commitment_to_out(commitment)


@router.get("/commitments", response_model=list[CommitmentOut])
async def list_commitments(db: AsyncSession = Depends(get_db)):
    commitments = (
        (await db.execute(select(RecurringCommitment).where(RecurringCommitment.user_id == SINGLE_USER_ID)))
        .scalars()
        .all()
    )
    return [_commitment_to_out(c) for c in commitments]
