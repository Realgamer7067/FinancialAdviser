"""Data-manifest service (V3 Phase 02): record and resolve, per (council_run,
instrument), the EXACT identifying version of the fundamentals/technicals/
kronos-forecast/candle data used to build that instrument's evidence.

This module is self-contained -- it does not import the pipeline, API, or
any provider/model_iface module. Wiring `record_manifest_entry` into
`recommendation_pipeline.py` and `get_manifest_entry` into `api/stocks.py` /
`api/recommendations.py` is a separate coordinator pass.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.manifest import DataManifestEntry


async def record_manifest_entry(
    db: AsyncSession,
    council_run_id: uuid.UUID,
    instrument_id: uuid.UUID,
    *,
    candle_source: str | None,
    candle_as_of: datetime | None,
    fundamentals_source: str | None,
    fundamentals_as_of_date: date | None,
    fundamentals_retrieved_at: datetime | None,
    technicals_computed_at: datetime | None,
    kronos_model_version: str | None,
    kronos_forecast_horizon: str | None,
    kronos_generated_at: datetime | None,
) -> DataManifestEntry:
    """Creates and flushes (does not commit) one manifest row for one
    instrument within one council run. Caller commits as part of its own
    transaction -- this must not call db.commit() itself, matching the rest
    of the pipeline's single-final-commit pattern (see
    recommendation_pipeline.py's docstring for why: ownership checks and
    publication must land atomically in one transaction)."""
    entry = DataManifestEntry(
        council_run_id=council_run_id,
        instrument_id=instrument_id,
        candle_source=candle_source,
        candle_as_of=candle_as_of,
        fundamentals_source=fundamentals_source,
        fundamentals_as_of_date=fundamentals_as_of_date,
        fundamentals_retrieved_at=fundamentals_retrieved_at,
        technicals_computed_at=technicals_computed_at,
        kronos_model_version=kronos_model_version,
        kronos_forecast_horizon=kronos_forecast_horizon,
        kronos_generated_at=kronos_generated_at,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.flush()
    return entry


async def get_manifest_entry(
    db: AsyncSession, council_run_id: uuid.UUID, instrument_id: uuid.UUID
) -> DataManifestEntry | None:
    """Looks up the manifest entry for one instrument within one council
    run. Returns None if none exists -- this is the "legacy report" case
    (the run predates the manifest system) and must be treated as
    unversioned, not backfilled with a fake entry. See `is_legacy`."""
    result = await db.execute(
        select(DataManifestEntry).where(
            DataManifestEntry.council_run_id == council_run_id,
            DataManifestEntry.instrument_id == instrument_id,
        )
    )
    return result.scalar_one_or_none()


def is_legacy(entry: DataManifestEntry | None) -> bool:
    """True when `entry` is None, i.e. the council run predates the
    manifest system and has no recorded data provenance. Callers (report
    rendering, freshness claims) must branch on this rather than inventing a
    manifest entry for old runs after the fact -- per V3 Phase 02: 'legacy
    reports with incomplete provenance stay explicitly legacy/unversioned.'"""
    return entry is None
