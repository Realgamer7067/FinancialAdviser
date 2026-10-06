"""Allocation policy: every number the plan depends on, declared and versioned. ALL values are unreviewed placeholders for a
single owner's own money (a college project), not a reviewed investment policy; the plan prints them with its output.

Gate order (a later gate can only make the plan MORE cautious):
1. tolerance unknown            -> the safe bucket only, and the plan asks for the three risk answers
2. capacity blocks added risk   -> the safe bucket only (e.g. emergency reserve below its target)
3. money claimed for goals due within 3 years stays out of the risk buckets
4. only then does the band's mix apply"""

from decimal import Decimal

POLICY_VERSION = "allocation-p0-unreviewed"

BUCKETS = ("equity_india", "equity_intl", "gold", "debt")
BUCKET_LABEL = {"equity_india": "Indian equity", "equity_intl": "International equity", "gold": "Gold", "debt": "Debt and liquid"}

# Strategic mix by the owner's own tolerance band (behavioural answers only; see personal/facts.py).
MIX = {
    "conservative": {"equity_india": Decimal("0.20"), "equity_intl": Decimal("0.00"), "gold": Decimal("0.10"), "debt": Decimal("0.70")},
    "moderate":     {"equity_india": Decimal("0.45"), "equity_intl": Decimal("0.05"), "gold": Decimal("0.10"), "debt": Decimal("0.40")},
    "aggressive":   {"equity_india": Decimal("0.65"), "equity_intl": Decimal("0.10"), "gold": Decimal("0.10"), "debt": Decimal("0.15")},
}
SAFE_ONLY = {"equity_india": Decimal(0), "equity_intl": Decimal(0), "gold": Decimal(0), "debt": Decimal(1)}

DRIFT_BAND = Decimal("0.05")              # a bucket within +/-5 percentage points of target needs no move
UNKNOWN_SHARE_LIMIT = Decimal("0.20")     # above this, drift cannot be trusted and the plan asks for input
SHORT_HORIZON_YEARS = 3                   # mirrors personal/constraints.py

# Direct-stock satellite inside the Indian equity bucket (Nifty 50 members only, so sectors are known to the engine).
SATELLITE_SHARE_OF_EQUITY = {"conservative": Decimal(0), "moderate": Decimal("0.15"), "aggressive": Decimal("0.25")}
SATELLITE_MAX_STOCKS = 5
SATELLITE_MAX_WEIGHT_OF_PORTFOLIO = Decimal("0.03")   # hard cap per stock, on the portfolio after the plan (leftover rounding never exceeds it)
SATELLITE_MAX_PER_SECTOR = 2                          # no forced sector coverage: at most two of the best-ranked stocks from one sector, and none from a sector with no candidate
SATELLITE_MIN_STOCKS = 3                              # fewer than this many eligible stocks and no direct stock is proposed
SATELLITE_MIN_LEG = Decimal("5000")                   # a direct stock below this is noise in a portfolio, so small amounts go to the index ETFs instead

# Core equity: broad index ETFs, split across a few underlyings. Only these named indices qualify; the NSE "category"
# text is free-form, so each is matched by an explicit pattern (see select.py).
CORE_EQUITY_SPLIT = {"large": Decimal("0.60"), "next50": Decimal("0.20"), "mid150": Decimal("0.20")}
CORE_EQUITY_SPLIT_CONSERVATIVE = {"large": Decimal(1)}

MIN_LEG_AMOUNT = Decimal("1000")          # the engine's own minimum action size
FEE_PCT = Decimal("0.003")                # the engine's illustrative friction

# International ETFs: Indian funds share a capped overseas-investment limit, so MON100-type ETFs have traded at large premiums
# to NAV (about 21% in recent coverage). This project has no iNAV feed to measure the premium, so the bucket is left unfilled
# and its weight moves to Indian equity, stated in the plan.
INTL_ETF_BLOCKED = True
INTL_REASON = ("Indian international ETFs have traded at large premiums to their NAV because of the shared overseas-investment limit "
               "(about 21% for MON100 in recent coverage), and this app cannot measure the premium; an international FUND bought at NAV in the "
               "Angel One app avoids that. The weight moved to Indian equity.")

# Below this a share or ETF purchase is mostly charges and the amount cannot be spread over several holdings, so the planner does not
# produce legs; it explains why and offers what works at any size (a fund bought by rupee amount).
SMALL_AMOUNT_FLOOR = MIN_LEG_AMOUNT * (1 + FEE_PCT)
SMALL_AMOUNT_VERSION = 1

LIQUID_PAYOUT_NOTE = ("Liquid ETFs come in two kinds: growth-NAV ones (e.g. LIQUIDCASE) whose price rises, and ones that hold a fixed price near ₹1,000 and "
                      "pay returns as extra units (e.g. LIQUIDBEES). The plan prefers the growth kind; the kind is inferred from the price.")


def declared() -> dict:
    """The policy as printed in every plan."""
    return {"version": POLICY_VERSION, "status": "unreviewed placeholders", "mix_by_band": {b: {k: str(v) for k, v in m.items()} for b, m in MIX.items()},
            "drift_band": str(DRIFT_BAND), "unknown_share_limit": str(UNKNOWN_SHARE_LIMIT), "short_horizon_years": SHORT_HORIZON_YEARS,
            "satellite_share_of_equity": {b: str(v) for b, v in SATELLITE_SHARE_OF_EQUITY.items()}, "satellite_max_stocks": SATELLITE_MAX_STOCKS, "satellite_max_per_sector": SATELLITE_MAX_PER_SECTOR,
            "satellite_max_weight_of_portfolio": str(SATELLITE_MAX_WEIGHT_OF_PORTFOLIO), "satellite_min_leg": str(SATELLITE_MIN_LEG), "core_equity_split": {k: str(v) for k, v in CORE_EQUITY_SPLIT.items()},
            "min_leg_amount": str(MIN_LEG_AMOUNT), "fee_pct": str(FEE_PCT), "international_etfs": "not used (premium risk, not measurable here)",
            "stock_checklist": "within a sector the highest-scoring liquid Nifty 50 stock above the floor; weights, floor and rules are in the stock checklist block (checklist-p0-unreviewed)",
            "etf_selection": "within an underlying: candidates are ETFs trading at least 20% as much as the most traded; the lowest KNOWN expense ratio wins (ties to the more traded); an unknown expense ratio never beats a known one; if none is known, the most traded"}
