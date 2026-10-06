import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin

# Unavailable numeric fields are stored as NULL and must be rendered as "UNKNOWN"
# in the UI/evidence layer (Section 8) -- never guessed.


class FundamentalMetrics(Base, UUIDPKMixin):
    __tablename__ = "fundamental_metrics"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("instruments.id"))
    as_of_date: Mapped[date] = mapped_column(Date)

    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebitda: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebitda_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebit: Mapped[float | None] = mapped_column(Float, nullable=True)
    pat: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_debt: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_to_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    interest_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    roce: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev_ebitda: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    # See app/providers/base.py::FundamentalSnapshot for why these are two
    # separate fields, not one -- different metrics from different disclosure
    # regimes (docs/V2-RETHINK.md P1).
    insider_holding_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    promoter_holding: Mapped[float | None] = mapped_column(Float, nullable=True)
    promoter_pledging: Mapped[float | None] = mapped_column(Float, nullable=True)
    institutional_ownership: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Annual statements for ONE fiscal year (same period end), so accruals / cash profitability / FCF yield never mix a trailing and an annual figure.
    annual_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_assets: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_assets_prior: Mapped[float | None] = mapped_column(Float, nullable=True)
    annual_net_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    annual_operating_cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    annual_capex: Mapped[float | None] = mapped_column(Float, nullable=True)
    annual_free_cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    # NSE's own quarterly filings, summed over four quarters: a cross-check on `eps`, never a replacement.
    nse_eps_ttm: Mapped[float | None] = mapped_column(Float, nullable=True)
    nse_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    nse_quarters: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped[str] = mapped_column(String)  # e.g. "nifty50_seed_dataset_v1"
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
