import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class PortfolioResult(Base, UUIDPKMixin):
    """Output of the PortfolioModel (Section 12). `method` distinguishes the real
    deterministic optimizer from the not-yet-wired DRL path -- never conflated."""

    __tablename__ = "portfolio_results"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    method: Mapped[str] = mapped_column(String)  # "mean_variance" | "finrl_drl" (stub)
    candidate_symbols: Mapped[list] = mapped_column(JSON)
    allocations: Mapped[dict] = mapped_column(JSON)  # {"TCS": 0.14, ...}
    expected_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_volatility: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version: Mapped[str] = mapped_column(String)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
