"""The recommendation pipeline (build plan's core vertical slice). Wires every
provider/model/deterministic-engine built so far into the single flow from
Section-17-style evidence to a persisted, auditable Recommendation row.

Deterministic code > specialist ML > LLM reasoning (Section 61) is enforced
throughout: screening/scoring/risk-gate are plain Python; Kronos/FinBERT/
PyPortfolioOpt produce evidence; Qwen only synthesizes evidence it's handed.
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import screening_config, settings
from app.council.orchestrator import run_candidate_council, run_planner
from app.models.analysis import FinbertAnalysis, KronosPrediction, TechnicalFeatures
from app.models.council import CandidateScore, CouncilOutput, CouncilRun
from app.models.fundamentals import FundamentalMetrics
from app.models.market import Instrument, MarketCandle
from app.models.news import NewsAnalysis, NewsItem
from app.models.portfolio import PortfolioResult
from app.models.recommendation import PortfolioRecommendation, Recommendation
from app.models.user import RiskProfile, UserProfile
from app.models_iface.base import NotImplementedModel
from app.models_iface.finbert import FinBERTModel
from app.models_iface.kronos import KronosModel
from app.models_iface.llm import LLMProvider, QwenOpenAICompatibleProvider
from app.models_iface.portfolio_mvo import MeanVariancePortfolioModel
from app.pipelines.progress import (
    STAGE_COUNCIL_EVALUATION,
    STAGE_COUNCIL_SETUP,
    STAGE_FETCHING_MARKET_DATA,
    STAGE_FINALIZING,
    STAGE_KRONOS_FORECAST,
    STAGE_LOADING_PROFILE,
    STAGE_MARKET_REGIME,
    STAGE_NEWS_INGESTION,
    STAGE_PLANNER,
    STAGE_PORTFOLIO_OPTIMIZATION,
    STAGE_PRELIM_SCORING,
    STAGE_SCREENING,
    STAGE_SYNCING_INSTRUMENTS,
    JobProgressTracker,
)
from app.pipelines.publication import verify_ownership
from app.services.manifest import record_manifest_entry
from app.providers.base import Candle, FundamentalDataProvider, FundamentalSnapshot, MarketDataProvider
from app.providers.factory import get_fundamental_provider, get_market_data_provider
from app.providers.mode import expected_candle_source, expected_fundamentals_source
from app.providers.nifty50_seed import NIFTY50_SEED
from app.providers.rss_news import RSSNewsProvider
from app.risk.gate import apply_risk_gate
from app.scoring.evidence import (
    CandidateEvidence,
    FundamentalEvidence,
    KronosEvidence,
    MarketEvidence,
    NewsEvidence,
    PortfolioEvidence,
    TechnicalEvidence,
)
from app.scoring.final_score import compute_final_score
from app.scoring.subscores import (
    fundamental_score as calc_fundamental_score,
    kronos_score as calc_kronos_score,
    news_score as calc_news_score,
    portfolio_score as calc_portfolio_score,
    risk_fit_score as calc_risk_fit_score,
    risk_tier as calc_risk_tier,
    risk_tier_score_with_breakdown as calc_risk_tier_score_with_breakdown,
    technical_score as calc_technical_score,
    volatility_band,
)
from app.services.fundamental_analysis import fill_derived_ratios
from app.services.market_regime import detect_market_regime
from app.services.technical_analysis import compute_technical_features

RISK_FREE_RATE = 0.07  # approx. Indian 10Y G-Sec yield proxy -- review periodically, not live data
MAX_SINGLE_WEIGHT = 0.25  # fallback when risk_profile is unknown -- see _max_single_weight_for
MAX_SINGLE_WEIGHT_BY_RISK_PROFILE = {
    "conservative": 0.15,
    "moderate": 0.25,
    "aggressive": 0.35,
}
HISTORY_DAYS = 400
NEWS_WINDOW_DAYS = 14
INTER_SYMBOL_DELAY_SECONDS = 0.2  # burst-rate headroom against yfinance's undocumented limits
CANDLE_STALENESS_TOLERANCE_DAYS = 3  # weekend/holiday gaps don't force a refetch


def _max_single_weight_for(risk_profile_label: str | None) -> float:
    """Conservative users get a tighter per-stock concentration cap than
    aggressive ones -- makes the "risk-balanced" allocation real instead of
    a single global constant applied to everyone (Part 2 of the beyond-MVP plan)."""
    return MAX_SINGLE_WEIGHT_BY_RISK_PROFILE.get(risk_profile_label, MAX_SINGLE_WEIGHT)


class PipelineError(Exception):
    pass


# ---------------------------------------------------------------- context ---


async def _load_user_context(db: AsyncSession, user_id: UUID) -> tuple[UserProfile, RiskProfile]:
    profile = (
        await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id).order_by(UserProfile.created_at.desc())
        )
    ).scalars().first()
    if profile is None:
        raise PipelineError("User has no onboarding profile yet.")

    risk = (
        await db.execute(
            select(RiskProfile).where(RiskProfile.user_profile_id == profile.id).order_by(RiskProfile.created_at.desc())
        )
    ).scalars().first()
    if risk is None:
        raise PipelineError("User has no computed risk profile yet.")

    return profile, risk


async def _sync_instruments(db: AsyncSession) -> dict[str, Instrument]:
    existing = {i.symbol: i for i in (await db.execute(select(Instrument))).scalars().all()}
    for seed in NIFTY50_SEED:
        if seed.symbol in existing:
            continue
        instrument = Instrument(
            symbol=seed.symbol,
            exchange="NSE",
            isin=seed.isin,
            name=seed.name,
            sector=seed.sector,
            instrument_key=seed.instrument_key,
        )
        db.add(instrument)
        existing[seed.symbol] = instrument
    await db.flush()
    return existing


# ------------------------------------------------------------- candles -----


async def _get_cached_candles(db: AsyncSession, instrument_id: UUID) -> list[Candle] | None:
    """MarketCandle rows persisted by a prior run, reused as a cache (Section 65:
    don't hit a rate-limited upstream for data we already have). None means no
    usable cache -- caller must fetch live."""
    rows = (
        await db.execute(
            select(MarketCandle)
            .where(
                MarketCandle.instrument_id == instrument_id,
                MarketCandle.interval == "1d",
                MarketCandle.source == expected_candle_source(),
                MarketCandle.superseded_at.is_(None),
            )
            .order_by(MarketCandle.timestamp)
        )
    ).scalars().all()
    if not rows:
        return None
    tolerance_days = settings.market_data_staleness_override_days
    if tolerance_days is None:
        tolerance_days = CANDLE_STALENESS_TOLERANCE_DAYS
    if (date.today() - rows[-1].timestamp.date()).days > tolerance_days:
        return None
    return [
        Candle(
            timestamp=r.timestamp,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume,
            source=r.source,
            retrieved_at=r.retrieved_at,
            adjusted=r.adjusted,
        )
        for r in rows
    ]


async def _fetch_candles(
    db: AsyncSession, provider: MarketDataProvider, instrument_id: UUID | None, symbol: str
) -> tuple[list[Candle], bool]:
    """Returns (candles, from_cache) -- callers must not re-persist candles that
    were already read back from MarketCandle, or every cache hit would insert
    duplicate rows."""
    if instrument_id is not None:
        cached = await _get_cached_candles(db, instrument_id)
        if cached is not None:
            return cached, True

    to_date = date.today()
    from_date = to_date - timedelta(days=HISTORY_DAYS)
    try:
        return await provider.get_historical_ohlcv(symbol, "1d", from_date, to_date), False
    except Exception:
        return [], False  # Section 50: a failed symbol doesn't crash the run


async def _persist_candles(db: AsyncSession, instrument_id: UUID, candles: list[Candle]) -> None:
    """A fresh fetch always re-pulls the FULL history window (HISTORY_DAYS),
    not just missing days -- inserting it on top of existing rows without
    clearing the overlap first duplicates every overlapping session
    (docs/V2-RETHINK.md P0). A refresh must not, however, HARD DELETE prior
    rows: a published Recommendation's evidence can reference technicals
    computed from a specific historical candle set, and once deleted that
    set can never be reconstructed (V3 Phase 02, docs/v3-execution/phase-02.md).

    So instead of deleting the overlap, this soft-supersedes it: rows whose
    (instrument, interval, timestamp, source) key is about to be replaced by
    genuinely different data get `superseded_at` stamped (kept, but excluded
    from every "current" read by the partial unique index / read-path
    filters), and the new data is inserted fresh under a shared
    `import_batch_id`. Candles that are byte-identical to what's already
    stored as the current row are left untouched entirely, so re-importing
    the same window twice in a row is a no-op rather than a supersede-churn
    loop.
    """
    if not candles:
        return
    sources = {c.source for c in candles}

    def _norm_ts(ts: datetime) -> datetime:
        # SQLite's DateTime(timezone=True) round-trips a tz-aware value as a
        # naive one (the offset isn't persisted), so a freshly-constructed
        # Candle.timestamp (aware) and a MarketCandle.timestamp read back
        # from the DB (naive) compare unequal -- and hash differently -- even
        # when they represent the same instant. Normalize both sides to
        # naive UTC before using them as comparison/dict keys so the diff
        # below isn't fooled by that round-trip into treating unchanged rows
        # as new.
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc)
        return ts.replace(tzinfo=None)

    existing_rows = (
        await db.execute(
            select(MarketCandle).where(
                MarketCandle.instrument_id == instrument_id,
                MarketCandle.interval == "1d",
                MarketCandle.source.in_(sources),
                MarketCandle.superseded_at.is_(None),
            )
        )
    ).scalars().all()
    existing_by_key = {(r.source, _norm_ts(r.timestamp)): r for r in existing_rows}

    def _unchanged(row: MarketCandle, c: Candle) -> bool:
        return (
            row.open == c.open
            and row.high == c.high
            and row.low == c.low
            and row.close == c.close
            and row.volume == c.volume
        )

    to_insert = [
        c
        for c in candles
        if (c.source, _norm_ts(c.timestamp)) not in existing_by_key
        or not _unchanged(existing_by_key[(c.source, _norm_ts(c.timestamp))], c)
    ]
    if not to_insert:
        return  # every incoming candle matches what's already the current row -- idempotent no-op

    now = datetime.now(timezone.utc)
    supersede_keys = [
        (c.source, _norm_ts(c.timestamp)) for c in to_insert if (c.source, _norm_ts(c.timestamp)) in existing_by_key
    ]
    if supersede_keys:
        supersede_ids = [existing_by_key[key].id for key in supersede_keys]
        await db.execute(
            update(MarketCandle)
            .where(
                MarketCandle.instrument_id == instrument_id,
                MarketCandle.interval == "1d",
                MarketCandle.superseded_at.is_(None),
                MarketCandle.id.in_(supersede_ids),
            )
            .values(superseded_at=now)
        )

    batch_id = uuid.uuid4()
    for c in to_insert:
        db.add(
            MarketCandle(
                instrument_id=instrument_id,
                interval="1d",
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                source=c.source,
                retrieved_at=c.retrieved_at,
                import_batch_id=batch_id,
                adjusted=c.adjusted,
            )
        )
    await db.flush()


# --------------------------------------------------------- fundamentals ----


async def _get_cached_fundamentals(db: AsyncSession, instrument: Instrument) -> FundamentalSnapshot | None:
    """FundamentalMetrics rows persisted by a prior run, reused as a TTL cache --
    yfinance `.info` is a single unofficial, rate-limited endpoint hit once per
    symbol per pipeline run; without this every run re-fetches all ~50 symbols
    regardless of how recently the last run fetched them."""
    ttl_hours = settings.fundamentals_staleness_override_hours
    if ttl_hours is None:
        ttl_hours = settings.fundamentals_cache_ttl_hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    row = (
        await db.execute(
            select(FundamentalMetrics)
            .where(
                FundamentalMetrics.instrument_id == instrument.id,
                FundamentalMetrics.retrieved_at >= cutoff,
                FundamentalMetrics.source == expected_fundamentals_source(),
            )
            .order_by(FundamentalMetrics.retrieved_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if row is None:
        return None
    return FundamentalSnapshot(
        symbol=instrument.symbol,
        as_of_date=row.as_of_date,
        revenue=row.revenue,
        revenue_growth=row.revenue_growth,
        ebitda=row.ebitda,
        ebitda_margin=row.ebitda_margin,
        ebit=row.ebit,
        pat=row.pat,
        eps=row.eps,
        eps_growth=row.eps_growth,
        operating_cash_flow=row.operating_cash_flow,
        free_cash_flow=row.free_cash_flow,
        total_debt=row.total_debt,
        debt_to_equity=row.debt_to_equity,
        interest_coverage=row.interest_coverage,
        roe=row.roe,
        roce=row.roce,
        operating_margin=row.operating_margin,
        net_margin=row.net_margin,
        pe=row.pe,
        forward_pe=row.forward_pe,
        pb=row.pb,
        ev_ebitda=row.ev_ebitda,
        dividend_yield=row.dividend_yield,
        insider_holding_pct=row.insider_holding_pct,
        promoter_holding=row.promoter_holding,
        promoter_pledging=row.promoter_pledging,
        institutional_ownership=row.institutional_ownership,
        market_cap=row.market_cap,
        source=row.source,
        retrieved_at=row.retrieved_at,
    )


async def _fetch_fundamentals(
    db: AsyncSession, instrument: Instrument, provider: FundamentalDataProvider
) -> FundamentalSnapshot | None:
    cached = await _get_cached_fundamentals(db, instrument)
    if cached is not None:
        return cached

    snapshot = await provider.get_fundamentals(instrument.symbol)
    if snapshot is None:
        return None
    snapshot = fill_derived_ratios(snapshot)
    db.add(
        FundamentalMetrics(
            instrument_id=instrument.id,
            as_of_date=snapshot.as_of_date,
            revenue=snapshot.revenue,
            revenue_growth=snapshot.revenue_growth,
            ebitda=snapshot.ebitda,
            ebitda_margin=snapshot.ebitda_margin,
            ebit=snapshot.ebit,
            pat=snapshot.pat,
            eps=snapshot.eps,
            eps_growth=snapshot.eps_growth,
            operating_cash_flow=snapshot.operating_cash_flow,
            free_cash_flow=snapshot.free_cash_flow,
            total_debt=snapshot.total_debt,
            debt_to_equity=snapshot.debt_to_equity,
            interest_coverage=snapshot.interest_coverage,
            roe=snapshot.roe,
            roce=snapshot.roce,
            operating_margin=snapshot.operating_margin,
            net_margin=snapshot.net_margin,
            pe=snapshot.pe,
            forward_pe=snapshot.forward_pe,
            pb=snapshot.pb,
            ev_ebitda=snapshot.ev_ebitda,
            dividend_yield=snapshot.dividend_yield,
            insider_holding_pct=snapshot.insider_holding_pct,
            promoter_holding=snapshot.promoter_holding,
            promoter_pledging=snapshot.promoter_pledging,
            institutional_ownership=snapshot.institutional_ownership,
            market_cap=snapshot.market_cap,
            source=snapshot.source,
            retrieved_at=snapshot.retrieved_at,
        )
    )
    await db.flush()
    return snapshot


# ------------------------------------------------------------ screening ----


def _passes_screen(
    snapshot: FundamentalSnapshot | None, technicals: dict, candles: list[Candle], cfg: dict
) -> bool:
    liq_cfg = cfg["liquidity_screen"]
    if candles:
        avg_volume = sum(c.volume for c in candles[-30:]) / min(len(candles), 30)
        if avg_volume < liq_cfg["min_avg_daily_volume"]:
            return False
    else:
        return False  # no candle history at all -- can't confirm liquidity

    fund_cfg = cfg["fundamental_screen"]
    if snapshot:
        if snapshot.debt_to_equity is not None and snapshot.debt_to_equity > fund_cfg["max_debt_to_equity"]:
            return False
        if snapshot.roe is not None and snapshot.roe < fund_cfg["min_roe"]:
            return False
        if (
            snapshot.promoter_pledging is not None
            and snapshot.promoter_pledging > fund_cfg["exclude_pledged_promoter_holding_above"]
        ):
            return False

    tech_cfg = cfg["technical_screen"]
    vol = technicals.get("volatility_30d")
    if vol is not None and vol > tech_cfg["max_volatility_30d"]:
        return False

    return True


# ---------------------------------------------------------------- news -----

_EVENT_KEYWORDS = {
    "earnings": ["earnings", "result", "profit", "revenue", "quarter", "q1", "q2", "q3", "q4"],
    "guidance": ["guidance", "outlook cut", "outlook raised"],
    "macro": ["rbi", "repo rate", "interest rate", "inflation", "gdp"],
    "regulatory": ["sebi", "regulation", "regulatory", "compliance"],
    "management": ["ceo", "cfo", "management", "resign", "appoint", "steps down"],
}


def _classify_event_type(title: str) -> str:
    lowered = title.lower()
    for event_type, keywords in _EVENT_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return event_type
    return "other"


def _tag_companies(title: str) -> list[str]:
    lowered = title.lower()
    return [s.symbol for s in NIFTY50_SEED if s.symbol.lower() in lowered or s.name.lower() in lowered]


async def _ingest_news(db: AsyncSession, news_provider: RSSNewsProvider, finbert: FinBERTModel) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=NEWS_WINDOW_DAYS)
    items = await news_provider.fetch_latest(since=since)
    existing_urls = {
        row[0] for row in (await db.execute(select(NewsItem.url).where(NewsItem.url.in_([i.url for i in items]))))
    }
    for item in items:
        if not item.url or item.url in existing_urls:
            continue
        # Multiple feeds (e.g. ET markets + ET stocks) can carry the same
        # article/URL -- dedupe within this batch too, not just against the DB.
        existing_urls.add(item.url)
        companies = _tag_companies(item.title)
        news_row = NewsItem(
            source=item.source,
            title=item.title,
            url=item.url,
            published_at=item.published_at,
            retrieved_at=item.retrieved_at,
            raw_summary=item.summary,
            companies=companies,
            sectors=[],
        )
        db.add(news_row)
        await db.flush()

        try:
            sentiment = await finbert.analyze_news(item.title, item.summary)
        except Exception:
            # Model unavailable (e.g. weights not downloaded/offline) -- the
            # NewsItem is still stored, just without sentiment (Section 50).
            continue
        db.add(
            NewsAnalysis(
                news_id=news_row.id,
                event_type=_classify_event_type(item.title),
                sentiment=sentiment.sentiment,
                confidence=sentiment.confidence,
                relevance=1.0 if companies else 0.3,
                importance=0.7 if _classify_event_type(item.title) != "other" else 0.4,
                model_name=sentiment.model_name,
                model_version=sentiment.model_version,
                analyzed_at=datetime.now(timezone.utc),
            )
        )
    await db.flush()


async def _aggregate_news_sentiment(db: AsyncSession, symbol: str, instrument_id: UUID) -> dict | None:
    since = datetime.now(timezone.utc) - timedelta(days=NEWS_WINDOW_DAYS)
    rows = (
        await db.execute(
            select(NewsAnalysis, NewsItem)
            .join(NewsItem, NewsAnalysis.news_id == NewsItem.id)
            .where(NewsItem.published_at >= since)
        )
    ).all()
    matching = [(a, n) for a, n in rows if symbol in n.companies]
    if not matching:
        return None

    total_weight = sum(a.confidence * a.relevance for a, _ in matching) or 1.0
    sentiment_score = sum(a.sentiment * a.confidence * a.relevance for a, _ in matching) / total_weight
    avg_confidence = sum(a.confidence for a, _ in matching) / len(matching)

    finbert_row = FinbertAnalysis(
        instrument_id=instrument_id,
        window_start=since,
        window_end=datetime.now(timezone.utc),
        sentiment_score=sentiment_score,
        confidence=avg_confidence,
        article_count=len(matching),
        model_name="FinBERT",
        model_version=matching[0][0].model_version,
        generated_at=datetime.now(timezone.utc),
    )
    db.add(finbert_row)
    await db.flush()

    # Give the council real articles to inspect, not just a folded-in number
    # (docs/V2-RETHINK.md P1/section 4). Ranked by importance*relevance --
    # already-computed FinBERT fields, no new data acquisition needed.
    top_matching = sorted(matching, key=lambda pair: pair[0].importance * pair[0].relevance, reverse=True)[:5]
    recent_articles = [
        {
            "headline": news.title,
            "url": news.url,
            "event_type": analysis.event_type,
            "sentiment": analysis.sentiment,
            "published_at": news.published_at.isoformat(),
        }
        for analysis, news in top_matching
    ]
    return {
        "sentiment": sentiment_score,
        "confidence": avg_confidence,
        "article_count": len(matching),
        "recent_articles": recent_articles,
    }


# --------------------------------------------------------------- kronos ----


async def _kronos_forecast(
    db: AsyncSession, kronos: KronosModel, instrument: Instrument, candles: list[Candle], horizon: str = "30d"
) -> dict | None:
    forecast = await kronos.forecast(instrument.symbol, candles, horizon)
    if forecast is None:
        return None
    generated_at = datetime.now(timezone.utc)
    db.add(
        KronosPrediction(
            instrument_id=instrument.id,
            forecast_horizon=forecast.forecast_horizon,
            direction=forecast.direction,
            predicted_return=forecast.predicted_return,
            predicted_return_p10=forecast.predicted_return_p10,
            predicted_return_p90=forecast.predicted_return_p90,
            direction_agreement=forecast.direction_agreement,
            sample_count=forecast.sample_count,
            confidence=forecast.confidence,
            input_timeframe=forecast.input_timeframe,
            model_name=forecast.model_name,
            model_version=forecast.model_version,
            generated_at=generated_at,
        )
    )
    await db.flush()
    # `TimeSeriesForecast` (the pydantic schema `forecast` is) has no
    # generated_at field of its own -- it's assigned here, at persistence
    # time. The manifest (V3 Phase 02) needs it, so it's added into the
    # dict explicitly rather than silently being absent from model_dump().
    return {**forecast.model_dump(), "generated_at": generated_at}


# ------------------------------------------------------------- pipeline ----


async def run_recommendation_pipeline(
    db: AsyncSession, user_id: UUID, job_id: UUID | None = None, worker_token: str | None = None
) -> CouncilRun:
    progress = JobProgressTracker(job_id, worker_token=worker_token)
    await progress.set_stage(STAGE_LOADING_PROFILE)
    user_profile, risk_profile = await _load_user_context(db, user_id)
    user_profile_payload = {
        "risk_profile": risk_profile.risk_profile,
        "risk_score": risk_profile.risk_score,
        "investment_horizon_years": risk_profile.investment_horizon_years,
        "capital": risk_profile.capital,
        "monthly_contribution": risk_profile.monthly_contribution,
        "objective": risk_profile.objective,
        "liquidity_requirement": risk_profile.liquidity_requirement,
    }

    market_provider = await get_market_data_provider()
    fundamentals_provider = await get_fundamental_provider()
    news_provider = RSSNewsProvider()
    llm: LLMProvider = QwenOpenAICompatibleProvider()
    kronos = KronosModel()
    finbert = FinBERTModel()
    portfolio_model = MeanVariancePortfolioModel()
    screen_cfg = screening_config()

    await progress.set_stage(STAGE_SYNCING_INSTRUMENTS)
    instruments = await _sync_instruments(db)

    await progress.set_stage(STAGE_MARKET_REGIME)
    nifty_candles, _ = await _fetch_candles(db, market_provider, None, "NIFTY50")
    vix_quote = None
    try:
        vix_quote = await market_provider.get_quote("INDIA_VIX")
    except Exception:
        pass
    market_regime = detect_market_regime(nifty_candles, vix_quote)

    candles_by_symbol: dict[str, list[Candle]] = {}
    fundamentals_by_symbol: dict[str, FundamentalSnapshot | None] = {}
    technicals_by_symbol: dict[str, dict] = {}

    for i, seed in enumerate(NIFTY50_SEED):
        await progress.set_stage(
            STAGE_FETCHING_MARKET_DATA, current_symbol=seed.symbol, index=i, total=len(NIFTY50_SEED)
        )
        instrument = instruments[seed.symbol]
        candles, from_cache = await _fetch_candles(db, market_provider, instrument.id, seed.symbol)
        candles_by_symbol[seed.symbol] = candles
        if candles and not from_cache:
            await _persist_candles(db, instrument.id, candles)

        snapshot = await _fetch_fundamentals(db, instrument, fundamentals_provider)
        fundamentals_by_symbol[seed.symbol] = snapshot

        tech = compute_technical_features(candles, "1d", benchmark_candles=nifty_candles) if candles else None
        technicals_by_symbol[seed.symbol] = tech or {}  # downstream .get() calls stay safe on missing data
        if tech:
            db.add(TechnicalFeatures(instrument_id=instrument.id, **tech))
        await asyncio.sleep(INTER_SYMBOL_DELAY_SECONDS)
    await db.flush()

    await progress.set_stage(STAGE_SCREENING)
    passing_screen = [
        s.symbol
        for s in NIFTY50_SEED
        if _passes_screen(
            fundamentals_by_symbol[s.symbol], technicals_by_symbol[s.symbol], candles_by_symbol[s.symbol], screen_cfg
        )
    ]
    # Rank by fundamental+technical quality BEFORE truncating -- truncating in
    # NIFTY50_SEED's arbitrary listing order meant the top `after_...` slice
    # was whichever symbols happen to sit first in the seed file, not the
    # best-screening ones, and the expensive Kronos/news work below only ever
    # ran on that arbitrary subset (docs/V2-RETHINK.md P1).
    stage1 = sorted(
        passing_screen,
        key=lambda s: _prelim_score(s, fundamentals_by_symbol, technicals_by_symbol),
        reverse=True,
    )[: screen_cfg["candidate_limits"]["after_fundamental_technical_screen"]]

    await progress.set_stage(STAGE_NEWS_INGESTION)
    await _ingest_news(db, news_provider, finbert)

    kronos_by_symbol: dict[str, dict | None] = {}
    news_by_symbol: dict[str, dict | None] = {}
    for i, symbol in enumerate(stage1):
        await progress.set_stage(STAGE_KRONOS_FORECAST, current_symbol=symbol, index=i, total=len(stage1))
        instrument = instruments[symbol]
        kronos_by_symbol[symbol] = await _kronos_forecast(db, kronos, instrument, candles_by_symbol[symbol])
        news_by_symbol[symbol] = await _aggregate_news_sentiment(db, symbol, instrument.id)

    await progress.set_stage(STAGE_PRELIM_SCORING)

    stage2 = sorted(
        stage1, key=lambda s: _prelim_score(s, fundamentals_by_symbol, technicals_by_symbol), reverse=True
    )[: screen_cfg["candidate_limits"]["after_kronos_news"]]
    final_candidates = stage2[: screen_cfg["candidate_limits"]["final_council_input"]]

    # ---- extra Kronos horizons for the final candidates only (Phase 0B #4) ----
    # The 30d forecast above (inside the stage1 loop, up to 40 symbols) is what
    # scoring consumes and stays as-is. 7d/90d are only useful for the handful
    # of stocks that actually reach the council, so fetch them here instead of
    # widening the 40-symbol loop (which would be 3x the Kronos inference cost
    # for horizons nothing downstream of this block reads).
    for symbol in final_candidates:
        instrument = instruments[symbol]
        for horizon in ("7d", "90d"):
            await _kronos_forecast(db, kronos, instrument, candles_by_symbol[symbol], horizon=horizon)

    await progress.set_stage(STAGE_PORTFOLIO_OPTIMIZATION)
    # ---- portfolio optimization across final candidates ----
    candidate_returns = {}
    for symbol in final_candidates:
        candles = candles_by_symbol[symbol]
        if len(candles) < 30:
            continue
        candidate_returns[symbol] = _candles_to_return_series(candles)

    max_single_weight = _max_single_weight_for(risk_profile.risk_profile)

    portfolio_result = None
    if candidate_returns:
        try:
            allocation = await portfolio_model.optimize(candidate_returns, RISK_FREE_RATE, max_single_weight)
            portfolio_result = PortfolioResult(
                user_id=user_id,
                method=allocation.method,
                candidate_symbols=list(candidate_returns.keys()),
                allocations=allocation.allocations,
                unallocated_cash=allocation.unallocated_cash,
                expected_return=allocation.expected_return,
                expected_volatility=allocation.expected_volatility,
                sharpe=allocation.sharpe,
                model_version=allocation.model_version,
                generated_at=datetime.now(timezone.utc),
            )
            db.add(portfolio_result)
            await db.flush()
        except NotImplementedModel:
            portfolio_result = None

    await progress.set_stage(STAGE_COUNCIL_SETUP)
    council_run = CouncilRun(
        user_id=user_id,
        job_id=job_id,
        market_regime=market_regime["market_regime"],
        universe_size=len(NIFTY50_SEED),
        candidates_after_screen=len(stage1),
        candidates_after_kronos_news=len(stage2),
        candidates_to_council=len(final_candidates),
        plan={},
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(council_run)
    await db.flush()

    await progress.set_stage(STAGE_PLANNER)
    planner_result = await run_planner(llm, user_profile_payload, market_regime)
    plan_content = planner_result.content if planner_result else {}
    council_run.plan = plan_content
    if planner_result:
        db.add(
            CouncilOutput(
                council_run_id=council_run.id,
                instrument_id=None,  # planner is run-level, not per-instrument
                role="planner",
                content=planner_result.content,
                model_name=planner_result.model_name,
                model_version=planner_result.model_version,
                prompt_version=planner_result.prompt_version,
                created_at=datetime.now(timezone.utc),
            )
        )

    recommendation_labels: dict[str, str] = {}
    for i, symbol in enumerate(final_candidates):
        await progress.set_stage(
            STAGE_COUNCIL_EVALUATION, current_symbol=symbol, index=i, total=len(final_candidates)
        )
        recommendation_labels[symbol] = await _evaluate_candidate(
            db=db,
            llm=llm,
            council_run=council_run,
            instrument=instruments[symbol],
            symbol=symbol,
            candles=candles_by_symbol[symbol],
            fundamentals=fundamentals_by_symbol[symbol],
            technicals=technicals_by_symbol[symbol],
            kronos_data=kronos_by_symbol.get(symbol),
            news_data=news_by_symbol.get(symbol),
            portfolio_result=portfolio_result,
            user_profile_payload=user_profile_payload,
            risk_profile_label=risk_profile.risk_profile,
            plan=plan_content,
            market_regime=market_regime["market_regime"],
        )

    await progress.set_stage(STAGE_FINALIZING)
    # An excluded (NO_RECOMMENDATION) stock must never receive a published
    # allocation -- the preliminary `portfolio_result` above was built before
    # the risk gate ran and may still include rejected symbols. Rebuild the
    # allocation from only the accepted symbols before publishing (Section
    # 20: risk gate rejection must be final, not overridden downstream).
    accepted_symbols = [s for s in final_candidates if recommendation_labels.get(s) != "NO_RECOMMENDATION"]
    rejected_symbols_in_allocation = (
        set(portfolio_result.allocations) - set(accepted_symbols) if portfolio_result else set()
    )
    if portfolio_result and rejected_symbols_in_allocation:
        accepted_returns = {s: candidate_returns[s] for s in accepted_symbols if s in candidate_returns}
        if accepted_returns:
            allocation = await portfolio_model.optimize(accepted_returns, RISK_FREE_RATE, max_single_weight)
            portfolio_result = PortfolioResult(
                user_id=user_id,
                method=allocation.method,
                candidate_symbols=list(accepted_returns.keys()),
                allocations=allocation.allocations,
                unallocated_cash=allocation.unallocated_cash,
                expected_return=allocation.expected_return,
                expected_volatility=allocation.expected_volatility,
                sharpe=allocation.sharpe,
                model_version=allocation.model_version,
                generated_at=datetime.now(timezone.utc),
            )
            db.add(portfolio_result)
            await db.flush()
        else:
            portfolio_result = None

    if portfolio_result:
        db.add(
            PortfolioRecommendation(
                user_id=user_id,
                council_run_id=council_run.id,
                portfolio_result_id=portfolio_result.id,
                allocations=portfolio_result.allocations,
                notes=[],
                created_at=datetime.now(timezone.utc),
            )
        )

    council_run.status = "done"
    council_run.completed_at = datetime.now(timezone.utc)
    # Ownership check and publication commit MUST be the same transaction
    # (docs/v3-execution/CONTRACTS.md C2) -- every Recommendation/
    # PortfolioRecommendation row added above, plus this council_run status
    # flip, is still uncommitted at this point (this function holds one
    # long-lived transaction with a single commit at the very end). If this
    # attempt's worker_token no longer matches (lease expired and another
    # attempt reclaimed the job), verify_ownership raises before anything
    # below it commits -- nothing this attempt produced becomes visible.
    await verify_ownership(db, job_id, worker_token)
    await db.commit()
    return council_run


def _to_fundamental_evidence(snapshot: FundamentalSnapshot | None) -> FundamentalEvidence | None:
    if snapshot is None:
        return None
    return FundamentalEvidence(
        roe=snapshot.roe,
        revenue_growth=snapshot.revenue_growth,
        debt_to_equity=snapshot.debt_to_equity,
        pe=snapshot.pe,
        net_margin=snapshot.net_margin,
        promoter_pledging=snapshot.promoter_pledging,
        ebitda_margin=snapshot.ebitda_margin,
        operating_cash_flow=snapshot.operating_cash_flow,
        free_cash_flow=snapshot.free_cash_flow,
        pb=snapshot.pb,
        ev_ebitda=snapshot.ev_ebitda,
        dividend_yield=snapshot.dividend_yield,
        institutional_ownership=snapshot.institutional_ownership,
        insider_holding_pct=snapshot.insider_holding_pct,
    )


def _candles_to_return_series(candles: list[Candle]) -> pd.Series:
    """Daily returns indexed by trading DATE, not row position (docs/V2-
    RETHINK.md P1). MeanVariancePortfolioModel used to align candidates by
    truncating every series to the shortest length and zipping positionally
    -- correct only if every candidate's history has identical missing
    sessions, which isn't guaranteed (a stale cache gap, a trading halt, a
    newer listing). Returning a date-indexed Series lets the optimizer do a
    real date-based inner join instead."""
    closes = pd.Series(
        [c.close for c in candles], index=pd.DatetimeIndex([c.timestamp for c in candles]).normalize()
    )
    return closes.pct_change().dropna()


def _prelim_score(
    symbol: str,
    fundamentals_by_symbol: dict[str, FundamentalSnapshot | None],
    technicals_by_symbol: dict[str, dict],
) -> float:
    """Cheap fundamental+technical-only ranking used both to pick which
    screen-passing symbols get the expensive Kronos/news work (docs/V2-
    RETHINK.md P1: must rank before truncating, not truncate in arbitrary
    seed order) and to narrow further to the final council candidates."""
    parts = []
    f = calc_fundamental_score(_to_fundamental_evidence(fundamentals_by_symbol[symbol]))
    t = calc_technical_score(_to_technical_evidence(technicals_by_symbol[symbol]))
    for v in (f, t):
        if v is not None:
            parts.append(v)
    return sum(parts) / len(parts) if parts else 0.0


def _to_technical_evidence(tech: dict) -> TechnicalEvidence | None:
    if not tech:
        return None
    return TechnicalEvidence(
        rsi_14=tech.get("rsi_14"),
        trend=tech.get("trend"),
        volatility_30d=tech.get("volatility_30d"),
        drawdown_1y=tech.get("drawdown_1y"),
        macd_hist=tech.get("macd_hist"),
        beta=tech.get("beta"),
    )


async def _evaluate_candidate(
    db: AsyncSession,
    llm: LLMProvider,
    council_run: CouncilRun,
    instrument: Instrument,
    symbol: str,
    candles: list[Candle],
    fundamentals: FundamentalSnapshot | None,
    technicals: dict,
    kronos_data: dict | None,
    news_data: dict | None,
    portfolio_result: PortfolioResult | None,
    user_profile_payload: dict,
    risk_profile_label: str,
    plan: dict,
    market_regime: str | None = None,
) -> str:
    # yfinance occasionally returns NaN for a bad/halted trading day -- Postgres'
    # JSON type rejects literal NaN outright (not valid per the JSON spec, unlike
    # Python's json module which allows it), crashing the INSERT. Walk back to the
    # last candle with a real close rather than propagating whatever's newest.
    last_valid_close = next((c.close for c in reversed(candles) if c.close == c.close), None)
    last_price = last_valid_close if last_valid_close is not None else 0.0
    fundamental_ev = _to_fundamental_evidence(fundamentals)
    technical_ev = _to_technical_evidence(technicals)
    kronos_ev = KronosEvidence(**kronos_data) if kronos_data else None
    news_ev = NewsEvidence(**news_data) if news_data else None
    recommended_weight = (
        portfolio_result.allocations.get(symbol) if portfolio_result and portfolio_result.allocations else None
    )
    portfolio_ev = (
        PortfolioEvidence(recommended_weight=recommended_weight, expected_sharpe=portfolio_result.sharpe)
        if portfolio_result
        else None
    )

    evidence = CandidateEvidence(
        symbol=symbol,
        exchange="NSE",
        market=MarketEvidence(
            price=last_price,
            market_cap=(
                fundamentals.market_cap
                if fundamentals and fundamentals.market_cap == fundamentals.market_cap
                else None
            ),
            volume=candles[-1].volume if candles else 0,
        ),
        fundamentals=fundamental_ev,
        technical=technical_ev,
        kronos=kronos_ev,
        news=news_ev,
        portfolio=portfolio_ev,
    )

    role_results = await run_candidate_council(llm, evidence, user_profile_payload, plan)
    for role, result in role_results.items():
        db.add(
            CouncilOutput(
                council_run_id=council_run.id,
                instrument_id=instrument.id,
                role=role,
                content=result.content,
                model_name=result.model_name,
                model_version=result.model_version,
                prompt_version=result.prompt_version,
                created_at=datetime.now(timezone.utc),
            )
        )

    sub_scores = {
        "fundamental": calc_fundamental_score(fundamental_ev),
        "technical": calc_technical_score(technical_ev),
        "kronos": calc_kronos_score(kronos_ev),
        "news": calc_news_score(news_ev),
        "portfolio": calc_portfolio_score(portfolio_ev, _max_single_weight_for(risk_profile_label)),
        "risk": calc_risk_fit_score(risk_profile_label, technical_ev),
    }
    breakdown = compute_final_score(
        sub_scores,
        technical_trend=technical_ev.trend if technical_ev else None,
        kronos_direction=kronos_ev.direction if kronos_ev else None,
    )
    recommendation_label = apply_risk_gate(breakdown, sub_scores["risk"], market_regime)

    db.add(
        CandidateScore(
            council_run_id=council_run.id,
            instrument_id=instrument.id,
            fundamental_score=breakdown.fundamental,
            technical_score=breakdown.technical,
            kronos_score=breakdown.kronos,
            news_score=breakdown.news,
            portfolio_score=breakdown.portfolio,
            risk_score=breakdown.risk,
            final_score=breakdown.final_score,
            model_agreement=breakdown.model_agreement,
            data_quality=breakdown.data_quality,
            confidence=breakdown.confidence,
            confidence_band=breakdown.confidence_band,
        )
    )

    # V3 Phase 02 (docs/v3-execution/phase-02.md): record exactly which data
    # version fed this instrument's evidence in THIS run, by natural identity
    # (source/as-of/generated-at), so a later read can bind back to the exact
    # inputs a published report used instead of always showing "most recent."
    await record_manifest_entry(
        db,
        council_run.id,
        instrument.id,
        candle_source=candles[-1].source if candles else None,
        candle_as_of=max((c.timestamp for c in candles), default=None),
        fundamentals_source=fundamentals.source if fundamentals else None,
        fundamentals_as_of_date=fundamentals.as_of_date if fundamentals else None,
        fundamentals_retrieved_at=fundamentals.retrieved_at if fundamentals else None,
        technicals_computed_at=technicals.get("computed_at") if technicals else None,
        kronos_model_version=kronos_data.get("model_version") if kronos_data else None,
        kronos_forecast_horizon=kronos_data.get("forecast_horizon") if kronos_data else None,
        kronos_generated_at=kronos_data.get("generated_at") if kronos_data else None,
    )

    judge = role_results.get("judge")
    bull = role_results.get("bull")
    bear = role_results.get("bear")
    strengths = judge.content.get("strongest_evidence", []) if judge else (bull.content.get("supporting_points", []) if bull else [])
    risks = judge.content.get("major_risks", []) if judge else (bear.content.get("concerns", []) if bear else [])
    rationale = judge.content.get("rationale", "") if judge else "Council judge unavailable; deterministic score/gate still applied."

    horizon_years = 5 if risk_profile_label != "conservative" else 2
    # This stock's own observed risk (volatility band), not the user's risk
    # tolerance -- those are deliberately separate concepts (Section 21).
    stock_risk_level = volatility_band(technical_ev.volatility_30d if technical_ev else None) or "unknown"
    # Composite 4-band tier from the fuller signal set (volatility/drawdown/
    # beta/debt-to-equity) -- distinct from risk_level above, and allowed to
    # stay None when too few signals are available (Section 8: never guess).
    stock_risk_tier = calc_risk_tier(technical_ev, fundamental_ev)
    stock_risk_tier_score, stock_risk_tier_breakdown = calc_risk_tier_score_with_breakdown(technical_ev, fundamental_ev)
    db.add(
        Recommendation(
            user_id=council_run.user_id,
            council_run_id=council_run.id,
            instrument_id=instrument.id,
            recommendation=recommendation_label,
            confidence=breakdown.confidence,
            confidence_band=breakdown.confidence_band,
            score=breakdown.final_score,
            risk_level=stock_risk_level,
            risk_tier=stock_risk_tier,
            risk_tier_score=stock_risk_tier_score,
            risk_tier_breakdown=stock_risk_tier_breakdown,
            suggested_horizon=f"{horizon_years}+ years",
            strengths=strengths,
            risks=risks,
            evidence=evidence.model_dump(),
            rationale=rationale,
            fundamental_score=breakdown.fundamental,
            technical_score=breakdown.technical,
            kronos_score=breakdown.kronos,
            news_score=breakdown.news,
            portfolio_score=breakdown.portfolio,
            risk_score=breakdown.risk,
            model_agreement=breakdown.model_agreement,
            data_quality=breakdown.data_quality,
            generated_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()
    return recommendation_label
