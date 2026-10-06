"""A transparent checklist score (0-100) for Nifty 50 stocks, from fundamentals and price-history RISK descriptors only.

What this is and is not. It is a screen: it says how a company looks on common textbook measures (is it cheap or dear against its peers, does
it earn well, is it indebted, has its price been rough). It is NOT a forecast of returns, and it has not been tested against what prices did
afterwards. Every score is stored point-in-time so that test can be run later (the scoring ledger). Trend, momentum and the Kronos forecast are
shown beside it but ADD NO POINTS, because the study found no return effect for them.

Rules (all declared in policy.py and printed with every plan; all unreviewed placeholders):
- Four components with fixed weights: valuation, quality, balance sheet, risk. Each is 0-100.
- Valuation is relative: cheaper than the group on P/E (price over trailing EPS, computed by us at the current price), P/B and EV/EBITDA scores
  higher. Banks, insurers and NBFCs are compared only with each other and never on EV/EBITDA or debt/equity (their debt is their business).
- Negative or zero earnings make P/E "not meaningful": that scores 0 on the P/E part and is flagged. It is never treated as cheap.
- One knock-out: a company with negative or zero trailing earnings cannot score above the floor, whatever else it does well.
- A missing input is left out and named; the score is the weighted average of what is known and carries a coverage fraction. Below the
  coverage floor the stock is "not scored". A gap is never filled with zero (except the not-meaningful P/E above, which is a stated finding).
- Pure functions: no database, no network."""

from dataclasses import dataclass, field

CHECKLIST_VERSION = "checklist-p0-unreviewed"
WEIGHTS = {"valuation": 30, "quality": 35, "balance": 15, "risk": 20}
FLOOR = 60.0                 # below this a stock is not picked for new money (about the lowest fifth of the Nifty 50 on the first run)
MAX_PLAUSIBLE_EV_EBITDA = 100.0   # above this the provider figure is treated as a data error (it reported over 1,000 for two IT companies)
MIN_COVERAGE = 0.6           # share of total weight that must be known for a score to be given
MIN_GROUP_FOR_RELATIVE = 8   # a relative (percentile) measure needs at least this many peers with a value
PE_BASIS_BAND = (0.5, 1.6)   # calculated P/E over the provider's stored P/E must fall in this band, else price and EPS may be on different bases
FINANCIAL_SECTORS = {"Financial Services"}


@dataclass
class StockInput:
    symbol: str
    name: str
    sector: str | None
    price: float | None
    eps: float | None = None
    pe_stored: float | None = None
    pb: float | None = None
    ev_ebitda: float | None = None
    roe: float | None = None
    net_margin: float | None = None
    eps_growth: float | None = None
    revenue_growth: float | None = None
    free_cash_flow: float | None = None
    debt_to_equity: float | None = None
    vol_252: float | None = None
    max_dd_1y: float | None = None
    fundamentals_as_of: str | None = None
    shown_only: dict = field(default_factory=dict)   # trend, momentum, forecast: displayed, never scored

    @property
    def financial(self) -> bool:
        return (self.sector or "") in FINANCIAL_SECTORS


def pe_of(s: StockInput) -> tuple[float | None, str | None]:
    """(P/E, flag). Price over trailing EPS at the CURRENT price, with the provider's stored P/E as a basis check."""
    if s.eps is None or s.price is None:
        return None, None
    if s.eps <= 0:
        return None, "negative or zero earnings, so P/E is not meaningful"
    pe = s.price / s.eps
    if s.pe_stored is not None and s.pe_stored > 0 and not (PE_BASIS_BAND[0] <= pe / s.pe_stored <= PE_BASIS_BAND[1]):
        return None, "price and earnings per share may not be on the same basis (share count changed?), so P/E is not used"
    return pe, None


def _rank_points(value: float, peers: list[float]) -> float:
    """100 for the cheapest in the group down to 0 for the dearest (mid-rank for ties)."""
    below = sum(1 for p in peers if p < value)
    equal = sum(1 for p in peers if p == value)
    frac = (below + 0.5 * (equal - 1)) / max(len(peers) - 1, 1) if len(peers) > 1 else 0.5
    return round(100 * (1 - frac), 1)


def _ladder(x: float, steps: list[tuple[float, float]], otherwise: float) -> float:
    """steps: [(threshold, points)] checked in order, first with x > threshold wins."""
    for thr, pts in steps:
        if x > thr:
            return pts
    return otherwise


def _avg(parts: list[float]) -> float | None:
    return round(sum(parts) / len(parts), 1) if parts else None


def score_universe(stocks: list[StockInput]) -> list[dict]:
    pes = {s.symbol: pe_of(s) for s in stocks}
    groups: dict[bool, dict[str, list[float]]] = {False: {"pe": [], "pb": [], "ev": []}, True: {"pe": [], "pb": [], "ev": []}}
    for s in stocks:
        g = groups[s.financial]
        if pes[s.symbol][0] is not None:
            g["pe"].append(pes[s.symbol][0])
        if s.pb is not None and s.pb > 0:
            g["pb"].append(s.pb)
        if not s.financial and s.ev_ebitda is not None and 0 < s.ev_ebitda <= MAX_PLAUSIBLE_EV_EBITDA:
            g["ev"].append(s.ev_ebitda)

    out = []
    for s in stocks:
        g = groups[s.financial]
        pe, pe_flag = pes[s.symbol]
        flags: list[str] = [pe_flag] if pe_flag else []
        reasons: list[str] = []
        who = "banks, insurers and NBFCs" if s.financial else "other Nifty 50 stocks"

        # --- valuation (relative to the group)
        val_parts, val_inputs = [], {}
        if pe is not None and len(g["pe"]) >= MIN_GROUP_FOR_RELATIVE:
            p = _rank_points(pe, g["pe"]); val_parts.append(p); val_inputs["pe"] = round(pe, 1)
            if p <= 25: reasons.append(f"P/E {pe:.1f} is among the dearest fifth of {who}")
        elif pe_flag and "negative" in pe_flag:
            val_parts.append(0.0); val_inputs["pe"] = None
            reasons.append("negative earnings (P/E not meaningful)")
        if s.pb is not None and s.pb > 0 and len(g["pb"]) >= MIN_GROUP_FOR_RELATIVE:
            p = _rank_points(s.pb, g["pb"]); val_parts.append(p); val_inputs["pb"] = round(s.pb, 2)
            if p <= 25: reasons.append(f"price-to-book {s.pb:.1f} is among the dearest fifth of {who}")
        if not s.financial and s.ev_ebitda is not None and s.ev_ebitda > MAX_PLAUSIBLE_EV_EBITDA:
            flags.append(f"EV/EBITDA of {s.ev_ebitda:,.0f} from the data provider is not plausible, so it is not used")
        elif not s.financial and s.ev_ebitda is not None and s.ev_ebitda > 0 and len(g["ev"]) >= MIN_GROUP_FOR_RELATIVE:
            p = _rank_points(s.ev_ebitda, g["ev"]); val_parts.append(p); val_inputs["ev_ebitda"] = round(s.ev_ebitda, 1)
            if p <= 25: reasons.append(f"EV/EBITDA {s.ev_ebitda:.1f} is among the dearest fifth of {who}")

        # --- quality (absolute ladders, the same cut-offs the earlier fundamental sub-score used)
        q_parts, q_inputs = [], {}
        if s.roe is not None:
            p = _ladder(s.roe, [(0.20, 100), (0.15, 80), (0.10, 60), (0.05, 40)], 20); q_parts.append(p); q_inputs["roe"] = round(s.roe, 3)
            if p <= 40: reasons.append(f"return on equity {s.roe:.0%} is low")
        if not s.financial and s.net_margin is not None:
            p = _ladder(s.net_margin, [(0.20, 100), (0.10, 75), (0.03, 50)], 20); q_parts.append(p); q_inputs["net_margin"] = round(s.net_margin, 3)
            if p <= 20: reasons.append(f"net margin {s.net_margin:.0%} is thin")
        if s.eps_growth is not None:
            p = _ladder(s.eps_growth, [(0.15, 100), (0.05, 75), (-1e-9, 50)], 20); q_parts.append(p); q_inputs["eps_growth"] = round(s.eps_growth, 3)
            if p <= 20: reasons.append(f"earnings per share fell {abs(s.eps_growth):.0%}")
        if s.revenue_growth is not None:
            p = _ladder(s.revenue_growth, [(0.15, 100), (0.08, 75), (0.02, 50), (-1e-9, 30)], 10); q_parts.append(p); q_inputs["revenue_growth"] = round(s.revenue_growth, 3)
            if p <= 10: reasons.append(f"revenue shrank {abs(s.revenue_growth):.0%}")
        if not s.financial and s.free_cash_flow is not None:
            q_parts.append(100.0 if s.free_cash_flow > 0 else 20.0); q_inputs["free_cash_flow_positive"] = s.free_cash_flow > 0
            if s.free_cash_flow <= 0: reasons.append("free cash flow is negative")

        # --- balance sheet (not for financials: their debt is their business)
        b_parts, b_inputs = [], {}
        if not s.financial and s.debt_to_equity is not None:
            p = _ladder(-s.debt_to_equity, [(-0.5, 100), (-1.0, 80), (-2.0, 60), (-3.0, 40)], 20)
            b_parts.append(p); b_inputs["debt_to_equity"] = round(s.debt_to_equity, 2)
            if p <= 40: reasons.append(f"debt is {s.debt_to_equity:.1f} times equity")

        # --- risk descriptors from the price history (volatility and worst fall; both are about risk, not returns)
        r_parts, r_inputs = [], {}
        if s.vol_252 is not None:
            p = _ladder(-s.vol_252, [(-0.20, 100), (-0.28, 80), (-0.35, 60), (-0.45, 40)], 20); r_parts.append(p); r_inputs["vol_252"] = round(s.vol_252, 3)
            if p <= 40: reasons.append(f"its price has been jumpy ({s.vol_252:.0%} a year)")
        if s.max_dd_1y is not None:
            d = -abs(s.max_dd_1y)
            p = _ladder(d, [(-0.15, 100), (-0.25, 75), (-0.35, 50), (-0.50, 30)], 10); r_parts.append(p); r_inputs["max_drawdown_1y"] = round(d, 3)
            if p <= 30: reasons.append(f"it fell {abs(d):.0%} from its high within the year")

        comps = {"valuation": (_avg(val_parts), val_inputs), "quality": (_avg(q_parts), q_inputs), "balance": (_avg(b_parts), b_inputs), "risk": (_avg(r_parts), r_inputs)}
        known = {k: v for k, v in comps.items() if v[0] is not None}
        weight_known = sum(WEIGHTS[k] for k in known)
        coverage = weight_known / sum(WEIGHTS.values()) if not s.financial else weight_known / (sum(WEIGHTS.values()) - WEIGHTS["balance"])
        missing = [k for k, v in comps.items() if v[0] is None and not (k == "balance" and s.financial)]
        score = round(sum(WEIGHTS[k] * v[0] for k, v in known.items()) / weight_known, 1) if weight_known and coverage >= MIN_COVERAGE else None
        if score is not None and s.eps is not None and s.eps <= 0:
            score = min(score, round(FLOOR - 0.1, 1))
        if score is None:
            status = "not_scored"
        elif score < FLOOR:
            status = "below_floor"
        else:
            status = "eligible"
        out.append({"symbol": s.symbol, "name": s.name, "sector": s.sector, "financial": s.financial, "score": score, "coverage": round(coverage, 2), "status": status,
                    "components": {k: {"score": v[0], "weight": WEIGHTS[k], "inputs": v[1]} for k, v in comps.items() if not (k == "balance" and s.financial)},
                    "missing": missing, "flags": flags, "reasons": reasons, "pe": None if pe is None else round(pe, 1), "price": s.price,
                    "fundamentals_as_of": s.fundamentals_as_of, "shown_only": s.shown_only})
    return out
