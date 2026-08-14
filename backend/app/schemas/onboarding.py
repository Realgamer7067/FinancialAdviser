"""Onboarding request/response schemas (Section 2). Pure form fields -- no
chat/free-text financial advice fields anywhere in this schema (Section 3)."""

from pydantic import BaseModel

from app.risk.scoring import RawRiskAnswers


class OnboardingRequest(BaseModel):
    age: int
    employment_status: str
    monthly_income_range: str
    monthly_investable_amount: float
    total_initial_investment: float
    existing_investments: dict = {}
    existing_debt: float = 0
    emergency_fund_status: str
    dependents: int = 0
    investment_objective: str
    investment_horizon_years: int
    liquidity_requirement: str
    investment_frequency: str
    raw_risk_answers: RawRiskAnswers


class RiskProfileResponse(BaseModel):
    risk_score: int
    risk_profile: str
    investment_horizon_years: int
    capital: float
    monthly_contribution: float
    objective: str
    liquidity_requirement: str
