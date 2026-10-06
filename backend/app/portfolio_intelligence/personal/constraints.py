"""Effective risk constraints (plan section 12.5): the strictest of capacity,
goal horizon/liquidity, explicit user restrictions and tolerance. Tolerance is
an ADDITIONAL ceiling, never a substitute for capacity; a funding gap or a high
required return never loosens any of them. Missing inputs are recorded as
unknown and restrict risk-increasing actions. Pure; unreviewed policy values."""

from datetime import date, timedelta
from decimal import Decimal

CONSTRAINT_POLICY_VERSION = "constraints-p0-unreviewed"
SHORT_HORIZON_DAYS = 365 * 3  # claims on goals due within 3 years are not available for added risk


def short_horizon_funds(goals: list[dict], allocations: list[dict], today: date | None = None) -> list[dict]:
    """goals: {chain_id, description, target_date(date)}; allocations: {goal_chain_id, amount(Decimal), status}."""
    today = today or date.today()
    limit = today + timedelta(days=SHORT_HORIZON_DAYS)
    out = []
    for g in goals:
        if g["target_date"] <= limit:
            claimed = sum((a["amount"] for a in allocations
                           if a["goal_chain_id"] == g["chain_id"] and a["status"] in ("active", "needs_review")), Decimal(0))
            out.append({"goal": g["description"], "target_date": g["target_date"].isoformat(), "claimed": format(claimed.normalize(), "f")})
    return out


def compute_effective_constraints(*, tolerance: dict, capacity: dict, short_horizon: list[dict], restrictions: list[dict]) -> dict:
    ceilings: list[dict] = []
    limiting: list[str] = []

    if tolerance["status"] != "ready":
        ceilings.append({"source": "tolerance", "status": "unknown", "detail": f"missing: {', '.join(tolerance['missing'])}",
                         "blocks_risk_increasing": True})
        limiting.append("tolerance_unknown")
    else:
        ceilings.append({"source": "tolerance", "status": "ready", "band": tolerance["band"],
                         "detail": "additional ceiling from your own answers; it cannot loosen capacity limits",
                         "blocks_risk_increasing": False})

    if capacity["blocks_risk_increasing_actions"]:
        for b in capacity["binding_constraints"]:
            limiting.append(b["rule"])
        ceilings.append({"source": "capacity", "status": capacity["status"], "binding": capacity["binding_constraints"],
                         "blocks_risk_increasing": True})
    else:
        ceilings.append({"source": "capacity", "status": capacity["status"], "binding": [], "blocks_risk_increasing": False})

    funded = [s for s in short_horizon if Decimal(s["claimed"]) > 0]
    ceilings.append({"source": "goal_horizon", "status": "restricts_funds" if funded else "none",
                     "short_horizon_goals": short_horizon,
                     "detail": ("money claimed for goals due within 3 years is not available for risk-increasing proposals"
                                if funded else "no money is claimed for goals due within 3 years"),
                     "blocks_risk_increasing": False})  # restricts WHICH rupees, not whether new money may take risk
    if funded:
        limiting.append("short_horizon_goal_funds")

    ceilings.append({"source": "restrictions", "status": "active" if restrictions else "none", "items": restrictions,
                     "blocks_risk_increasing": False})
    if restrictions:
        limiting.append("user_restrictions")

    return {
        "policy_version": CONSTRAINT_POLICY_VERSION,
        "risk_increasing_allowed": not any(c["blocks_risk_increasing"] for c in ceilings),
        "limiting_factors": limiting,
        "ceilings": ceilings,
        "note": "A goal funding gap or a high required return never loosens these limits.",
    }
