"""Coverage for GET /api/stocks/{symbol} -- the Phase 0B additions: full
technicals passthrough, multi-horizon Kronos, and council transparency."""

from datetime import datetime, timezone

from app.core.single_user import SINGLE_USER_ID
from app.models.analysis import KronosPrediction, TechnicalFeatures
from app.models.council import CouncilOutput, CouncilRun
from app.models.market import Instrument
from app.models.recommendation import Recommendation


async def _seed_instrument(db_session, symbol="TESTCO"):
    instrument = Instrument(symbol=symbol, exchange="NSE", name="Test Co")
    db_session.add(instrument)
    await db_session.flush()
    return instrument


async def test_technicals_expose_moving_averages_and_bollinger_bands(client, db_session):
    instrument = await _seed_instrument(db_session, "TESTCO")
    db_session.add(
        TechnicalFeatures(
            instrument_id=instrument.id,
            timeframe="1d",
            as_of=datetime.now(timezone.utc),
            sma_20=100.0,
            sma_50=98.0,
            sma_200=95.0,
            ema_12=101.0,
            ema_26=99.0,
            rsi_14=55.0,
            macd_hist=0.5,
            bb_upper=105.0,
            bb_lower=95.0,
            volatility_30d=0.2,
            drawdown_1y=-0.1,
            beta=1.1,
            trend="bullish",
            computed_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    res = await client.get("/api/stocks/TESTCO")
    assert res.status_code == 200
    technicals = res.json()["technicals"]
    assert technicals["sma_20"] == 100.0
    assert technicals["sma_50"] == 98.0
    assert technicals["sma_200"] == 95.0
    assert technicals["ema_12"] == 101.0
    assert technicals["ema_26"] == 99.0
    assert technicals["bb_upper"] == 105.0
    assert technicals["bb_lower"] == 95.0


async def test_kronos_horizons_reports_only_persisted_horizons(client, db_session):
    # A stock screened out before the council loop only ever gets a 30d row
    # (Phase 0B #4) -- the endpoint must report exactly what exists, not
    # assume all 3 horizons are present.
    instrument = await _seed_instrument(db_session, "SCREENEDOUT")
    db_session.add(
        KronosPrediction(
            instrument_id=instrument.id,
            forecast_horizon="30d",
            direction="bullish",
            predicted_return=0.05,
            predicted_return_p10=0.02,
            predicted_return_p90=0.08,
            direction_agreement=0.9,
            sample_count=8,
            confidence=0.5,
            input_timeframe="200_daily_bars",
            model_version="test-v1",
            generated_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    res = await client.get("/api/stocks/SCREENEDOUT")
    body = res.json()
    assert body["kronos"]["forecast_horizon"] == "30d"
    assert [h["forecast_horizon"] for h in body["kronos_horizons"]] == ["30d"]


async def test_kronos_horizons_reports_all_three_for_a_council_candidate(client, db_session):
    instrument = await _seed_instrument(db_session, "COUNCILPICK")
    for horizon, ret in (("7d", 0.01), ("30d", 0.05), ("90d", 0.12)):
        db_session.add(
            KronosPrediction(
                instrument_id=instrument.id,
                forecast_horizon=horizon,
                direction="bullish",
                predicted_return=ret,
                predicted_return_p10=ret - 0.02,
                predicted_return_p90=ret + 0.02,
                direction_agreement=0.9,
                sample_count=8,
                confidence=0.5,
                input_timeframe="200_daily_bars",
                model_version="test-v1",
                generated_at=datetime.now(timezone.utc),
            )
        )
    await db_session.commit()

    res = await client.get("/api/stocks/COUNCILPICK")
    body = res.json()
    assert body["kronos"]["forecast_horizon"] == "30d"
    assert {h["forecast_horizon"] for h in body["kronos_horizons"]} == {"7d", "30d", "90d"}


async def test_council_outputs_empty_when_no_council_run(client, db_session):
    await _seed_instrument(db_session, "NOCOUNCIL")
    await db_session.commit()

    res = await client.get("/api/stocks/NOCOUNCIL")
    body = res.json()
    assert body["recommendation"] is None


async def test_council_outputs_populated_for_this_instrument_and_run(client, db_session):
    instrument = await _seed_instrument(db_session, "HASCOUNCIL")
    council_run = CouncilRun(
        user_id=SINGLE_USER_ID,
        market_regime="neutral",
        universe_size=1,
        candidates_after_screen=1,
        candidates_after_kronos_news=1,
        candidates_to_council=1,
        plan={},
        status="done",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(council_run)
    await db_session.flush()

    db_session.add(
        CouncilOutput(
            council_run_id=council_run.id,
            instrument_id=instrument.id,
            role="bull",
            content={"supporting_points": ["strong ROE"], "summary": "Looks solid."},
            model_name="Qwen",
            model_version="test-v1",
            prompt_version="v1",
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        Recommendation(
            user_id=SINGLE_USER_ID,
            council_run_id=council_run.id,
            instrument_id=instrument.id,
            recommendation="CANDIDATE",
            confidence=0.8,
            confidence_band="high",
            score=70.0,
            risk_level="moderate",
            risk_tier="moderate",
            risk_tier_score=45.0,
            risk_tier_breakdown={"volatility_30d": 40.0, "beta": 50.0},
            suggested_horizon="5+ years",
            strengths=["strong ROE"],
            risks=[],
            evidence={},
            rationale="Solid fundamentals.",
            fundamental_score=80.0,
            technical_score=60.0,
            kronos_score=None,
            news_score=None,
            portfolio_score=None,
            risk_score=70.0,
            model_agreement=0.75,
            data_quality=0.6,
            generated_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    res = await client.get("/api/stocks/HASCOUNCIL")
    rec = res.json()["recommendation"]
    assert rec["confidence_band"] == "high"
    assert rec["risk_tier_score"] == 45.0
    assert rec["risk_tier_breakdown"] == {"volatility_30d": 40.0, "beta": 50.0}
    assert len(rec["council_outputs"]) == 1
    assert rec["council_outputs"][0]["role"] == "bull"
    assert rec["council_outputs"][0]["content"]["summary"] == "Looks solid."
