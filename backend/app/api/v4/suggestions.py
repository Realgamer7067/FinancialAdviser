"""What changed for the securities you hold or watch. GET computes and writes NOTHING; the nightly worker raises inbox items and logs."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.portfolio_intelligence.suggestions.build import build_suggestions, declared
from app.utils.time import utcnow

router = APIRouter(prefix="/api/v4", tags=["v4-suggestions"])


@router.get("/suggestions")
async def suggestions(db: AsyncSession = Depends(get_db)):
    return await build_suggestions(db, utcnow())


@router.get("/suggestions/policy")
async def suggestions_policy():
    return declared()
