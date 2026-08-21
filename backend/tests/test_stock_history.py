"""Coverage for GET /api/stocks/{symbol}/history -- new endpoint reading
already-persisted MarketCandle rows for the price-history chart."""

from datetime import datetime, timedelta, timezone

from app.models.market import Instrument, MarketCandle


async def _seed_candles(db_session, symbol="TESTCO", days=10):
    instrument = Instrument(symbol=symbol, exchange="NSE", name="Test Co")
    db_session.add(instrument)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    for i in range(days):
        db_session.add(
            MarketCandle(
                instrument_id=instrument.id,
                interval="1d",
                timestamp=now - timedelta(days=days - i),
                open=100 + i,
                high=101 + i,
                low=99 + i,
                close=100 + i,
                volume=1000,
                source="test_fixture",
                retrieved_at=now,
            )
        )
    await db_session.commit()
    return instrument


async def test_history_returns_points_in_ascending_order(client, db_session):
    await _seed_candles(db_session, symbol="TESTCO", days=5)

    res = await client.get("/api/stocks/TESTCO/history")
    assert res.status_code == 200
    body = res.json()
    assert body["symbol"] == "TESTCO"
    assert body["interval"] == "1d"
    assert len(body["points"]) == 5
    timestamps = [p["timestamp"] for p in body["points"]]
    assert timestamps == sorted(timestamps)


async def test_history_days_param_clamps_to_valid_range(client, db_session):
    await _seed_candles(db_session, symbol="TESTCO2", days=3)

    res = await client.get("/api/stocks/TESTCO2/history?days=999999")
    assert res.status_code == 200
    assert len(res.json()["points"]) == 3


async def test_history_unknown_symbol_404s(client):
    res = await client.get("/api/stocks/NOPE/history")
    assert res.status_code == 404
