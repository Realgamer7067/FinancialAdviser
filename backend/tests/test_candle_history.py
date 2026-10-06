"""V3 Phase 02: refreshing a symbol's candle cache must soft-supersede prior
rows instead of hard-deleting them, so a published Recommendation's evidence
(computed from a specific historical candle set) stays reconstructable.

Covers:
- idempotent re-import of byte-identical data is a no-op (no new superseded
  rows, no duplicate current rows).
- an overlapping refresh with genuinely changed values supersedes the old
  rows (kept, still queryable) rather than deleting them, and the new rows
  become the only current ones for that key.
- the "current" read path (`_get_cached_candles`) only ever sees
  non-superseded rows.
- total row count in the table increases across a refresh with changed data
  (proof history was preserved, not destroyed) instead of staying flat.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.market import Instrument, MarketCandle
from app.pipelines.recommendation_pipeline import _get_cached_candles, _persist_candles
from app.providers.base import Candle


async def _make_instrument(db_session, symbol="TESTCO"):
    instrument = Instrument(symbol=symbol, exchange="NSE", name="Test Co")
    db_session.add(instrument)
    await db_session.flush()
    return instrument


def _candles(base_day: datetime, n: int, *, close_offset: float = 0.0, source: str = "demo_seed"):
    out = []
    for i in range(n):
        ts = base_day - timedelta(days=n - i)
        out.append(
            Candle(
                timestamp=ts,
                open=100 + i + close_offset,
                high=101 + i + close_offset,
                low=99 + i + close_offset,
                close=100 + i + close_offset,
                volume=1000,
                source=source,
                retrieved_at=base_day,
                adjusted=True,
            )
        )
    return out


async def _count_all_rows(db_session, instrument_id) -> int:
    result = await db_session.execute(
        select(func.count()).select_from(MarketCandle).where(MarketCandle.instrument_id == instrument_id)
    )
    return result.scalar_one()


async def _count_current_rows(db_session, instrument_id) -> int:
    result = await db_session.execute(
        select(func.count())
        .select_from(MarketCandle)
        .where(MarketCandle.instrument_id == instrument_id, MarketCandle.superseded_at.is_(None))
    )
    return result.scalar_one()


async def test_identical_reimport_is_idempotent_noop(db_session):
    instrument = await _make_instrument(db_session)
    now = datetime.now(timezone.utc)
    batch = _candles(now, 10)

    await _persist_candles(db_session, instrument.id, batch)
    await db_session.commit()
    total_after_first = await _count_all_rows(db_session, instrument.id)
    current_after_first = await _count_current_rows(db_session, instrument.id)
    assert total_after_first == 10
    assert current_after_first == 10

    # Re-import byte-identical data.
    await _persist_candles(db_session, instrument.id, _candles(now, 10))
    await db_session.commit()

    total_after_second = await _count_all_rows(db_session, instrument.id)
    current_after_second = await _count_current_rows(db_session, instrument.id)
    assert total_after_second == total_after_first, "identical re-import must not create new rows"
    assert current_after_second == current_after_first, "identical re-import must not supersede current rows"


async def test_changed_values_supersede_instead_of_delete(db_session):
    instrument = await _make_instrument(db_session)
    now = datetime.now(timezone.utc)

    await _persist_candles(db_session, instrument.id, _candles(now, 10))
    await db_session.commit()
    total_before = await _count_all_rows(db_session, instrument.id)
    original_row_ids = {
        r.id
        for r in (
            await db_session.execute(select(MarketCandle).where(MarketCandle.instrument_id == instrument.id))
        )
        .scalars()
        .all()
    }
    assert len(original_row_ids) == 10

    # Refresh with genuinely different OHLCV values for the same timestamps.
    await _persist_candles(db_session, instrument.id, _candles(now, 10, close_offset=5.0))
    await db_session.commit()

    total_after = await _count_all_rows(db_session, instrument.id)
    current_after = await _count_current_rows(db_session, instrument.id)

    # History preserved, not destroyed: row count grows rather than staying
    # flat or shrinking.
    assert total_after > total_before
    assert total_after == total_before + 10

    # Exactly one current set for the key.
    assert current_after == 10

    # The original rows are still present in the table, but now marked
    # superseded rather than gone.
    superseded_rows = (
        await db_session.execute(
            select(MarketCandle).where(
                MarketCandle.instrument_id == instrument.id,
                MarketCandle.superseded_at.is_not(None),
            )
        )
    ).scalars().all()
    assert {r.id for r in superseded_rows} == original_row_ids

    # Current rows are a disjoint, freshly-inserted set carrying the
    # refreshed values.
    current_rows = (
        await db_session.execute(
            select(MarketCandle).where(
                MarketCandle.instrument_id == instrument.id,
                MarketCandle.superseded_at.is_(None),
            )
        )
    ).scalars().all()
    assert {r.id for r in current_rows}.isdisjoint(original_row_ids)
    assert all(row.close >= 105 for row in current_rows)


async def test_cached_read_only_sees_current_rows(db_session):
    instrument = await _make_instrument(db_session)
    now = datetime.now(timezone.utc)

    await _persist_candles(db_session, instrument.id, _candles(now, 10))
    await db_session.commit()
    await _persist_candles(db_session, instrument.id, _candles(now, 10, close_offset=5.0))
    await db_session.commit()

    cached = await _get_cached_candles(db_session, instrument.id)
    assert cached is not None
    assert len(cached) == 10
    assert all(c.close >= 105 for c in cached)


async def test_import_batch_id_shared_across_batch_and_new_on_refresh(db_session):
    instrument = await _make_instrument(db_session)
    now = datetime.now(timezone.utc)

    await _persist_candles(db_session, instrument.id, _candles(now, 5))
    await db_session.commit()
    first_rows = (
        await db_session.execute(select(MarketCandle).where(MarketCandle.instrument_id == instrument.id))
    ).scalars().all()
    first_batch_ids = {r.import_batch_id for r in first_rows}
    assert len(first_batch_ids) == 1
    assert None not in first_batch_ids

    await _persist_candles(db_session, instrument.id, _candles(now, 5, close_offset=1.0))
    await db_session.commit()
    current_rows = (
        await db_session.execute(
            select(MarketCandle).where(
                MarketCandle.instrument_id == instrument.id,
                MarketCandle.superseded_at.is_(None),
            )
        )
    ).scalars().all()
    second_batch_ids = {r.import_batch_id for r in current_rows}
    assert len(second_batch_ids) == 1
    assert second_batch_ids != first_batch_ids
