import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class TechnicalFeatures(Base, UUIDPKMixin):
    """Deterministic technical-indicator snapshot (Section 9). Evidence, not a verdict."""

    __tablename__ = "technical_features"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(String)  # "1d" / "1w" / "1mo"
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    sma_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_200: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_12: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_26: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_hist: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    adx_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    volatility_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    drawdown_1y: Mapped[float | None] = mapped_column(Float, nullable=True)
    beta: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend: Mapped[str | None] = mapped_column(String, nullable=True)  # bullish/neutral/bearish

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KronosPrediction(Base, UUIDPKMixin):
    """Structured Kronos forecast (Section 10). Never presented as fact."""

    __tablename__ = "kronos_predictions"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"))
    forecast_horizon: Mapped[str] = mapped_column(String)  # "7d" / "30d" / "90d"
    direction: Mapped[str] = mapped_column(String)  # bullish/neutral/bearish
    predicted_return: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    input_timeframe: Mapped[str] = mapped_column(String)
    model_name: Mapped[str] = mapped_column(String, default="Kronos")
    model_version: Mapped[str] = mapped_column(String)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FinbertAnalysis(Base, UUIDPKMixin):
    """Aggregated news-sentiment evidence per instrument over a time window (Section 11)."""

    __tablename__ = "finbert_analysis"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sentiment_score: Mapped[float] = mapped_column(Float)  # -1..1, recency-weighted
    confidence: Mapped[float] = mapped_column(Float)
    article_count: Mapped[int] = mapped_column(Integer)
    model_name: Mapped[str] = mapped_column(String, default="FinBERT")
    model_version: Mapped[str] = mapped_column(String)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
