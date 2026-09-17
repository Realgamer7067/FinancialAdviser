"""docs/v3-execution/phase-02.md: GET /api/stocks/{symbol} must bind
fundamentals/technicals/kronos evidence to the exact data version the
recommendation was actually built from (via DataManifestEntry), not always
"most recent as of read time" -- otherwise the page can silently show a
verdict paired with numbers it never saw."""

from datetime import datetime, timedelta, timezone

from app.core.single_user import SINGLE_USER_ID
from app.models.council import CouncilRun
from app.models.fundamentals import FundamentalMetrics
from app.models.manifest import DataManifestEntry
from app.models.market import Instrument
from app.models.recommendation import Recommendation


async def _seed_instrument(db_session, symbol="MANIFESTCO"):
    instrument = Instrument(symbol=symbol, exchange="NSE", name="Manifest Co")
    db_session.add(instrument)
    await db_session.flush()
    return instrument


def _fundamentals_kwargs(instrument_id, *, retrieved_at, roe):
    return dict(
        instrument_id=instrument_id,
        as_of_date=retrieved_at.date(),
        roe=roe,
        revenue_growth=0.1,
        debt_to_equity=0.5,
        pe=20.0,
        net_margin=0.15,
        market_cap=1_000_000.0,
        source="demo_seed",
        retrieved_at=retrieved_at,
    )


async def test_evidence_pins_to_manifest_entry_not_most_recent_fundamentals(client, db_session):
    instrument = await _seed_instrument(db_session)
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=10)

    council_run = CouncilRun(
        user_id=SINGLE_USER_ID, market_regime="normal", universe_size=1, candidates_after_screen=1,
        candidates_after_kronos_news=1, candidates_to_council=1, plan={}, status="done",
        started_at=old_time, completed_at=old_time,
    )
    db_session.add(council_run)
    await db_session.flush()

    # The fundamentals row that existed WHEN the recommendation was generated.
    db_session.add(FundamentalMetrics(**_fundamentals_kwargs(instrument.id, retrieved_at=old_time, roe=0.10)))
    await db_session.flush()

    db_session.add(
        DataManifestEntry(
            council_run_id=council_run.id,
            instrument_id=instrument.id,
            fundamentals_source="demo_seed",
            fundamentals_as_of_date=old_time.date(),
            fundamentals_retrieved_at=old_time,
            created_at=old_time,
        )
    )
    db_session.add(
        Recommendation(
            user_id=SINGLE_USER_ID, council_run_id=council_run.id, instrument_id=instrument.id,
            recommendation="CANDIDATE", confidence=0.7, confidence_band="medium", score=65.0,
            risk_level="moderate", risk_tier="moderate", risk_tier_score=None, risk_tier_breakdown=None,
            suggested_horizon="5+ years", strengths=[], risks=[], evidence={}, rationale="Old snapshot.",
            fundamental_score=60.0, technical_score=None, kronos_score=None, news_score=None,
            portfolio_score=None, risk_score=None, model_agreement=0.6, data_quality=0.4, generated_at=old_time,
        )
    )
    await db_session.commit()

    # A NEWER fundamentals fetch lands after the recommendation was made --
    # e.g. a later pipeline run refreshed the cache. Without manifest binding
    # this would be served as "the" fundamentals for the stock, contradicting
    # what the still-displayed recommendation actually reasoned about.
    db_session.add(FundamentalMetrics(**_fundamentals_kwargs(instrument.id, retrieved_at=now, roe=0.55)))
    await db_session.commit()

    res = await client.get(f"/api/stocks/{instrument.symbol}")
    assert res.status_code == 200
    body = res.json()
    assert body["fundamentals"]["roe"] == 0.10  # the OLD, manifest-pinned value -- not 0.55
    assert body["evidence_is_legacy"] is False


async def test_legacy_recommendation_with_no_manifest_entry_falls_back_and_is_flagged(client, db_session):
    instrument = await _seed_instrument(db_session, "LEGACYCO")
    now = datetime.now(timezone.utc)

    council_run = CouncilRun(
        user_id=SINGLE_USER_ID, market_regime="normal", universe_size=1, candidates_after_screen=1,
        candidates_after_kronos_news=1, candidates_to_council=1, plan={}, status="done",
        started_at=now, completed_at=now,
    )
    db_session.add(council_run)
    await db_session.flush()
    # Deliberately no DataManifestEntry -- simulates a pre-Phase-02 run.
    db_session.add(FundamentalMetrics(**_fundamentals_kwargs(instrument.id, retrieved_at=now, roe=0.20)))
    db_session.add(
        Recommendation(
            user_id=SINGLE_USER_ID, council_run_id=council_run.id, instrument_id=instrument.id,
            recommendation="CANDIDATE", confidence=0.7, confidence_band="medium", score=65.0,
            risk_level="moderate", risk_tier="moderate", risk_tier_score=None, risk_tier_breakdown=None,
            suggested_horizon="5+ years", strengths=[], risks=[], evidence={}, rationale="Legacy.",
            fundamental_score=60.0, technical_score=None, kronos_score=None, news_score=None,
            portfolio_score=None, risk_score=None, model_agreement=0.6, data_quality=0.4, generated_at=now,
        )
    )
    await db_session.commit()

    res = await client.get(f"/api/stocks/{instrument.symbol}")
    assert res.status_code == 200
    body = res.json()
    assert body["fundamentals"]["roe"] == 0.20  # falls back to most-recent, as before
    assert body["evidence_is_legacy"] is True


async def test_no_recommendation_is_not_flagged_legacy(client, db_session):
    await _seed_instrument(db_session, "NOREC")
    await db_session.commit()

    res = await client.get("/api/stocks/NOREC")
    assert res.status_code == 200
    assert res.json()["evidence_is_legacy"] is False
