"""Coverage for GET /api/recommendations/latest -- Phase 0B's council-outputs
grouping query and the new confidence_band/risk_tier_score fields."""

from datetime import datetime, timezone

from app.core.single_user import SINGLE_USER_ID
from app.models.council import CouncilOutput, CouncilRun
from app.models.market import Instrument
from app.models.recommendation import Recommendation


async def _seed_run_with_two_candidates(db_session):
    council_run = CouncilRun(
        user_id=SINGLE_USER_ID,
        market_regime="neutral",
        universe_size=2,
        candidates_after_screen=2,
        candidates_after_kronos_news=2,
        candidates_to_council=2,
        plan={},
        status="done",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(council_run)
    await db_session.flush()

    tcs = Instrument(symbol="TCS", exchange="NSE", name="TCS Ltd")
    infy = Instrument(symbol="INFY", exchange="NSE", name="Infosys")
    db_session.add_all([tcs, infy])
    await db_session.flush()

    # Only TCS gets council_outputs -- INFY exercises the "no rows for this
    # instrument" branch of the grouping query.
    db_session.add(
        CouncilOutput(
            council_run_id=council_run.id,
            instrument_id=tcs.id,
            role="judge",
            content={"rationale": "Consistent grower.", "strongest_evidence": [], "contradictory_evidence": [],
                     "missing_data": [], "model_disagreements": [], "major_risks": []},
            model_name="Qwen",
            model_version="test-v1",
            prompt_version="v1",
            created_at=datetime.now(timezone.utc),
        )
    )

    for instrument, score in ((tcs, 82.0), (infy, 55.0)):
        db_session.add(
            Recommendation(
                user_id=SINGLE_USER_ID,
                council_run_id=council_run.id,
                instrument_id=instrument.id,
                recommendation="STRONG_CANDIDATE" if score > 80 else "WATCHLIST",
                confidence=0.8,
                confidence_band="high",
                score=score,
                risk_level="moderate",
                risk_tier="moderate",
                risk_tier_score=40.0,
                risk_tier_breakdown={"volatility_30d": 40.0},
                suggested_horizon="5+ years",
                strengths=[],
                risks=[],
                evidence={},
                rationale="test",
                fundamental_score=None,
                technical_score=None,
                kronos_score=None,
                news_score=None,
                portfolio_score=None,
                risk_score=None,
                model_agreement=0.7,
                data_quality=0.5,
                generated_at=datetime.now(timezone.utc),
            )
        )
    await db_session.commit()
    return council_run


async def test_latest_recommendations_populates_council_outputs_per_instrument(client, db_session):
    await _seed_run_with_two_candidates(db_session)

    res = await client.get("/api/recommendations/latest")
    assert res.status_code == 200
    cards = {c["symbol"]: c for c in res.json()["recommendations"]}

    assert len(cards["TCS"]["council_outputs"]) == 1
    assert cards["TCS"]["council_outputs"][0]["role"] == "judge"
    assert cards["INFY"]["council_outputs"] == []

    assert cards["TCS"]["confidence_band"] == "high"
    assert cards["TCS"]["risk_tier_score"] == 40.0
    assert cards["TCS"]["risk_tier_breakdown"] == {"volatility_30d": 40.0}


async def test_latest_recommendations_404s_with_no_runs(client):
    res = await client.get("/api/recommendations/latest")
    assert res.status_code == 404


async def test_latest_recommendations_prefers_newer_zero_row_run_over_older_populated_one(client, db_session):
    # docs/V2-RETHINK.md P0: a newer completed run that legitimately produced
    # zero recommendations (a "no opportunity" outcome) must never be skipped
    # in favor of an older run that happens to have rows -- that would show
    # the user a stale opportunity as if it were current.
    older_run = CouncilRun(
        user_id=SINGLE_USER_ID,
        market_regime="neutral",
        universe_size=1,
        candidates_after_screen=1,
        candidates_after_kronos_news=1,
        candidates_to_council=1,
        plan={},
        status="done",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(older_run)
    await db_session.flush()
    tcs = Instrument(symbol="TCS", exchange="NSE", name="TCS Ltd")
    db_session.add(tcs)
    await db_session.flush()
    db_session.add(
        Recommendation(
            user_id=SINGLE_USER_ID,
            council_run_id=older_run.id,
            instrument_id=tcs.id,
            recommendation="STRONG_CANDIDATE",
            confidence=0.8,
            confidence_band="high",
            score=82.0,
            risk_level="moderate",
            risk_tier="moderate",
            risk_tier_score=40.0,
            risk_tier_breakdown={},
            suggested_horizon="5+ years",
            strengths=[],
            risks=[],
            evidence={},
            rationale="test",
            fundamental_score=None,
            technical_score=None,
            kronos_score=None,
            news_score=None,
            portfolio_score=None,
            risk_score=None,
            model_agreement=0.7,
            data_quality=0.5,
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )

    newer_zero_row_run = CouncilRun(
        user_id=SINGLE_USER_ID,
        market_regime="high_volatility",
        universe_size=1,
        candidates_after_screen=0,
        candidates_after_kronos_news=0,
        candidates_to_council=0,
        plan={},
        status="done",
        started_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    db_session.add(newer_zero_row_run)
    await db_session.commit()

    res = await client.get("/api/recommendations/latest")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == str(newer_zero_row_run.id)
    assert body["recommendations"] == []
