"""Coverage for POST /api/portfolio/allocate -- turns the latest optimizer
weights into rupee amounts + whole-share counts for a user-entered amount."""

from app.core.single_user import SINGLE_USER_ID
from app.models.council import CouncilRun
from app.models.market import Instrument, MarketCandle
from app.models.portfolio import PortfolioResult
from app.models.recommendation import PortfolioRecommendation
from app.models.user import User
from app.utils.time import utcnow


async def _seed_portfolio(
    db_session,
    allocations: dict[str, float],
    prices: dict[str, float] | None = None,
    sectors: dict[str, str] | None = None,
):
    prices = prices or {}
    sectors = sectors or {}
    db_session.add(User(id=SINGLE_USER_ID, email="user@local", full_name="User", hashed_password="unused"))
    await db_session.flush()

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
        candidate_symbols=list(allocations.keys()),
        allocations=allocations,
        expected_return=0.12,
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
            allocations=allocations,
            notes=[],
            created_at=utcnow(),
        )
    )

    for symbol, price in prices.items():
        instrument = Instrument(symbol=symbol, exchange="NSE", name=symbol, sector=sectors.get(symbol))
        db_session.add(instrument)
        await db_session.flush()
        db_session.add(
            MarketCandle(
                instrument_id=instrument.id,
                interval="1d",
                timestamp=utcnow(),
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1000,
                source="demo_seed",  # matches _force_hermetic_settings' demo_mode=True
                retrieved_at=utcnow(),
            )
        )

    await db_session.commit()


async def test_allocate_computes_shares_and_remainder(client, db_session):
    await _seed_portfolio(db_session, {"TCS": 0.6, "INFY": 0.4}, {"TCS": 300.0, "INFY": 250.0})

    res = await client.post("/api/portfolio/allocate", json={"amount": 1000})
    assert res.status_code == 200
    body = res.json()
    assert body["amount"] == 1000

    by_symbol = {a["symbol"]: a for a in body["allocations"]}
    # 0.6 * 1000 = 600 rupees @ 300/share -> 2 shares -> 600 exactly used
    assert by_symbol["TCS"]["shares"] == 2
    assert by_symbol["TCS"]["rupee_amount"] == 600.0
    # 0.4 * 1000 = 400 rupees @ 250/share -> 1 share -> 250 used, 150 leftover
    assert by_symbol["INFY"]["shares"] == 1
    assert by_symbol["INFY"]["rupee_amount"] == 250.0

    assert body["total_allocated"] == 850.0
    assert body["cash_remainder"] == 150.0


async def test_allocate_falls_back_to_weight_when_price_unknown(client, db_session):
    await _seed_portfolio(db_session, {"NOPRICE": 1.0})

    res = await client.post("/api/portfolio/allocate", json={"amount": 500})
    assert res.status_code == 200
    body = res.json()
    item = body["allocations"][0]
    assert item["symbol"] == "NOPRICE"
    assert item["shares"] is None
    assert item["last_price"] is None
    assert item["rupee_amount"] == 500.0
    assert body["cash_remainder"] == 0.0


async def test_allocate_rejects_non_positive_amount(client, db_session):
    await _seed_portfolio(db_session, {"TCS": 1.0}, {"TCS": 300.0})

    res = await client.post("/api/portfolio/allocate", json={"amount": 0})
    assert res.status_code == 422

    res = await client.post("/api/portfolio/allocate", json={"amount": -100})
    assert res.status_code == 422


async def test_allocate_404s_with_no_portfolio(client):
    res = await client.post("/api/portfolio/allocate", json={"amount": 1000})
    assert res.status_code == 404


async def test_latest_portfolio_includes_sectors_by_symbol(client, db_session):
    await _seed_portfolio(
        db_session,
        {"TCS": 0.6, "INFY": 0.4},
        prices={"TCS": 300.0, "INFY": 250.0},
        sectors={"TCS": "IT", "INFY": "IT"},
    )

    res = await client.get("/api/portfolio/latest")
    assert res.status_code == 200
    body = res.json()
    assert body["sectors"] == {"TCS": "IT", "INFY": "IT"}
    assert body["has_allocation"] is True


async def test_newer_empty_run_supersedes_older_populated_portfolio(client, db_session):
    # docs/v3-execution/CONTRACTS.md C1: run A completed with a real
    # allocation; run B is a LATER completed run that produced no allocation
    # at all (every candidate excluded post-gate). /latest and /allocate must
    # reflect B's outcome (no allocation), never silently keep serving A's
    # stale allocation just because it's the newest row that happens to
    # exist in PortfolioRecommendation.
    db_session.add(User(id=SINGLE_USER_ID, email="user@local", full_name="User", hashed_password="unused"))
    await db_session.flush()

    run_a = CouncilRun(
        user_id=SINGLE_USER_ID, market_regime="normal", universe_size=1, candidates_after_screen=1,
        candidates_after_kronos_news=1, candidates_to_council=1, plan={}, status="done",
        started_at=utcnow(), completed_at=utcnow(),
    )
    db_session.add(run_a)
    await db_session.flush()
    result_a = PortfolioResult(
        user_id=SINGLE_USER_ID, method="mean_variance", candidate_symbols=["TCS"], allocations={"TCS": 1.0},
        expected_return=0.1, expected_volatility=0.2, sharpe=0.5, model_version="test", generated_at=utcnow(),
    )
    db_session.add(result_a)
    await db_session.flush()
    db_session.add(
        PortfolioRecommendation(
            user_id=SINGLE_USER_ID, council_run_id=run_a.id, portfolio_result_id=result_a.id,
            allocations={"TCS": 1.0}, notes=[], created_at=utcnow(),
        )
    )
    await db_session.commit()

    # Run B: completed LATER, no accepted candidates -> no PortfolioRecommendation at all.
    run_b = CouncilRun(
        user_id=SINGLE_USER_ID, market_regime="high_volatility", universe_size=1, candidates_after_screen=0,
        candidates_after_kronos_news=0, candidates_to_council=0, plan={}, status="done",
        started_at=utcnow(), completed_at=utcnow(),
    )
    db_session.add(run_b)
    await db_session.commit()

    res = await client.get("/api/portfolio/latest")
    assert res.status_code == 200
    body = res.json()
    assert body["has_allocation"] is False
    assert body["allocations"] == {}
    assert body["reason"] is not None

    res = await client.post("/api/portfolio/allocate", json={"amount": 1000})
    assert res.status_code == 404
