import uuid

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class User(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String)


class UserProfile(Base, UUIDPKMixin, TimestampMixin):
    """Structured onboarding answers (Section 2). Raw answers stored separately
    from the derived risk profile (RiskProfile) per the spec's hard requirement."""

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)

    age: Mapped[int] = mapped_column(Integer)
    employment_status: Mapped[str] = mapped_column(String)
    monthly_income_range: Mapped[str] = mapped_column(String)
    monthly_investable_amount: Mapped[float] = mapped_column(Float)
    total_initial_investment: Mapped[float] = mapped_column(Float)
    existing_investments: Mapped[dict] = mapped_column(JSON, default=dict)
    existing_debt: Mapped[float] = mapped_column(Float, default=0)
    emergency_fund_status: Mapped[str] = mapped_column(String)
    dependents: Mapped[int] = mapped_column(Integer, default=0)
    investment_objective: Mapped[str] = mapped_column(String)
    investment_horizon_years: Mapped[int] = mapped_column(Integer)
    liquidity_requirement: Mapped[str] = mapped_column(String)
    investment_frequency: Mapped[str] = mapped_column(String)

    # Raw risk-questionnaire answers (Section 2), untouched by the derived scorer.
    raw_risk_answers: Mapped[dict] = mapped_column(JSON, default=dict)


class RiskProfile(Base, UUIDPKMixin, TimestampMixin):
    """Deterministically computed from UserProfile.raw_risk_answers.
    Qwen interprets this; it never invents it (Section 2)."""

    __tablename__ = "risk_profiles"

    user_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profiles.id")
    )
    risk_score: Mapped[int] = mapped_column(Integer)
    risk_profile: Mapped[str] = mapped_column(String)  # conservative/moderate/aggressive
    investment_horizon_years: Mapped[int] = mapped_column(Integer)
    capital: Mapped[float] = mapped_column(Float)
    monthly_contribution: Mapped[float] = mapped_column(Float)
    objective: Mapped[str] = mapped_column(String)
    liquidity_requirement: Mapped[str] = mapped_column(String)
    # `created_at` (from TimestampMixin) is the computation timestamp.
