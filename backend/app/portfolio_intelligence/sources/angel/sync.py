"""One account sync: session -> profile identity check -> holdings ->
normalize -> publish, fenced on the job's worker_token (plan section 12.4)."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import PositionObservation, SourceAccount, SourceImport
from app.models.market import Instrument
from app.models.portfolio_jobs import PortfolioJob
from app.pipelines.publication import StalePublicationError
from app.portfolio_intelligence.normalization.identity import resolve_identity
from app.portfolio_intelligence.sources.angel.client import AngelClient
from app.portfolio_intelligence.sources.angel.errors import (
    AngelError,
    AuthExpired,
    IdentityConflict,
    Unavailable,
)
from app.portfolio_intelligence.sources.angel.holdings import ParsedHoldings, parse_holdings
from app.portfolio_intelligence.sources.angel.identity import fingerprint
from app.portfolio_intelligence.sources.angel.token_store import load_session
from app.portfolio_intelligence.sources.import_rows import SCHEMA_VERSION, content_hash
from app.portfolio_intelligence.state.build import safe_refresh
from app.utils.time import utcnow

ANGEL_SCHEMA_VERSION = "angel-holdings-v1"


async def fetch_account_snapshot(
    account: SourceAccount, client: AngelClient | None = None
) -> tuple[ParsedHoldings, dict]:
    """Network half of a sync. Returns parsed holdings and a provider summary
    (RMS / open positions kept as separate, labelled coverage buckets)."""
    own_client = client is None
    if client is None:
        session = load_session()
        if session is None:
            raise AuthExpired("no valid Angel session; run the operator setup")
        client = AngelClient(jwt=session.jwt)
    try:
        profile = await client.get_profile()
        if not account.external_fingerprint or fingerprint(str(profile["clientcode"])) != account.external_fingerprint:
            raise IdentityConflict("the connected Angel session belongs to a different account")
        retrieved_at = utcnow()
        data = await client.get_all_holding()
        parsed = parse_holdings(data, retrieved_at)

        summary: dict = {"schema": ANGEL_SCHEMA_VERSION, "retrieved_at": retrieved_at.isoformat()}
        # Separate coverage buckets: never merged into holdings.
        try:
            positions = await client.get_positions()
            summary["open_positions"] = {"count": len(positions), "supported": False,
                                         "note": "intraday/derivative positions are not valued or risk-modelled"}
        except AuthExpired:
            raise
        except AngelError as exc:
            summary["open_positions"] = {"fetched": False, "code": exc.code}
        try:
            rms = await client.get_rms()
            summary["rms_raw"] = {k: rms.get(k) for k in ("net", "availablecash", "availableintradaypayin", "utilisedpayout")
                                  if k in rms}
            summary["rms_note"] = "raw broker funds/margin fields; not confirmed deployable cash"
        except AuthExpired:
            raise
        except AngelError as exc:
            summary["rms_raw"] = {"fetched": False, "code": exc.code}
        return parsed, summary
    finally:
        if own_client:
            await client.aclose()


async def publish_sync_result(
    db: AsyncSession, job_id: uuid.UUID, worker_token: str, account_id: uuid.UUID,
    parsed: ParsedHoldings, summary: dict,
) -> SourceImport:
    """Insert the import, update account freshness and complete the job in ONE
    transaction, only if this attempt still owns the job. A partial batch is
    stored for review but never becomes the account's current snapshot
    (latest_import() only reads status='complete') and fails the job."""
    # populate_existing: the session may already hold this job from before the
    # (slow) network fetch; without it the fence would compare STALE in-memory
    # token/status instead of the freshly locked row.
    job = (
        await db.execute(
            select(PortfolioJob).where(PortfolioJob.id == job_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if job is None or job.worker_token != worker_token or job.status != "running":
        raise StalePublicationError("sync attempt no longer owns the job")
    account = await db.get(SourceAccount, account_id, populate_existing=True)
    if account is None:
        raise Unavailable("account disappeared during sync")

    instruments = (await db.execute(select(Instrument))).scalars().all()
    now = utcnow()
    summary = {**summary, "quarantined_rows": parsed.quarantined}
    imp = SourceImport(
        account_id=account.id,
        idempotency_key=f"sync-{job.id}",
        content_hash=content_hash(parsed.rows),
        schema_version=f"{SCHEMA_VERSION}/{ANGEL_SCHEMA_VERSION}",
        status=parsed.status,
        row_count=len(parsed.rows),
        reconciliation=parsed.reconciliation,
        provider_summary=summary,
        created_at=now,
    )
    db.add(imp)
    await db.flush()
    for ordinal, (row, meta) in enumerate(zip(parsed.rows, parsed.metas), start=1):
        res = resolve_identity(asset_type=row.asset_type, isin=row.isin, symbol=row.symbol,
                               approved_instrument_id=None, instruments=instruments)
        db.add(PositionObservation(
            import_id=imp.id, row_ordinal=ordinal, asset_type=row.asset_type,
            raw_identifier=row.raw_identifier, isin=row.isin, symbol=row.symbol,
            instrument_id=res.instrument_id, resolution=res.status, resolution_note=res.note,
            units=row.units, value=row.value, valuation_date=row.valuation_date,
            cost_basis=None, locked=False, ownership="sole", source_meta=meta,
        ))
    job.result_import_id = imp.id
    job.completed_at = now
    account.last_sync_at = now
    if parsed.status == "complete":
        job.status = "done"
        account.status = "active"
        account.last_error = None
    else:
        job.status = "failed"
        job.error_code = "PARTIAL_DATA"
        job.error = (f"{len(parsed.quarantined)} row(s) quarantined; "
                     f"reconciliation material gap={parsed.reconciliation.get('material_gap')}")
        account.last_error = "PARTIAL_DATA: last sync was incomplete; previous complete import kept"
    await db.commit()
    user_id, imp_id, status = account.user_id, imp.id, parsed.status
    await safe_refresh(db, user_id)
    if status == "complete":
        # Even when holdings are unchanged the account may have just recovered from "reconnect required":
        # re-review so the current decision reflects it. Duplicates coalesce (one live review job).
        from app.portfolio_intelligence.decisions.runner import enqueue_review, kick_inline_reviews
        from app.portfolio_intelligence.events import record_event

        await record_event(db, user_id, "import_published", dedup_key=f"import:{imp_id}", source_id=str(imp_id),
                           affected={"import_id": str(imp_id)})
        await enqueue_review(db, user_id)
        kick_inline_reviews()
    return imp
