"""Deterministic stress illustrations (plan sections 5.2, 12.6). Pure.

A scenario is ONE shock applied once to the positions it verifiably covers; a
broad-market and a sector shock are separate scenarios, never stacked, so beta
is not double counted. Unknown sensitivity is a coverage gap reported in
rupees, never a silent 0. These are hypothetical illustrations, not forecasts."""

from decimal import ROUND_HALF_UP, Decimal

from app.portfolio_intelligence.risk.exposure import asset_class_of, sector_verified

SCENARIO_VERSION = "stress-v1"
_PAISE = Decimal("0.01")
MIN_SHOCK, MAX_SHOCK = Decimal("-0.60"), Decimal("0")

# Named templates are versioned; changing one means a new SCENARIO_VERSION.
CATALOG = [
    {"id": "equity_broad_-20", "kind": "broad_equity", "shock": "-0.20", "label": "Broad equity market falls 20%", "status": "supported"},
    {"id": "sector_financial_services_-20", "kind": "sector", "sector": "Financial Services", "shock": "-0.20",
     "label": "Financial Services sector falls 20% (banks, NBFCs and insurers together; banks alone are not separated)", "status": "supported"},
    {"id": "sector_information_technology_-25", "kind": "sector", "sector": "Information Technology", "shock": "-0.25",
     "label": "Information Technology sector falls 25%", "status": "supported"},
    {"id": "rates_+150bp", "kind": "rates", "label": "Interest rates rise 1.5 percentage points", "status": "unsupported",
     "reason": "needs bond/debt-fund duration, which this snapshot does not hold"},
    {"id": "oil_+30", "kind": "oil", "label": "Oil rises 30%", "status": "unsupported", "reason": "needs a sourced sensitivity per holding"},
    {"id": "inr_-10", "kind": "fx", "label": "Rupee falls 10%", "status": "unsupported", "reason": "needs known currency exposure per holding"},
]


def resolve_scenario(spec: dict) -> dict:
    """spec: {"id": named} or {"kind": "broad_equity"|"sector", "shock": "-0.2", "sector": "..."} (custom, bounded)."""
    if spec.get("id"):
        found = next((c for c in CATALOG if c["id"] == spec["id"]), None)
        if found is None:
            raise ValueError("unknown scenario id")
        if found["status"] != "supported":
            raise ValueError(f"scenario unsupported: {found['reason']}")
        return found
    kind = spec.get("kind")
    if kind not in ("broad_equity", "sector"):
        raise ValueError("custom scenario kind must be broad_equity or sector")
    shock = Decimal(str(spec.get("shock")))
    if not shock.is_finite() or shock < MIN_SHOCK or shock > MAX_SHOCK:
        raise ValueError(f"custom shock must be between {MIN_SHOCK} and {MAX_SHOCK} (a fall, up to 60%)")
    if kind == "sector" and not str(spec.get("sector", "")).strip():
        raise ValueError("sector scenario needs a sector name")
    sector = str(spec["sector"]).strip() if kind == "sector" else None
    return {"id": "custom", "kind": kind, "sector": sector, "shock": str(shock), "label": "Custom shock", "status": "supported"}


def _sensitivity(scn: dict, p: dict) -> tuple[Decimal | None, str]:
    """(modeled return or None if unmodeled, reason)."""
    cls = asset_class_of(p["asset_type"])
    if scn["kind"] == "broad_equity":
        if cls == "equity":
            return Decimal(scn["shock"]), "direct listed equity moves one-for-one with the shock (beta 1 assumed)"
        if cls in ("cash", "deposit"):
            return Decimal(0), "no market-price shock in this scenario"
        if cls == "fund_or_etf":
            return None, "fund/ETF composition unknown (no look-through)"
        if cls == "gold":
            return None, "gold's sensitivity to an equity shock is not modeled"
        return None, "asset class unknown"
    # sector scenario: only verified members are shocked; everyone else is outside the scenario
    if cls == "equity" and sector_verified(p) and p.get("sector") == scn["sector"]:
        return Decimal(scn["shock"]), f"verified {scn['sector']} holding"
    if cls == "equity" and not sector_verified(p):
        return None, "equity sector unverified (not in the instrument list or the market catalogue's sector list)"
    if cls == "fund_or_etf":
        return None, "fund/ETF composition unknown (no look-through)"
    if cls in ("gold", "unknown"):
        return None, "not classified for sector scenarios"
    return Decimal(0), "not in the shocked sector"


def run_scenario(scn: dict, positions: list[dict]) -> dict:
    ledger = []
    modeled_change = Decimal(0)
    modeled_value = Decimal(0)
    unmodeled_value = Decimal(0)
    unvalued = 0
    for p in positions:
        if p["value"] is None:
            ledger.append({"position_id": p["position_id"], "account": p["account_label"], "holding": p["label"], "pre_shock_value": None,
                           "modeled_return": None, "value_change": None, "modeled": False, "reason": "no value; excluded", "quality": p["quality"]})
            unvalued += 1
            continue
        ret, reason = _sensitivity(scn, p)
        if ret is None:
            unmodeled_value += p["value"]
            ledger.append({"position_id": p["position_id"], "account": p["account_label"], "holding": p["label"],
                           "pre_shock_value": format(p["value"].normalize(), "f"), "modeled_return": None, "value_change": None,
                           "modeled": False, "reason": reason, "quality": p["quality"]})
            continue
        change = (p["value"] * ret).quantize(_PAISE, rounding=ROUND_HALF_UP)
        modeled_change += change
        modeled_value += p["value"]
        ledger.append({"position_id": p["position_id"], "account": p["account_label"], "holding": p["label"],
                       "pre_shock_value": format(p["value"].normalize(), "f"), "modeled_return": format(ret.normalize(), "f"),
                       "value_change": format(change, "f"), "modeled": True, "reason": reason, "quality": p["quality"]})
    total = modeled_value + unmodeled_value
    return {
        "scenario": {k: scn.get(k) for k in ("id", "kind", "sector", "shock", "label")},
        "version": SCENARIO_VERSION,
        "label": "Hypothetical illustration, not a forecast.",
        "known_total": format(total.normalize(), "f"),
        "modeled_value": format(modeled_value.normalize(), "f"),
        "modeled_change": format(modeled_change, "f"),
        "modeled_change_pct_of_modeled_value": None if modeled_value == 0 else format((modeled_change / modeled_value).quantize(Decimal("0.0001")), "f"),
        "modeled_change_pct_of_known_total": None if total == 0 else format((modeled_change / total).quantize(Decimal("0.0001")), "f"),
        "outside_coverage": {"value": format(unmodeled_value.normalize(), "f"),
                             "share_of_known_total": None if total == 0 else format((unmodeled_value / total).quantize(Decimal("0.0001")), "f"),
                             "unvalued_positions": unvalued,
                             "note": "sensitivity unknown: reported as a gap, not assumed flat"},
        "ledger": ledger,
        "reconciles": sum((Decimal(r["value_change"]) for r in ledger if r["modeled"]), Decimal(0)) == modeled_change,
    }
