"""End-to-end smoke test for `run_recommendation_pipeline` (Phase 5) --
previously zero coverage existed for the pipeline, worker, or council wiring.

Runs the real pipeline against 3 real NIFTY50_SEED symbols, with only the
network-touching pieces faked:
- get_fundamental_provider() -> fake (would otherwise hit real Yahoo Finance)
- RSSNewsProvider -> fake, returns no items (would otherwise hit real RSS feeds)
- KronosModel -> fake, returns None (real one downloads model weights from HF
  on first use -- unsafe/slow/non-deterministic in CI)

Left real/unmocked, deliberately:
- Market data: `settings.demo_mode` defaults True, so `get_market_data_provider()`
  already resolves to `DemoMarketDataProvider` (synthetic seeded data, no network).
- FinBERTModel: constructing it touches no network; it's never actually invoked
  here since the fake news provider returns zero items.
- QwenOpenAICompatibleProvider: with no QWEN_API_KEY configured (the test-env
  default), `complete_structured` raises `StructuredOutputError` before any
  network call -- exercising the real "LLM unavailable, degrade gracefully"
  path rather than faking it.
"""

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.recommendation import Recommendation
from app.models.system import RecommendationJob
from app.models.user import RiskProfile, User, UserProfile
from app.pipelines import recommendation_pipeline as pipeline_module
from app.pipelines.progress import JobProgressTracker
from app.providers.base import FundamentalSnapshot

_VALID_RISK_TIERS = {"safer", "moderate", "risky", "riskiest"}
_VALID_CONFIDENCE_BANDS = {"high", "medium", "low"}


class _FakeFundamentalsProvider:
    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(
            symbol=symbol,
            as_of_date=date.today(),
            roe=0.15,
            debt_to_equity=1.0,
            promoter_pledging=0.1,
            revenue_growth=0.1,
            net_margin=0.1,
            pe=20.0,
            retrieved_at=datetime.now(timezone.utc),
            source="fake_test_fixture",
        )

    async def get_universe(self) -> list[str]:
        return []


class _FakeNewsProvider:
    async def fetch_latest(self, since=None):
        return []


class _FakeKronosModel:
    async def forecast(self, symbol: str, candles, horizon: str):
        return None  # deliberately exercises the "missing signal" path


async def test_pipeline_runs_end_to_end_without_network(db_session, monkeypatch):
    monkeypatch.setattr(pipeline_module, "NIFTY50_SEED", pipeline_module.NIFTY50_SEED[:3])

    async def _fake_get_fundamental_provider():
        return _FakeFundamentalsProvider()

    monkeypatch.setattr(pipeline_module, "get_fundamental_provider", _fake_get_fundamental_provider)
    monkeypatch.setattr(pipeline_module, "RSSNewsProvider", lambda: _FakeNewsProvider())
    monkeypatch.setattr(pipeline_module, "KronosModel", lambda: _FakeKronosModel())

    user = User(email="smoke@example.com", hashed_password="unused-single-user-mode", full_name="Smoke Test")
    db_session.add(user)
    await db_session.flush()

    profile = UserProfile(
        user_id=user.id,
        age=30,
        employment_status="salaried",
        monthly_income_range="10_20_lakh",
        monthly_investable_amount=20000.0,
        total_initial_investment=100000.0,
        emergency_fund_status="adequate",
        investment_objective="wealth_creation",
        investment_horizon_years=5,
        liquidity_requirement="low",
        investment_frequency="monthly",
    )
    db_session.add(profile)
    await db_session.flush()

    risk = RiskProfile(
        user_profile_id=profile.id,
        risk_score=60,
        risk_profile="moderate",
        investment_horizon_years=5,
        capital=100000.0,
        monthly_contribution=20000.0,
        objective="wealth_creation",
        liquidity_requirement="low",
    )
    db_session.add(risk)
    await db_session.commit()

    council_run = await pipeline_module.run_recommendation_pipeline(db_session, user.id)

    assert council_run.status == "done"
    assert council_run.universe_size == 3
    assert council_run.candidates_after_screen >= 0

    recommendations = (
        await db_session.execute(select(Recommendation).where(Recommendation.council_run_id == council_run.id))
    ).scalars().all()
    for rec in recommendations:
        assert rec.risk_tier is None or rec.risk_tier in _VALID_RISK_TIERS
        # Phase 0B: previously computed then discarded before reaching persistence.
        assert rec.confidence_band in _VALID_CONFIDENCE_BANDS
        assert (rec.risk_tier is None) == (rec.risk_tier_score is None) == (rec.risk_tier_breakdown is None)
        if rec.risk_tier_score is not None:
            assert 0 <= rec.risk_tier_score <= 100
            assert isinstance(rec.risk_tier_breakdown, dict) and rec.risk_tier_breakdown


async def test_pipeline_writes_job_progress_through_separate_session(db_session, test_engine, monkeypatch):
    """Phase 0A: JobProgressTracker must reach a terminal stage/progress_pct by
    the time the pipeline returns, writing through its own session rather than
    the pipeline's (see app/pipelines/progress.py's module docstring for why).
    The default AsyncSessionLocal would resolve to a real DATABASE_URL, not this
    test's in-memory engine, so JobProgressTracker is swapped for one bound to
    the test's own session factory -- same monkeypatch pattern already used
    above for KronosModel/RSSNewsProvider."""
    monkeypatch.setattr(pipeline_module, "NIFTY50_SEED", pipeline_module.NIFTY50_SEED[:3])

    async def _fake_get_fundamental_provider():
        return _FakeFundamentalsProvider()

    monkeypatch.setattr(pipeline_module, "get_fundamental_provider", _fake_get_fundamental_provider)
    monkeypatch.setattr(pipeline_module, "RSSNewsProvider", lambda: _FakeNewsProvider())
    monkeypatch.setattr(pipeline_module, "KronosModel", lambda: _FakeKronosModel())

    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(
        pipeline_module,
        "JobProgressTracker",
        lambda job_id, **kwargs: JobProgressTracker(job_id, session_factory=test_session_factory, **kwargs),
    )

    user = User(email="smoke-progress@example.com", hashed_password="unused-single-user-mode", full_name="Smoke Test")
    db_session.add(user)
    await db_session.flush()

    profile = UserProfile(
        user_id=user.id,
        age=30,
        employment_status="salaried",
        monthly_income_range="10_20_lakh",
        monthly_investable_amount=20000.0,
        total_initial_investment=100000.0,
        emergency_fund_status="adequate",
        investment_objective="wealth_creation",
        investment_horizon_years=5,
        liquidity_requirement="low",
        investment_frequency="monthly",
    )
    db_session.add(profile)
    await db_session.flush()

    risk = RiskProfile(
        user_profile_id=profile.id,
        risk_score=60,
        risk_profile="moderate",
        investment_horizon_years=5,
        capital=100000.0,
        monthly_contribution=20000.0,
        objective="wealth_creation",
        liquidity_requirement="low",
    )
    db_session.add(risk)

    job = RecommendationJob(user_id=user.id, status="running", created_at=datetime.now(timezone.utc))
    db_session.add(job)
    await db_session.commit()

    await pipeline_module.run_recommendation_pipeline(db_session, user.id, job_id=job.id)

    refreshed = (await db_session.execute(select(RecommendationJob).where(RecommendationJob.id == job.id))).scalar_one()
    # The pipeline's last set_stage call is "finalizing" (band start 98%, per
    # STAGE_BANDS) -- the final 98->100 jump happens when worker.py flips
    # status to "done" separately, not tracked as its own stage.
    assert refreshed.stage == "finalizing"
    assert refreshed.progress_pct == 98.0
    assert refreshed.stage_detail is not None

    # Regression check for worker.py's write-back pattern: `job` here is the
    # SAME stale in-memory object _process_job would hold (loaded before the
    # pipeline ran, never refreshed since -- JobProgressTracker wrote through
    # separate sessions). Setting only status/completed_at and committing must
    # emit an UPDATE for just those columns, not clobber stage/progress_pct
    # back to whatever this stale copy held (None) at load time.
    job.status = "done"
    await db_session.commit()
    reloaded_after_status_flip = (
        await db_session.execute(select(RecommendationJob).where(RecommendationJob.id == job.id))
    ).scalar_one()
    assert reloaded_after_status_flip.status == "done"
    assert reloaded_after_status_flip.stage == "finalizing"
    assert reloaded_after_status_flip.progress_pct == 98.0
