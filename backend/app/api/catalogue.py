"""Product catalogue API (V3 Phase 03, docs/V3-IMPLEMENTATION-PLAN.md section
4.2). Read-only: lists/reads catalogue entries with the RE-DERIVED support
level (app/services/catalogue.py::resolve_support_level) as the authoritative
value -- the stored `support_level` column is only a cached hint and can be
stale. `is_synthetic` is always surfaced so a frontend can badge synthetic
entries and never present them as real live market terms."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.catalogue import ProductCatalogEntry
from app.services.catalogue import resolve_support_level

router = APIRouter(prefix="/api/catalogue", tags=["catalogue"])


class ProductCatalogEntryOut(BaseModel):
    id: UUID
    external_ids: dict
    parent_exposure_id: str | None
    product_type: str
    issuer_or_amc: str
    currency: str
    status: str
    support_level: str  # stored value, kept for visibility/debugging only
    resolved_support_level: str  # RE-DERIVED -- the authoritative value for gating
    exposure_vector: dict
    exposure_as_of: date
    valuation_method: str
    valuation_date: date | None
    eligible_contribution_methods: list
    minimum_initial: Decimal | None
    minimum_additional: Decimal | None
    increment: Decimal | None
    quantity_granularity: str
    settlement_delay_days: int | None
    maturity_or_lock_rule: str | None
    fee_assumptions: dict | None
    eligibility_predicates: dict | None
    source_ids: list
    source_freshness: date
    is_synthetic: bool
    created_at: datetime

    model_config = {"from_attributes": True}


def _to_out(entry: ProductCatalogEntry) -> ProductCatalogEntryOut:
    return ProductCatalogEntryOut(
        id=entry.id,
        external_ids=entry.external_ids,
        parent_exposure_id=entry.parent_exposure_id,
        product_type=entry.product_type,
        issuer_or_amc=entry.issuer_or_amc,
        currency=entry.currency,
        status=entry.status,
        support_level=entry.support_level,
        resolved_support_level=resolve_support_level(entry),
        exposure_vector=entry.exposure_vector,
        exposure_as_of=entry.exposure_as_of,
        valuation_method=entry.valuation_method,
        valuation_date=entry.valuation_date,
        eligible_contribution_methods=entry.eligible_contribution_methods,
        minimum_initial=entry.minimum_initial,
        minimum_additional=entry.minimum_additional,
        increment=entry.increment,
        quantity_granularity=entry.quantity_granularity,
        settlement_delay_days=entry.settlement_delay_days,
        maturity_or_lock_rule=entry.maturity_or_lock_rule,
        fee_assumptions=entry.fee_assumptions,
        eligibility_predicates=entry.eligibility_predicates,
        source_ids=entry.source_ids,
        source_freshness=entry.source_freshness,
        is_synthetic=entry.is_synthetic,
        created_at=entry.created_at,
    )


@router.get("", response_model=list[ProductCatalogEntryOut])
async def list_catalogue(
    product_type: str | None = Query(default=None),
    support_level: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    query = select(ProductCatalogEntry).where(ProductCatalogEntry.status == "active")
    if product_type is not None:
        query = query.where(ProductCatalogEntry.product_type == product_type)
    entries = (await db.execute(query)).scalars().all()

    out = [_to_out(e) for e in entries]
    if support_level is not None:
        # Filter on the RE-DERIVED level, not the stored column -- a stored
        # support_level can claim instrument_planning while missing critical
        # terms; the derived value is the source of truth for gating.
        out = [o for o in out if o.resolved_support_level == support_level]
    return out


@router.get("/{entry_id}", response_model=ProductCatalogEntryOut)
async def get_catalogue_entry(entry_id: UUID, db: AsyncSession = Depends(get_db)):
    entry = await db.get(ProductCatalogEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown catalogue entry")
    return _to_out(entry)
