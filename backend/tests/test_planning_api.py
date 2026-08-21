"""Coverage for GET /api/planning/sip-projection and POST /api/planning/goal-sip
-- default-resolution from RiskProfile/PortfolioResult, and the assumed_return
flag that must never silently present a rate as fact."""

from app.api.planning import FALLBACK_ANNUAL_RATE_PCT
from app.core.single_user import SINGLE_USER_ID
from app.models.council import CouncilRun
from app.models.portfolio import PortfolioResult
from app.models.recommendation import PortfolioRecommendation
from app.models.user import RiskProfile, User, UserProfile
from app.utils.time import utcnow


async def _seed_risk_profile(db_session, monthly_contribution=10000.0, investment_horizon_years=10):
    db_session.add(User(id=SINGLE_USER_ID, email="user@local", full_name="User", hashed_password="unused"))
    await db_session.flush()

    profile = UserProfile(
        user_id=SINGLE_USER_ID,
        age=30,
        employment_status="salaried",
        monthly_income_range="50k_100k",
        monthly_investable_amount=monthly_contribution,
        total_initial_investment=100000.0,
        emergency_fund_status="full",
        investment_objective="wealth_building",
        investment_horizon_years=investment_horizon_years,
        liquidity_requirement="low",
        investment_frequency="monthly",
    )
    db_session.add(profile)
    await db_session.flush()

    risk_profile = RiskProfile(
        user_profile_id=profile.id,
        risk_score=60,
        risk_profile="moderate",
        investment_horizon_years=investment_horizon_years,
        capital=100000.0,
        monthly_contribution=monthly_contribution,
        objective="wealth_building",
        liquidity_requirement="low",
    )
    db_session.add(risk_profile)
    await db_session.commit()


async def _seed_portfolio_result(db_session, expected_return=0.15):
    council_run = CouncilRun(
        user_id=SINGLE_USER_ID,
        market_regime="normal",
        universe_size=1,
        candidates_after_screen=1,
        candidates_after_kronos_news=1,
        candidates_to_council=1,
        plan={},
        status="done",
        started_at=utcnow(),
    )
    db_session.add(council_run)
    await db_session.flush()

    result = PortfolioResult(
        user_id=SINGLE_USER_ID,
        method="mean_variance",
        candidate_symbols=["TCS"],
        allocations={"TCS": 1.0},
        expected_return=expected_return,
        expected_volatility=0.2,
        sharpe=0.6,
        model_version="test",
        generated_at=utcnow(),
    )
    db_session.add(result)
    await db_session.flush()

    db_session.add(
        PortfolioRecommendation(
            user_id=SINGLE_USER_ID,
            council_run_id=council_run.id,
            portfolio_result_id=result.id,
            allocations={"TCS": 1.0},
            notes=[],
            created_at=utcnow(),
        )
    )
    await db_session.commit()


async def test_sip_projection_with_explicit_params_not_assumed(client):
    res = await client.get(
        "/api/planning/sip-projection",
        params={"monthly_amount": 5000, "years": 3, "annual_rate_pct": 12},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["assumed_return"] is False
    assert body["annual_rate_pct"] == 12
    assert len(body["points"]) == 3
    assert body["points"][-1]["invested_cumulative"] == 5000 * 3 * 12


async def test_sip_projection_404s_without_profile_or_explicit_params(client):
    res = await client.get("/api/planning/sip-projection")
    assert res.status_code == 404


async def test_sip_projection_defaults_from_risk_profile_and_flags_assumed_rate(client, db_session):
    await _seed_risk_profile(db_session, monthly_contribution=8000.0, investment_horizon_years=5)

    res = await client.get("/api/planning/sip-projection")
    assert res.status_code == 200
    body = res.json()
    assert body["monthly_amount"] == 8000.0
    assert body["years"] == 5
    assert body["assumed_return"] is True
    assert body["annual_rate_pct"] == FALLBACK_ANNUAL_RATE_PCT


async def test_sip_projection_uses_portfolio_expected_return_not_assumed(client, db_session):
    await _seed_risk_profile(db_session)
    await _seed_portfolio_result(db_session, expected_return=0.15)

    res = await client.get("/api/planning/sip-projection")
    assert res.status_code == 200
    body = res.json()
    assert body["assumed_return"] is False
    assert body["annual_rate_pct"] == 15.0


async def test_goal_sip_returns_positive_required_amount(client, db_session):
    res = await client.post("/api/planning/goal-sip", json={"target_amount": 1000000, "years": 10})
    assert res.status_code == 200
    body = res.json()
    assert body["required_monthly_sip"] > 0
    assert body["assumed_return"] is True


async def test_goal_sip_rejects_non_positive_inputs(client):
    res = await client.post("/api/planning/goal-sip", json={"target_amount": 0, "years": 10})
    assert res.status_code == 422

    res = await client.post("/api/planning/goal-sip", json={"target_amount": 1000, "years": 0})
    assert res.status_code == 422
