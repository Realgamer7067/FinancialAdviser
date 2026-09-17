"""Product catalogue (V3 Phase 03, docs/V3-IMPLEMENTATION-PLAN.md section 4.2:
"Instrument catalogue contract"). A catalogue any later allocation engine can
query for "what products exist, what do we actually know about them, and are
we allowed to recommend a specific instrument purchase or only a category."

No real reviewed financial product data has been supplied to this project
(recorded as an unresolved external input in docs/v3-execution/STATE.md).
Every fixture entry created via app/services/catalogue_fixtures.py is
explicitly SYNTHETIC (`is_synthetic=True`, `source_ids=["synthetic_fixture_v1"]`)
and must never be presented as real live market terms -- same convention as
app/providers/demo_market_data.py / demo_fundamentals.py (`source="demo_seed"`,
"never presented as real")."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class ProductCatalogEntry(Base, UUIDPKMixin):
    __tablename__ = "product_catalog_entries"

    # Stable internal ID (id, from UUIDPKMixin) plus external identifiers --
    # V3 section 4.2: "Preserve aliases and identifier changes rather than
    # matching on display names."
    external_ids: Mapped[dict] = mapped_column(JSON)  # e.g. {"isin": "INF...", "scheme_code": "..."} -- keys vary by product_type
    parent_exposure_id: Mapped[str | None] = mapped_column(String, nullable=True)  # shared by e.g. direct/regular
    # plans of the same fund -- V3 4.2: "Scheme plans/options have distinct identities; share a parent
    # economic-exposure ID to detect duplication."
    product_type: Mapped[str] = mapped_column(String)  # V3 4.1 family names, snake_cased: direct_listed_equity |
    # equity_index_fund | equity_index_etf | bank_fd | bank_rd | treasury_bill | govt_security |
    # liquid_debt_fund | gold_fund_etf | locked_account | hybrid_fund | other
    issuer_or_amc: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String, default="INR")
    status: Mapped[str] = mapped_column(String)  # "active" | "inactive"
    support_level: Mapped[str] = mapped_column(String)  # cached hint, NOT authoritative -- see
    # app/services/catalogue.py::resolve_support_level for the source of truth.
    # "education_only" | "holdings_only" | "category_planning" | "instrument_planning"
    exposure_vector: Mapped[dict] = mapped_column(JSON)  # e.g. {"domestic_equity": 1.0}; need not sum to 1.0
    # (a known-unknown remainder is allowed -- see V3 section 6.4; not enforced here)
    exposure_as_of: Mapped[date] = mapped_column(Date)
    valuation_method: Mapped[str] = mapped_column(String)  # e.g. "market_price", "nav", "issuer_quoted_rate"
    valuation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    eligible_contribution_methods: Mapped[list] = mapped_column(JSON)  # e.g. ["lump_sum", "sip"]
    minimum_initial: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    minimum_additional: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    increment: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    quantity_granularity: Mapped[str] = mapped_column(String)  # "whole_unit" | "fractional" | "amount"
    settlement_delay_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maturity_or_lock_rule: Mapped[str | None] = mapped_column(String, nullable=True)
    fee_assumptions: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # e.g. {"expense_ratio": 0.002, "exit_load": null}
    eligibility_predicates: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # e.g. {"min_age": null, "residency": "india_resident_individual"}
    source_ids: Mapped[list] = mapped_column(JSON)  # references into a source registry -- for synthetic entries,
    # a literal marker like ["synthetic_fixture_v1"], never a fake real-looking source ID
    source_freshness: Mapped[date] = mapped_column(Date)  # as_of date of the underlying terms
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)  # True for every fixture entry -- lets a
    # REAL reviewed catalogue entry (added later, by someone with actual sourced data) be distinguished at the
    # schema level, not just by convention
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
