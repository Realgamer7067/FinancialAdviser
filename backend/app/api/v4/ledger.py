"""The scorecard: has any signal earned the right to a weight? Everything here is read-only except queueing the registered study.
Backtest evidence and live evidence are kept apart and labelled; a backtest can never reach `earned`."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.securities import LedgerOutcome, LedgerStudy
from app.portfolio_intelligence.ledger import registry as R
from app.portfolio_intelligence.ledger.jobs import enqueue_study
from app.portfolio_intelligence.ledger.live import live_status
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4/ledger", tags=["v4-ledger"])


@router.get("/registry")
async def registry():
    return {**R.registry(), "registry_hash": R.registry_hash(), "study_v2": R.registry_v2(), "registry_hash_v2": R.registry_hash_v2(), "live_claims": R.LIVE_CLAIMS, "live_registry_hash": R.live_registry_hash(),
            "rule": "The design was frozen and hashed before the first result was computed. Changing any part of it is a new study version, and the scorecard counts versions tried."}


@router.get("/study")
async def study(version: str | None = None, db: AsyncSession = Depends(get_db)):
    """The stored study. Default: the newest version. Every version tried is listed, and older versions stay readable (`?version=study-v1`)."""
    rows = (await db.execute(select(LedgerStudy).order_by(LedgerStudy.created_at.desc()))).scalars().all()
    versions = sorted({r.study_version for r in rows})
    if not rows:
        return {"status": "none", "versions_tried": 0, "message": "the registered study has not been run yet", "registry_hash": R.registry_hash_v2()}
    chosen = next((r for r in rows if version is None or r.study_version == version), None)
    if chosen is None:
        return {"status": "none", "versions_tried": len(versions), "versions": versions, "message": f"no stored study for version {version}", "registry_hash": R.registry_hash_v2()}
    expected = R.REGISTRIES.get(chosen.study_version, (None, lambda: None))[1]()
    return {"status": "ready", "versions_tried": len(versions), "versions": versions, "study_id": str(chosen.id), "created_at": chosen.created_at.isoformat(), "evidence": "backtest",
            "registry_hash": chosen.registry_hash, "frozen_hash_matches_code": chosen.registry_hash == expected,
            "other_versions": [{"version": r.study_version, "created_at": r.created_at.isoformat(), "outcome_basis": r.result.get("outcome_basis", "price")} for r in rows if r.id != chosen.id], **chosen.result}


@router.post("/study/run", status_code=202)
async def run_study(db: AsyncSession = Depends(get_db)):
    job = await enqueue_study(db, "manual", utcnow())
    return {"queued": job is not None, "already_queued": job is None}


@router.get("/live")
async def live(db: AsyncSession = Depends(get_db)):
    return await live_status(db)


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)):
    n = (await db.execute(select(func.count()).select_from(LedgerOutcome).where(LedgerOutcome.status == "scored"))).scalar_one()
    return {"outcomes_scored": n, "studies": (await db.execute(select(func.count()).select_from(LedgerStudy))).scalar_one()}
