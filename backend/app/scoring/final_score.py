"""Deterministic final scoring (Section 18), model agreement (Section 51), and
confidence (Section 19) -- all computed in Python, outside the LLM. The Qwen
judge explains this score; it never invents it."""

from collections import Counter

from pydantic import BaseModel

from app.core.config import scoring_config


class ScoreBreakdown(BaseModel):
    fundamental: float | None
    technical: float | None
    kronos: float | None
    news: float | None
    portfolio: float | None
    risk: float | None
    final_score: float
    model_agreement: float
    data_quality: float
    confidence: float
    confidence_band: str  # high | medium | low


def _direction_from_score(score: float | None, bull_at: float = 60, bear_at: float = 40) -> str | None:
    if score is None:
        return None
    if score >= bull_at:
        return "bullish"
    if score <= bear_at:
        return "bearish"
    return "neutral"


def compute_model_agreement(
    fundamental: float | None,
    technical_trend: str | None,
    kronos_direction: str | None,
    news: float | None,
) -> float:
    signals = [
        s
        for s in [
            _direction_from_score(fundamental),
            technical_trend,
            kronos_direction,
            _direction_from_score(news),
        ]
        if s is not None
    ]
    if len(signals) < 2:
        return 0.4  # too little evidence to claim agreement (Section 51)
    counts = Counter(signals)
    majority_count = counts.most_common(1)[0][1]
    return majority_count / len(signals)


def compute_final_score(
    sub_scores: dict[str, float | None], technical_trend: str | None, kronos_direction: str | None
) -> ScoreBreakdown:
    weights = scoring_config()["weights"]
    conf_cfg = scoring_config()["confidence"]

    available = {k: v for k, v in sub_scores.items() if v is not None}
    weight_sum = sum(weights[k] for k in available)
    final = sum(sub_scores[k] * weights[k] for k in available) / weight_sum if weight_sum > 0 else 0.0

    data_quality = len(available) / len(weights)
    model_agreement = compute_model_agreement(
        sub_scores.get("fundamental"), technical_trend, kronos_direction, sub_scores.get("news")
    )
    confidence = max(0.0, min(1.0, 0.5 * model_agreement + 0.5 * data_quality))

    if confidence >= conf_cfg["high_min"]:
        band = "high"
    elif confidence >= conf_cfg["medium_min"]:
        band = "medium"
    else:
        band = "low"

    return ScoreBreakdown(
        fundamental=sub_scores.get("fundamental"),
        technical=sub_scores.get("technical"),
        kronos=sub_scores.get("kronos"),
        news=sub_scores.get("news"),
        portfolio=sub_scores.get("portfolio"),
        risk=sub_scores.get("risk"),
        final_score=round(final, 1),
        model_agreement=round(model_agreement, 2),
        data_quality=round(data_quality, 2),
        confidence=round(confidence, 2),
        confidence_band=band,
    )
