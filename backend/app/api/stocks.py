"""Stock-detail API (Section 56)."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.single_user import SINGLE_USER_ID
from app.models.analysis import FinbertAnalysis, KronosPrediction, TechnicalFeatures
from app.models.council import CouncilOutput
from app.models.fundamentals import FundamentalMetrics
from app.models.market import Instrument, MarketCandle
from app.models.news import NewsAnalysis, NewsItem
from app.models.recommendation import Recommendation
from app.providers.mode import expected_candle_source, expected_fundamentals_source
from app.schemas.recommendation import CouncilRoleOutput, RecommendationCard
from app.services.manifest import get_manifest_entry, is_legacy
from app.schemas.stock import (
    FundamentalsOut,
    KronosOut,
    NewsArticleOut,
    NewsArticlesOut,
    NewsOut,
    PriceHistoryOut,
    PriceHistoryPoint,
    StockDetail,
    TechnicalsOut,
)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/{symbol}", response_model=StockDetail)
async def get_stock_detail(symbol: str, db: AsyncSession = Depends(get_db)):
    instrument = (await db.execute(select(Instrument).where(Instrument.symbol == symbol))).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=404, detail="Unknown symbol")

    # docs/v3-execution/CONTRACTS.md C3: an API read-path selecting "most
    # recent row" must filter by the current DEMO_MODE's source, same as the
    # pipeline's own ingestion-side cache reads -- otherwise a demo<->live
    # toggle can serve the wrong mode's candle/fundamentals here even though
    # ingestion itself is correctly isolated.
    latest_candle = (
        await db.execute(
            select(MarketCandle)
            .where(
                MarketCandle.instrument_id == instrument.id,
                MarketCandle.source == expected_candle_source(),
                MarketCandle.superseded_at.is_(None),
            )
            .order_by(MarketCandle.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # V3 Phase 02 (docs/v3-execution/phase-02.md): a report's evidence
    # (fundamentals/technicals/kronos) must bind to the EXACT data the
    # recommendation was actually built from, not "most recent as of read
    # time" -- otherwise the page can silently mix a stale council verdict
    # with newer numbers it never saw. Resolve the recommendation and its
    # manifest entry FIRST so evidence reads can pin to it when available.
    # Price stays independently "live" on purpose -- current market price is
    # supposed to be fresh, unlike the scored evidence inputs.
    recommendation = (
        await db.execute(
            select(Recommendation)
            .where(Recommendation.instrument_id == instrument.id, Recommendation.user_id == SINGLE_USER_ID)
            .order_by(Recommendation.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    manifest_entry = (
        await get_manifest_entry(db, recommendation.council_run_id, instrument.id) if recommendation else None
    )
    evidence_is_legacy = recommendation is not None and is_legacy(manifest_entry)

    fundamentals_query = select(FundamentalMetrics).where(FundamentalMetrics.instrument_id == instrument.id)
    if manifest_entry and manifest_entry.fundamentals_retrieved_at is not None:
        fundamentals_query = fundamentals_query.where(
            FundamentalMetrics.source == manifest_entry.fundamentals_source,
            FundamentalMetrics.retrieved_at == manifest_entry.fundamentals_retrieved_at,
        )
    else:
        fundamentals_query = fundamentals_query.where(FundamentalMetrics.source == expected_fundamentals_source())
    fundamentals = (
        await db.execute(fundamentals_query.order_by(FundamentalMetrics.retrieved_at.desc()).limit(1))
    ).scalar_one_or_none()

    technicals_query = select(TechnicalFeatures).where(TechnicalFeatures.instrument_id == instrument.id)
    if manifest_entry and manifest_entry.technicals_computed_at is not None:
        technicals_query = technicals_query.where(TechnicalFeatures.computed_at == manifest_entry.technicals_computed_at)
    technicals = (
        await db.execute(technicals_query.order_by(TechnicalFeatures.computed_at.desc()).limit(1))
    ).scalar_one_or_none()

    kronos_query = select(KronosPrediction).where(
        KronosPrediction.instrument_id == instrument.id, KronosPrediction.forecast_horizon == "30d"
    )
    if manifest_entry and manifest_entry.kronos_generated_at is not None:
        kronos_query = kronos_query.where(
            KronosPrediction.model_version == manifest_entry.kronos_model_version,
            KronosPrediction.generated_at == manifest_entry.kronos_generated_at,
        )
    kronos = (
        await db.execute(kronos_query.order_by(KronosPrediction.generated_at.desc()).limit(1))
    ).scalar_one_or_none()

    # Up to 3 rows, one per horizon -- separate queries rather than a window
    # function since this table is tiny per instrument (Phase 0B #4).
    kronos_horizons = []
    for horizon in ("7d", "30d", "90d"):
        row = (
            await db.execute(
                select(KronosPrediction)
                .where(KronosPrediction.instrument_id == instrument.id, KronosPrediction.forecast_horizon == horizon)
                .order_by(KronosPrediction.generated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            kronos_horizons.append(
                KronosOut(
                    forecast_horizon=row.forecast_horizon,
                    direction=row.direction,
                    predicted_return=row.predicted_return,
                    predicted_return_p10=row.predicted_return_p10,
                    predicted_return_p90=row.predicted_return_p90,
                    direction_agreement=row.direction_agreement,
                    sample_count=row.sample_count,
                    confidence=row.confidence,
                    generated_at=row.generated_at,
                )
            )

    news = (
        await db.execute(
            select(FinbertAnalysis)
            .where(FinbertAnalysis.instrument_id == instrument.id)
            .order_by(FinbertAnalysis.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    council_outputs = []
    if recommendation is not None:
        output_rows = (
            await db.execute(
                select(CouncilOutput).where(
                    CouncilOutput.council_run_id == recommendation.council_run_id,
                    CouncilOutput.instrument_id == instrument.id,
                )
            )
        ).scalars().all()
        council_outputs = [
            CouncilRoleOutput(
                role=out.role,
                content=out.content,
                model_name=out.model_name,
                model_version=out.model_version,
                prompt_version=out.prompt_version,
                created_at=out.created_at,
            )
            for out in output_rows
        ]

    return StockDetail(
        symbol=instrument.symbol,
        name=instrument.name,
        sector=instrument.sector,
        latest_price=latest_candle.close if latest_candle else None,
        price_as_of=latest_candle.timestamp if latest_candle else None,
        evidence_is_legacy=evidence_is_legacy,
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
                beta=technicals.beta,
                sma_20=technicals.sma_20,
                sma_50=technicals.sma_50,
                sma_200=technicals.sma_200,
                ema_12=technicals.ema_12,
                ema_26=technicals.ema_26,
                bb_upper=technicals.bb_upper,
                bb_lower=technicals.bb_lower,
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
                predicted_return_p10=kronos.predicted_return_p10,
                predicted_return_p90=kronos.predicted_return_p90,
                direction_agreement=kronos.direction_agreement,
                sample_count=kronos.sample_count,
                confidence=kronos.confidence,
                generated_at=kronos.generated_at,
            )
            if kronos
            else None
        ),
        kronos_horizons=kronos_horizons,
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
                confidence_band=recommendation.confidence_band,
                score=recommendation.score,
                risk_level=recommendation.risk_level,
                risk_tier=recommendation.risk_tier,
                risk_tier_score=recommendation.risk_tier_score,
                risk_tier_breakdown=recommendation.risk_tier_breakdown,
                suggested_horizon=recommendation.suggested_horizon,
                strengths=recommendation.strengths,
                risks=recommendation.risks,
                rationale=recommendation.rationale,
                evidence=recommendation.evidence,
                fundamental_score=recommendation.fundamental_score,
                technical_score=recommendation.technical_score,
                kronos_score=recommendation.kronos_score,
                news_score=recommendation.news_score,
                portfolio_score=recommendation.portfolio_score,
                risk_score=recommendation.risk_score,
                model_agreement=recommendation.model_agreement,
                data_quality=recommendation.data_quality,
                generated_at=recommendation.generated_at,
                council_outputs=council_outputs,
            )
            if recommendation
            else None
        ),
    )


@router.get("/{symbol}/history", response_model=PriceHistoryOut)
async def get_stock_history(symbol: str, days: int = 180, db: AsyncSession = Depends(get_db)):
    days = max(1, min(days, 365))
    instrument = (await db.execute(select(Instrument).where(Instrument.symbol == symbol))).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=404, detail="Unknown symbol")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(MarketCandle)
            .where(
                MarketCandle.instrument_id == instrument.id,
                MarketCandle.interval == "1d",
                MarketCandle.timestamp >= cutoff,
                MarketCandle.source == expected_candle_source(),
                MarketCandle.superseded_at.is_(None),
            )
            .order_by(MarketCandle.timestamp.asc())
        )
    ).scalars().all()

    return PriceHistoryOut(
        symbol=symbol,
        interval="1d",
        points=[
            PriceHistoryPoint(timestamp=r.timestamp, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
            for r in rows
        ],
    )


@router.get("/{symbol}/news", response_model=NewsArticlesOut)
async def get_stock_news(symbol: str, days: int = 30, db: AsyncSession = Depends(get_db)):
    """Raw ingested articles tagged to this symbol -- the aggregate sentiment
    on StockDetail.news is a summary of exactly these. Filtered in Python
    (`symbol in item.companies`), same as the pipeline's own
    _aggregate_news_sentiment -- NewsItem.companies is a JSON array, not
    portably queryable with SQL containment across the SQLite-in-tests /
    Postgres-in-prod split this repo relies on."""
    days = max(1, min(days, 365))
    instrument = (await db.execute(select(Instrument).where(Instrument.symbol == symbol))).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=404, detail="Unknown symbol")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(NewsAnalysis, NewsItem)
            .join(NewsItem, NewsAnalysis.news_id == NewsItem.id)
            .where(NewsItem.published_at >= cutoff)
            .order_by(NewsItem.published_at.desc())
        )
    ).all()
    matching = [(a, n) for a, n in rows if symbol in n.companies][:50]

    return NewsArticlesOut(
        symbol=symbol,
        articles=[
            NewsArticleOut(
                title=n.title,
                url=n.url,
                source=n.source,
                published_at=n.published_at,
                sentiment=a.sentiment,
                event_type=a.event_type,
                confidence=a.confidence,
            )
            for a, n in matching
        ],
    )
