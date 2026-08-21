"""Static educational content API. Serves curated, non-live reference
content only -- never a personalized recommendation or a live quote (see
app/education/safer_alternatives.py's module docstring)."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.education.safer_alternatives import get_safer_alternatives

router = APIRouter(prefix="/api/education", tags=["education"])


class SaferAlternativeOut(BaseModel):
    key: str
    name: str
    category: str
    description: str
    indicative_return_range: str
    liquidity: str
    typical_lock_in: str | None
    risk_note: str
    suited_risk_profiles: list[str]
    eligibility_note: str | None


class SaferAlternativesOut(BaseModel):
    disclaimer: str
    items: list[SaferAlternativeOut]


_DISCLAIMER = (
    "General educational information only, not a live quote, not personalized "
    "financial advice, and not an offer to invest. Rates and terms change -- "
    "verify current figures with the issuing bank/RBI/post office before investing."
)


@router.get("/safer-alternatives", response_model=SaferAlternativesOut)
async def safer_alternatives():
    items = [
        SaferAlternativeOut(
            key=a.key,
            name=a.name,
            category=a.category,
            description=a.description,
            indicative_return_range=a.indicative_return_range,
            liquidity=a.liquidity,
            typical_lock_in=a.typical_lock_in,
            risk_note=a.risk_note,
            suited_risk_profiles=list(a.suited_risk_profiles),
            eligibility_note=a.eligibility_note,
        )
        for a in get_safer_alternatives()
    ]
    return SaferAlternativesOut(disclaimer=_DISCLAIMER, items=items)
