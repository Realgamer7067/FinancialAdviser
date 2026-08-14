"""FinBERT (ProsusAI/finbert) FinancialLanguageModel implementation. Ungated,
CPU-fast -- chosen over FinGPT for this offline/no-GPU MVP (see build plan).
The FinancialLanguageModel interface stays swappable so a FinGPT LoRA adapter
can replace this once GPU/gated-weights access is available."""

import asyncio
from typing import Literal

from transformers import pipeline

from app.core.config import settings
from app.models_iface.base import FinancialLanguageModel, NewsSentiment

_LABEL_MAP: dict[str, Literal["positive", "neutral", "negative"]] = {
    "positive": "positive",
    "neutral": "neutral",
    "negative": "negative",
}


class FinBERTModel(FinancialLanguageModel):
    _pipeline = None  # lazy-loaded, shared across instances (Section 40)

    def __init__(self):
        self._model_version = settings.finbert_model_id

    def _ensure_loaded(self):
        if FinBERTModel._pipeline is None:
            FinBERTModel._pipeline = pipeline(
                "text-classification", model=settings.finbert_model_id, device=-1  # CPU
            )
        return FinBERTModel._pipeline

    async def analyze_news(self, headline: str, summary: str | None = None) -> NewsSentiment:
        text = f"{headline}. {summary}" if summary else headline
        result = await asyncio.to_thread(self._run, text)
        label = _LABEL_MAP.get(result["label"].lower(), "neutral")
        score = result["score"]
        # FinBERT gives P(label); convert to a signed -1..1 sentiment score.
        signed = score if label == "positive" else (-score if label == "negative" else 0.0)
        return NewsSentiment(
            sentiment=signed,
            confidence=score,
            direction=label,
            model_name="FinBERT",
            model_version=self._model_version,
        )

    def _run(self, text: str) -> dict:
        clf = self._ensure_loaded()
        return clf(text, truncation=True)[0]
