"""Deterministic fundamental-ratio gap-filling (Section 8). Only fills a ratio
when it can be derived exactly from other known fields on the same snapshot --
never estimates from unrelated data. Anything still missing stays None
(UNKNOWN), rendered as such in the UI/evidence layer."""

from app.providers.base import FundamentalSnapshot


def fill_derived_ratios(snapshot: FundamentalSnapshot) -> FundamentalSnapshot:
    data = snapshot.model_dump()

    if data["ebitda_margin"] is None and data["ebitda"] is not None and data["revenue"]:
        data["ebitda_margin"] = data["ebitda"] / data["revenue"]

    if data["net_margin"] is None and data["pat"] is not None and data["revenue"]:
        data["net_margin"] = data["pat"] / data["revenue"]

    if data["operating_margin"] is None and data["ebit"] is not None and data["revenue"]:
        data["operating_margin"] = data["ebit"] / data["revenue"]

    if data["free_cash_flow"] is None and data["operating_cash_flow"] is not None:
        # Only exact when capex is known; capex isn't tracked separately in the
        # MVP snapshot, so this stays None rather than a wrong estimate.
        pass

    return FundamentalSnapshot(**data)


def has_pledged_shares_risk(snapshot: FundamentalSnapshot, threshold: float = 0.5) -> bool:
    if snapshot.promoter_pledging is None:
        return False  # UNKNOWN -- not asserted as a risk, but also not cleared
    return snapshot.promoter_pledging > threshold
