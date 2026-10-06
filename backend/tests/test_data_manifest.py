"""Coverage for the V3 Phase 02 data-manifest primitive (app/models/manifest.py,
app/services/manifest.py) -- record_manifest_entry / get_manifest_entry."""

from datetime import date, datetime, timezone

from app.core.single_user import SINGLE_USER_ID
from app.models.council import CouncilRun
from app.models.market import Instrument
from app.services.manifest import get_manifest_entry, is_legacy, record_manifest_entry


async def _make_council_run(db_session, *, market_regime="neutral"):
    council_run = CouncilRun(
        user_id=SINGLE_USER_ID,
        market_regime=market_regime,
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
    return council_run


async def _make_instrument(db_session, symbol="TCS"):
    instrument = Instrument(symbol=symbol, exchange="NSE", name=f"{symbol} Ltd")
    db_session.add(instrument)
    await db_session.flush()
    return instrument


async def test_record_manifest_entry_stores_all_fields(db_session):
    council_run = await _make_council_run(db_session)
    instrument = await _make_instrument(db_session)

    candle_as_of = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    fundamentals_retrieved_at = datetime(2026, 8, 30, 6, 0, tzinfo=timezone.utc)
    technicals_computed_at = datetime(2026, 9, 1, 9, 30, tzinfo=timezone.utc)
    kronos_generated_at = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)

    entry = await record_manifest_entry(
        db_session,
        council_run.id,
        instrument.id,
        candle_source="yahoo_finance",
        candle_as_of=candle_as_of,
        fundamentals_source="nifty50_seed_dataset_v1",
        fundamentals_as_of_date=date(2026, 6, 30),
        fundamentals_retrieved_at=fundamentals_retrieved_at,
        technicals_computed_at=technicals_computed_at,
        kronos_model_version="kronos-v1",
        kronos_forecast_horizon="30d",
        kronos_generated_at=kronos_generated_at,
    )
    entry_id = entry.id
    await db_session.commit()

    # Force a real SELECT instead of reading back the same in-memory object
    # out of the session identity map (expire_on_commit=False in conftest
    # would otherwise let this pass even if values were mis-persisted).
    db_session.expunge_all()
    fetched = await get_manifest_entry(db_session, council_run.id, instrument.id)

    assert fetched is not None
    assert fetched.id == entry_id
    assert fetched.council_run_id == council_run.id
    assert fetched.instrument_id == instrument.id
    assert fetched.candle_source == "yahoo_finance"
    # SQLite has no tz-aware datetime storage -- a genuine re-read comes back
    # naive, so compare against the naive equivalent rather than the
    # tz-aware value that was written.
    assert fetched.candle_as_of == candle_as_of.replace(tzinfo=None)
    assert fetched.fundamentals_source == "nifty50_seed_dataset_v1"
    assert fetched.fundamentals_as_of_date == date(2026, 6, 30)
    assert fetched.fundamentals_retrieved_at == fundamentals_retrieved_at.replace(tzinfo=None)
    assert fetched.technicals_computed_at == technicals_computed_at.replace(tzinfo=None)
    assert fetched.kronos_model_version == "kronos-v1"
    assert fetched.kronos_forecast_horizon == "30d"
    assert fetched.kronos_generated_at == kronos_generated_at.replace(tzinfo=None)
    assert fetched.created_at is not None


async def test_get_manifest_entry_returns_none_for_legacy_run(db_session):
    council_run = await _make_council_run(db_session)
    instrument = await _make_instrument(db_session)
    await db_session.commit()

    entry = await get_manifest_entry(db_session, council_run.id, instrument.id)
    assert entry is None
    assert is_legacy(entry) is True


async def test_get_manifest_entry_returns_exact_match(db_session):
    council_run = await _make_council_run(db_session)
    instrument = await _make_instrument(db_session)

    created = await record_manifest_entry(
        db_session,
        council_run.id,
        instrument.id,
        candle_source="yahoo_finance",
        candle_as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        fundamentals_source="nifty50_seed_dataset_v1",
        fundamentals_as_of_date=date(2026, 6, 30),
        fundamentals_retrieved_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        technicals_computed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        kronos_model_version="kronos-v1",
        kronos_forecast_horizon="30d",
        kronos_generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    await db_session.commit()

    fetched = await get_manifest_entry(db_session, council_run.id, instrument.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert is_legacy(fetched) is False


async def test_two_council_runs_same_instrument_produce_independent_entries(db_session):
    instrument = await _make_instrument(db_session)
    run_a = await _make_council_run(db_session, market_regime="neutral")
    run_b = await _make_council_run(db_session, market_regime="high_volatility")

    entry_a = await record_manifest_entry(
        db_session,
        run_a.id,
        instrument.id,
        candle_source="yahoo_finance",
        candle_as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        fundamentals_source="nifty50_seed_dataset_v1",
        fundamentals_as_of_date=date(2026, 6, 30),
        fundamentals_retrieved_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        technicals_computed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        kronos_model_version="kronos-v1",
        kronos_forecast_horizon="30d",
        kronos_generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    entry_b = await record_manifest_entry(
        db_session,
        run_b.id,
        instrument.id,
        candle_source="yahoo_finance",
        candle_as_of=datetime(2026, 9, 8, tzinfo=timezone.utc),
        fundamentals_source="nifty50_seed_dataset_v1",
        fundamentals_as_of_date=date(2026, 6, 30),
        fundamentals_retrieved_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        technicals_computed_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
        kronos_model_version="kronos-v2",
        kronos_forecast_horizon="30d",
        kronos_generated_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )
    entry_a_id, entry_b_id = entry_a.id, entry_b.id
    await db_session.commit()
    db_session.expunge_all()

    assert entry_a_id != entry_b_id

    fetched_a = await get_manifest_entry(db_session, run_a.id, instrument.id)
    fetched_b = await get_manifest_entry(db_session, run_b.id, instrument.id)

    assert fetched_a.id == entry_a_id
    assert fetched_a.kronos_model_version == "kronos-v1"
    assert fetched_b.id == entry_b_id
    assert fetched_b.kronos_model_version == "kronos-v2"


async def test_nullable_fields_round_trip_as_none(db_session):
    council_run = await _make_council_run(db_session)
    instrument = await _make_instrument(db_session)

    entry = await record_manifest_entry(
        db_session,
        council_run.id,
        instrument.id,
        candle_source="yahoo_finance",
        candle_as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        fundamentals_source="nifty50_seed_dataset_v1",
        fundamentals_as_of_date=date(2026, 6, 30),
        fundamentals_retrieved_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        technicals_computed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        kronos_model_version=None,
        kronos_forecast_horizon=None,
        kronos_generated_at=None,
    )
    await db_session.commit()
    db_session.expunge_all()

    fetched = await get_manifest_entry(db_session, council_run.id, instrument.id)
    assert fetched.kronos_model_version is None
    assert fetched.kronos_forecast_horizon is None
    assert fetched.kronos_generated_at is None
