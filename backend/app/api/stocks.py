"""Stock-detail API (Section 56)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.analysis import FinbertAnalysis, KronosPrediction, TechnicalFeatures
from app.models.fundamentals import FundamentalMetrics
from app.models.market import Instrument, MarketCandle
from app.models.recommendation import Recommendation
from app.models.user import User
from app.schemas.recommendation import RecommendationCard
from app.schemas.stock import FundamentalsOut, KronosOut, NewsOut, StockDetail, TechnicalsOut

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/{symbol}", response_model=StockDetail)
async def get_stock_detail(symbol: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    instrument = (await db.execute(select(Instrument).where(Instrument.symbol == symbol))).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=404, detail="Unknown symbol")

    latest_candle = (
        await db.execute(
            select(MarketCandle)
            .where(MarketCandle.instrument_id == instrument.id)
            .order_by(MarketCandle.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    fundamentals = (
        await db.execute(
            select(FundamentalMetrics)
            .where(FundamentalMetrics.instrument_id == instrument.id)
            .order_by(FundamentalMetrics.retrieved_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    technicals = (
        await db.execute(
            select(TechnicalFeatures)
            .where(TechnicalFeatures.instrument_id == instrument.id)
            .order_by(TechnicalFeatures.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    kronos = (
        await db.execute(
            select(KronosPrediction)
            .where(KronosPrediction.instrument_id == instrument.id)
            .order_by(KronosPrediction.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    news = (
        await db.execute(
            select(FinbertAnalysis)
            .where(FinbertAnalysis.instrument_id == instrument.id)
            .order_by(FinbertAnalysis.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    recommendation = (
        await db.execute(
            select(Recommendation)
            .where(Recommendation.instrument_id == instrument.id, Recommendation.user_id == user.id)
            .order_by(Recommendation.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return StockDetail(
        symbol=instrument.symbol,
        name=instrument.name,
        sector=instrument.sector,
        latest_price=latest_candle.close if latest_candle else None,
        fundamentals=(
            FundamentalsOut(
                as_of_date=str(fundamentals.as_of_date),
                roe=fundamentals.roe,
                revenue_growth=fundamentals.revenue_growth,
                debt_to_equity=fundamentals.debt_to_equity,
                pe=fundamentals.pe,
                net_margin=fundamentals.net_margin,
                market_cap=fundamentals.market_cap,
                source=fundamentals.source,
            )
            if fundamentals
            else None
        ),
        technicals=(
            TechnicalsOut(
                rsi_14=technicals.rsi_14,
                trend=technicals.trend,
                volatility_30d=technicals.volatility_30d,
                drawdown_1y=technicals.drawdown_1y,
                macd_hist=technicals.macd_hist,
                computed_at=technicals.computed_at,
            )
            if technicals
            else None
        ),
        kronos=(
            KronosOut(
                forecast_horizon=kronos.forecast_horizon,
                direction=kronos.direction,
                predicted_return=kronos.predicted_return,
                confidence=kronos.confidence,
                generated_at=kronos.generated_at,
            )
            if kronos
            else None
        ),
        news=(
            NewsOut(
                sentiment_score=news.sentiment_score,
                confidence=news.confidence,
                article_count=news.article_count,
                window_start=news.window_start,
                window_end=news.window_end,
            )
            if news
            else None
        ),
        recommendation=(
            RecommendationCard(
                id=recommendation.id,
                symbol=instrument.symbol,
                name=instrument.name,
                recommendation=recommendation.recommendation,
                confidence=recommendation.confidence,
                score=recommendation.score,
                risk_level=recommendation.risk_level,
                suggested_horizon=recommendation.suggested_horizon,
                strengths=recommendation.strengths,
                risks=recommendation.risks,
                rationale=recommendation.rationale,
                evidence=recommendation.evidence,
                model_agreement=recommendation.model_agreement,
                data_quality=recommendation.data_quality,
                generated_at=recommendation.generated_at,
            )
            if recommendation
            else None
        ),
    )
