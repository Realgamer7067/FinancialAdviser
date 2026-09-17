import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class Instrument(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String, unique=True, index=True)
    exchange: Mapped[str] = mapped_column(String, default="NSE")
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    instrument_key: Mapped[str | None] = mapped_column(String, nullable=True)  # Upstox instrument_key
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MarketPrice(Base, UUIDPKMixin):
    """Latest quote snapshot. Every row is timestamped/sourced (Section 25)."""

    __tablename__ = "market_prices"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"))
    price: Mapped[float] = mapped_column(Float)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    market_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketCandle(Base, UUIDPKMixin):
    __tablename__ = "market_candles"
    __table_args__ = (
        # Defense-in-depth against the overlapping-refresh duplication bug
        # (docs/V2-RETHINK.md P0): source is part of the natural key so a
        # demo_seed row and a yfinance row for the same instant never collide.
        #
        # V3 Phase 02 (docs/v3-execution/phase-02.md): a plain UniqueConstraint
        # would forbid keeping superseded history alongside its replacement, so
        # this is a PARTIAL unique index that only applies to "current" rows
        # (superseded_at IS NULL). Superseded rows for the same natural key are
        # allowed to coexist -- a refresh soft-supersedes instead of deleting,
        # so a published report's evidence can still be traced back to the
        # exact candle set it was computed from.
        Index(
            "uq_market_candles_natural_key_current",
            "instrument_id",
            "interval",
            "timestamp",
            "source",
            unique=True,
            sqlite_where=text("superseded_at IS NULL"),
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"))
    interval: Mapped[str] = mapped_column(String)  # "1d", "1w", "1mo"
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # V3 Phase 02: soft-supersession instead of hard delete on refresh (see
    # __table_args__ above). import_batch_id groups every row inserted by one
    # _persist_candles() call; superseded_at is set when a later refresh
    # replaces this row's data, but the row itself is kept for history.
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # V3 Phase 02: whether `close` is split/dividend-adjusted (see
    # app.providers.base.Candle.adjusted). default=True since existing rows
    # were fetched via yfinance, whose default is adjusted closes.
    adjusted: Mapped[bool] = mapped_column(Boolean, default=True)
