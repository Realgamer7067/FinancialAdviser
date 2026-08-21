"""Portfolio API (Section 22)."""

import math

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.market import Instrument, MarketCandle
from app.models.portfolio import PortfolioResult
from app.models.recommendation import PortfolioRecommendation

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class PortfolioOut(BaseModel):
    method: str
    allocations: dict[str, float]
    sectors: dict[str, str | None]
    expected_return: float | None
    expected_volatility: float | None
    sharpe: float | None
    notes: list[str]


class AllocateRequest(BaseModel):
    amount: float = Field(gt=0)


class StockAllocation(BaseModel):
    symbol: str
    weight: float
    rupee_amount: float
    last_price: float | None
    shares: int | None


class AllocateOut(BaseModel):
    amount: float
    total_allocated: float
    cash_remainder: float
    allocations: list[StockAllocation]


async def _load_latest_portfolio(db: AsyncSession) -> tuple[PortfolioRecommendation, PortfolioResult]:
    row = (
        await db.execute(
            select(PortfolioRecommendation, PortfolioResult)
            .join(PortfolioResult, PortfolioRecommendation.portfolio_result_id == PortfolioResult.id)
            .where(PortfolioRecommendation.user_id == SINGLE_USER_ID)
            .order_by(PortfolioRecommendation.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No portfolio recommendation yet -- trigger analysis first")
    return row


@router.get("/latest", response_model=PortfolioOut)
async def latest_portfolio(db: AsyncSession = Depends(get_db)):
    rec, result = await _load_latest_portfolio(db)
    instruments = (
        await db.execute(select(Instrument).where(Instrument.symbol.in_(rec.allocations.keys())))
    ).scalars().all()
    sectors = {i.symbol: i.sector for i in instruments}
    return PortfolioOut(
        method=result.method,
        allocations=rec.allocations,
        sectors=sectors,
        expected_return=result.expected_return,
        expected_volatility=result.expected_volatility,
        sharpe=result.sharpe,
        notes=rec.notes,
    )


@router.post("/allocate", response_model=AllocateOut)
async def allocate_portfolio(payload: AllocateRequest, db: AsyncSession = Depends(get_db)):
    """Turns the latest optimizer weights into rupee amounts + whole-share
    counts for a given investment amount (Section 22 follow-up -- weights
    alone don't tell a beginner how many shares of what to actually buy).
    NSE doesn't support fractional share delivery, so amounts are floored to
    whole shares per stock; leftover cash is reported as `cash_remainder`."""
    rec, _ = await _load_latest_portfolio(db)

    allocations: list[StockAllocation] = []
    total_allocated = 0.0
    for symbol, weight in rec.allocations.items():
        instrument = (await db.execute(select(Instrument).where(Instrument.symbol == symbol))).scalar_one_or_none()
        last_price = None
        if instrument is not None:
            latest_candle = (
                await db.execute(
                    select(MarketCandle)
                    .where(MarketCandle.instrument_id == instrument.id)
                    .order_by(MarketCandle.timestamp.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            last_price = latest_candle.close if latest_candle else None

        target_amount = payload.amount * weight
        if last_price:
            shares = math.floor(target_amount / last_price)
            rupee_amount = round(shares * last_price, 2)
        else:
            shares = None
            rupee_amount = round(target_amount, 2)

        total_allocated += rupee_amount
        allocations.append(
            StockAllocation(symbol=symbol, weight=weight, rupee_amount=rupee_amount, last_price=last_price, shares=shares)
        )

    return AllocateOut(
        amount=payload.amount,
        total_allocated=round(total_allocated, 2),
        cash_remainder=round(payload.amount - total_allocated, 2),
        allocations=allocations,
    )
