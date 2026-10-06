"""Risk observations from the Twin (plan sections 5.1, 12.5). Pure functions.

Every dimension reports status ready / estimated / insufficient_data /
unsupported with its coverage and method. Unknown stays in an explicit unknown
bucket (never zero, never redistributed); unvalued positions are counted
separately. Weights are of TOTAL KNOWN VALUE unless stated. These are weight
concentrations, not independent risk factors."""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

METHOD_VERSION = "exposure-v1"
_ZERO = Decimal(0)
UNRESOLVED = ("unresolved", "ambiguous")

ASSET_CLASS = {
    "listed_equity": "equity",
    "etf": "fund_or_etf",          # composition unknown: no look-through
    "mutual_fund": "fund_or_etf",
    "cash": "cash",
    "deposit": "deposit",
    "gold": "gold",
    "other": "unknown",
    "unclassified": "unknown",
}


def _w(x: Decimal, total: Decimal) -> str | None:
    return None if total == 0 else format((x / total).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")


def _s(x: Decimal) -> str:
    return format(x.normalize(), "f")


def sector_verified(p: dict) -> bool:
    """A sector counts only when it came from the instrument master (a resolved Nifty 50 match) or from the market catalogue by ISIN."""
    return bool(p.get("sector")) and (p.get("resolution") == "resolved" or p.get("sector_source") == "market_catalogue")


def asset_class_of(asset_type: str) -> str:
    return ASSET_CLASS.get(asset_type, "unknown")


def compute_exposures(positions: list[dict]) -> dict:
    """positions: {position_id, account_label, asset_type, resolution, instrument_id, isin, label,
    value: Decimal|None, quality, sector: str|None, as_of: str}"""
    valued = [p for p in positions if p["value"] is not None]
    unvalued = [p for p in positions if p["value"] is None]
    total = sum((p["value"] for p in valued), _ZERO)

    # --- asset mix -------------------------------------------------------------
    by_class: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    basis: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: _ZERO))
    for p in valued:
        c = asset_class_of(p["asset_type"])
        by_class[c] += p["value"]
        basis[c]["instrument_master" if p["resolution"] == "resolved" else "user_declared"] += p["value"]
    mix = {c: {"value": _s(v), "weight": _w(v, total),
               "classification_basis": {k: _s(x) for k, x in basis[c].items()}} for c, v in sorted(by_class.items())}
    equity = by_class.get("equity", _ZERO)
    funds = by_class.get("fund_or_etf", _ZERO)
    asset_mix = {
        "status": "ready" if total > 0 else "insufficient_data",
        "method": "user-declared asset type; 'instrument_master' basis when the holding matched a known instrument",
        "known_total": _s(total),
        "unvalued_positions": len(unvalued),
        "classes": mix,
        "direct_equity_share": _w(equity, total),
        # Funds/ETFs are not looked through, so true equity exposure lies in this range.
        "equity_share_upper_bound": _w(equity + funds, total),
        "warnings": (["fund and ETF holdings are not looked through; their equity exposure is unknown"] if funds else [])
                    + ([f"{len(unvalued)} position(s) have no value and are excluded from every weight"] if unvalued else []),
    }

    # --- issuer concentration (direct listed equity only) ------------------------
    issuers: dict[str, dict] = {}
    for p in valued:
        if p["asset_type"] != "listed_equity":
            continue
        key = p["instrument_id"] or p["isin"]  # identified issuer; symbol text alone does not identify
        if not key:
            continue
        e = issuers.setdefault(str(key), {"label": p["label"], "value": _ZERO, "accounts": set()})
        e["value"] += p["value"]
        e["accounts"].add(p["account_label"])
    ranked = sorted(issuers.values(), key=lambda e: -e["value"])
    identified = sum((e["value"] for e in ranked), _ZERO)
    if identified > 0:
        hhi = sum(((e["value"] / identified) ** 2 for e in ranked), _ZERO)
        issuer = {
            "status": "ready",
            "method": "weight concentration over the identified-issuer slice; not independent risk exposures",
            "identified_value": _s(identified),
            "coverage_fraction": _w(identified, total),
            "largest_issuer_weight": _w(ranked[0]["value"], total),
            "largest_issuer": ranked[0]["label"],
            "top5_weight": _w(sum((e["value"] for e in ranked[:5]), _ZERO), total),
            "herfindahl_over_identified": format(hhi.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f"),
            "effective_positions_over_identified": format((1 / hhi).quantize(Decimal("0.01")), "f"),
            "issuers": [{"issuer": e["label"], "value": _s(e["value"]), "weight": _w(e["value"], total),
                         "accounts": sorted(e["accounts"])} for e in ranked],
            "warnings": [] if identified == total else ["issuer concentration covers only the identified direct-equity slice"],
        }
    else:
        issuer = {"status": "insufficient_data", "coverage_fraction": "0", "warnings": ["no identified direct equity holdings"],
                  "issuers": []}

    # --- account concentration ---------------------------------------------------
    by_account: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    for p in valued:
        by_account[p["account_label"]] += p["value"]
    accounts = [{"account": a, "value": _s(v), "weight": _w(v, total)} for a, v in sorted(by_account.items(), key=lambda kv: -kv[1])]

    # --- sector (verified instrument sector only) -----------------------------------
    sectors: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    for p in valued:
        c = asset_class_of(p["asset_type"])
        if c == "equity" and sector_verified(p):
            sectors[p["sector"]] += p["value"]
        elif c == "equity":
            sectors["unclassified_equity"] += p["value"]
        elif c == "fund_or_etf":
            sectors["fund_lookthrough_unknown"] += p["value"]
        else:
            sectors["non_equity"] += p["value"]
    sector = {
        "status": "ready" if total > 0 else "insufficient_data",
        "method": "sector from the matched instrument master or, for other listed stocks, the market catalogue by ISIN (NSE sector list, larger companies only); everything else, and every fund or ETF, stays in an explicit unknown bucket",
        "buckets": [{"bucket": k, "value": _s(v), "weight": _w(v, total)} for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])],
        "unknown_weight": _w(sectors.get("unclassified_equity", _ZERO) + sectors.get("fund_lookthrough_unknown", _ZERO), total),
    }

    # --- coverage / staleness (separate from risk itself) -------------------------
    def share(pred):
        return _w(sum((p["value"] for p in valued if pred(p)), _ZERO), total)

    dates = sorted(p["as_of"] for p in positions) if positions else []
    coverage = {
        "position_count": len(positions), "valued_count": len(valued), "unvalued_count": len(unvalued),
        "fresh_value_share": share(lambda p: p["quality"] == "fresh"),
        "identity_resolved_value_share": share(lambda p: p["resolution"] in ("resolved", "not_applicable")),
        "earliest_as_of": dates[0] if dates else None, "latest_as_of": dates[-1] if dates else None,
    }

    # Reconciliation: every bucket set sums to the known total (checked in tests, shown here).
    recon = {
        "asset_classes_sum": _s(sum(by_class.values(), _ZERO)), "sectors_sum": _s(sum(sectors.values(), _ZERO)),
        "accounts_sum": _s(sum(by_account.values(), _ZERO)), "known_total": _s(total),
    }
    return {"method_version": METHOD_VERSION, "asset_mix": asset_mix, "issuer_concentration": issuer,
            "account_concentration": accounts, "sector": sector, "coverage": coverage, "reconciliation": recon}


def compute_liquidity(positions: list[dict], claims_by_position: dict[str, Decimal], capacity: dict) -> dict:
    """Confirmed accessible CASH (not deposits) after goal claims, vs the next 12 months of
    essential outgo plus known obligations. Undefined when the denominator is unknown/zero."""
    cash = _ZERO
    for p in positions:
        if asset_class_of(p["asset_type"]) == "cash" and p["value"] is not None:
            cash += max(p["value"] - claims_by_position.get(p["position_id"], _ZERO), _ZERO)
    outgo = capacity.get("monthly_essential_outgo")
    out = {"method": "unclaimed cash positions / (12 x essential outgo + known obligations next 12 months); "
                     "deposits and broker margin are not counted as accessible cash",
           "accessible_cash_after_claims": _s(cash), "status": "insufficient_data", "months_of_outgo": None, "ratio_to_12m_need": None}
    if outgo is None:
        out["warnings"] = ["essential monthly outgo is unknown (add it in Financial profile)"]
        return out
    outgo_d = Decimal(outgo)
    obligations = Decimal(capacity["near_term_obligations_12m"]) if capacity.get("near_term_obligations_12m") is not None else None
    if outgo_d == 0:
        out["warnings"] = ["essential outgo is zero; coverage is undefined"]
        return out
    need = outgo_d * 12 + (obligations or _ZERO)
    out.update(status="ready" if obligations is not None else "estimated", months_of_outgo=format((cash / outgo_d).quantize(Decimal("0.1")), "f"),
               ratio_to_12m_need=format((cash / need).quantize(Decimal("0.001")), "f"), twelve_month_need=_s(need))
    out["warnings"] = [] if obligations is not None else ["near-term obligations were not entered; the 12-month need may be understated"]
    return out
