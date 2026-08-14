"""Specialist-model interfaces (Section 41). Qwen (MasterReasoningModel) never
fetches facts itself -- it only reasons over what these produce (Section 62)."""

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel

from app.providers.base import Candle


class TimeSeriesForecast(BaseModel):
    """Structured Kronos-style output (Section 10). Never presented as fact."""

    forecast_horizon: str
    direction: Literal["bullish", "neutral", "bearish"]
    predicted_return: float
    confidence: float
    input_timeframe: str
    model_name: str
    model_version: str


class TimeSeriesModel(ABC):
    @abstractmethod
    async def forecast(self, symbol: str, candles: list[Candle], horizon: str) -> TimeSeriesForecast | None:
        """Returns None (not a guess) if the model can't produce a forecast --
        e.g. insufficient history -- per the failure-handling rule (Section 50)."""


class NewsEvent(BaseModel):
    type: str
    importance: float


class NewsSentiment(BaseModel):
    """Structured FinBERT output (Section 11)."""

    sentiment: float  # -1..1
    confidence: float  # 0..1
    direction: Literal["positive", "neutral", "negative"]
    model_name: str
    model_version: str


class FinancialLanguageModel(ABC):
    @abstractmethod
    async def analyze_news(self, headline: str, summary: str | None = None) -> NewsSentiment: ...


class PortfolioAllocationResult(BaseModel):
    method: str  # "mean_variance" | "finrl_drl"
    allocations: dict[str, float]
    expected_return: float | None
    expected_volatility: float | None
    sharpe: float | None
    model_version: str


class PortfolioModel(ABC):
    @abstractmethod
    async def optimize(
        self,
        candidate_returns: dict[str, list[float]],
        risk_free_rate: float,
        max_single_weight: float,
    ) -> PortfolioAllocationResult: ...


class NotImplementedModel(Exception):
    """Raised by stub adapters (e.g. the FinRL DRL agent) that are intentionally
    not wired up yet -- never silently faked (Section 74)."""
