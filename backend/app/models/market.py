import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Uuid
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
