"""Portfolio API (Section 22)."""

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.portfolio import PortfolioResult
from app.models.recommendation import PortfolioRecommendation
from app.models.user import User

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class PortfolioOut(BaseModel):
    method: str
    allocations: dict[str, float]
    expected_return: float | None
    expected_volatility: float | None
    sharpe: float | None
    notes: list[str]


@router.get("/latest", response_model=PortfolioOut)
async def latest_portfolio(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = (
        await db.execute(
            select(PortfolioRecommendation, PortfolioResult)
            .join(PortfolioResult, PortfolioRecommendation.portfolio_result_id == PortfolioResult.id)
            .where(PortfolioRecommendation.user_id == user.id)
            .order_by(PortfolioRecommendation.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No portfolio recommendation yet -- trigger analysis first")
    rec, result = row
    return PortfolioOut(
        method=result.method,
        allocations=rec.allocations,
        expected_return=result.expected_return,
        expected_volatility=result.expected_volatility,
        sharpe=result.sharpe,
        notes=rec.notes,
    )
