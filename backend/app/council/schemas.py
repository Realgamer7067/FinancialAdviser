"""Structured council I/O schemas (Section 16/42). Every role returns a
concise, validated result -- never raw chain-of-thought (Section 16: 'do not
expose private chain-of-thought')."""

from typing import Literal

from pydantic import BaseModel, Field


class PlannerOutput(BaseModel):
    """Qwen's analysis plan (Section 14) -- guidance only; screening/weights
    stay config-driven, this doesn't override them."""

    prioritize: list[str] = Field(max_length=6)
    avoid: list[str] = Field(max_length=6)
    notes: str


class BullCaseOutput(BaseModel):
    supporting_points: list[str] = Field(max_length=6)
    summary: str


class BearCaseOutput(BaseModel):
    concerns: list[str] = Field(max_length=6)
    summary: str


class FundamentalAssessmentOutput(BaseModel):
    business_quality: Literal["strong", "adequate", "weak", "unknown"]
    valuation: Literal["cheap", "fair", "expensive", "unknown"]
    summary: str


class QuantAssessmentOutput(BaseModel):
    technical_read: Literal["bullish", "neutral", "bearish", "unknown"]
    forecast_read: Literal["bullish", "neutral", "bearish", "unknown"]
    summary: str


class RiskAssessmentOutput(BaseModel):
    key_risks: list[str] = Field(max_length=6)
    suitability: Literal["suitable", "caution", "unsuitable"]
    summary: str


class JudgeVerdictOutput(BaseModel):
    """Section 16: the judge must explicitly identify these -- no numeric
    score/confidence here, those are computed deterministically (Section 18/19)."""

    strongest_evidence: list[str] = Field(max_length=5)
    contradictory_evidence: list[str] = Field(max_length=5)
    missing_data: list[str] = Field(max_length=5)
    model_disagreements: list[str] = Field(max_length=5)
    major_risks: list[str] = Field(max_length=5)
    rationale: str
