"""Angel One instrument master, latest quotes and the watchlist (Portfolio
Intelligence Engine, post-Phase-09). Read-only market data: nothing here can
place an order. Quotes are the LATEST observation per instrument with their own
retrieval/exchange times; they never rewrite a saved valuation."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class BrokerInstrument(Base, UUIDPKMixin):
    """Angel's (exchange, token) identity for a tradable instrument. Tokens are source-specific and may
    change; the canonical identity stays on `instruments` (when matched)."""

    __tablename__ = "broker_instruments"
    __table_args__ = (UniqueConstraint("provider", "exchange", "token", name="uq_broker_instruments_token"),)

    provider: Mapped[str] = mapped_column(String, default="angel_one")
    exchange: Mapped[str] = mapped_column(String)
    token: Mapped[str] = mapped_column(String)
    trading_symbol: Mapped[str] = mapped_column(String, index=True)   # e.g. RELIANCE-EQ
    symbol: Mapped[str] = mapped_column(String, index=True)           # e.g. RELIANCE
    name: Mapped[str] = mapped_column(String)
    series: Mapped[str] = mapped_column(String, default="EQ")
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"), nullable=True, index=True)
    match_basis: Mapped[str | None] = mapped_column(String, nullable=True)  # symbol_series_match | null
    security_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("securities.id"), nullable=True, index=True)  # catalogue link (P0)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketQuote(Base):
    __tablename__ = "market_quotes"

    broker_instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("broker_instruments.id"), primary_key=True)
    ltp: Mapped[Decimal] = mapped_column(Numeric)
    prev_close: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    percent_change: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # percent, as the broker reports it
    week52_high: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    week52_low: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    exchange_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # null unless the payload had one
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mode: Mapped[str] = mapped_column(String)


class Watchlist(Base, UUIDPKMixin):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WatchlistItem(Base, UUIDPKMixin):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "broker_instrument_id", name="uq_watchlist_items_unique"),)

    watchlist_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("watchlists.id"), index=True)
    broker_instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("broker_instruments.id"))
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    why_watching: Mapped[str | None] = mapped_column(String, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WatchAlert(Base, UUIDPKMixin):
    __tablename__ = "watch_alerts"

    item_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("watchlist_items.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # price_above | price_below | day_move_up | day_move_down
    threshold: Mapped[Decimal] = mapped_column(Numeric)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered: Mapped[bool] = mapped_column(Boolean, default=False)  # current state: condition true at the last refresh
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
