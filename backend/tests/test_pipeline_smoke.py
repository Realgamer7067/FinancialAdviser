"""End-to-end smoke test for `run_recommendation_pipeline` (Phase 5) --
previously zero coverage existed for the pipeline, worker, or council wiring.

Runs the real pipeline against 3 real NIFTY50_SEED symbols, with only the
network-touching pieces faked:
- YFinanceFundamentalProvider -> fake (would otherwise hit real Yahoo Finance)
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

from app.core.security import hash_password
from app.models.user import RiskProfile, User, UserProfile
from app.pipelines import recommendation_pipeline as pipeline_module
from app.providers.base import FundamentalSnapshot


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
    monkeypatch.setattr(pipeline_module, "YFinanceFundamentalProvider", lambda: _FakeFundamentalsProvider())
    monkeypatch.setattr(pipeline_module, "RSSNewsProvider", lambda: _FakeNewsProvider())
    monkeypatch.setattr(pipeline_module, "KronosModel", lambda: _FakeKronosModel())

    user = User(email="smoke@example.com", hashed_password=hash_password("x"), full_name="Smoke Test")
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
