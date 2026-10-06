"""Value / quality / momentum ranking of Nifty 50 stocks. Pure functions: no database, no network.

What this is. A deterministic, explainable screen built from three SEPARATE components, each the mean of percentile ranks of a few standard
measures against comparable businesses. It is an UNVALIDATED POLICY, not an optimised strategy: the component weights are equal by default,
configurable, and printed with every result. Nothing here forecasts returns, and nothing has been shown to predict them (see Model evidence).

Rules (all declared below, all unreviewed placeholders):
- Value: earnings yield (EPS over the current price, so negative earnings rank LAST and are never "cheap"), EBITDA over enterprise value, book yield,
  equity free-cash-flow yield. Quality: return on equity, margins, growth, low debt, dividend payout (capped at 100%), and (when their inputs exist) cash profitability and ACCRUALS,
  where higher accruals weaken quality. Momentum: 12-1 and 6-1 on total return averaged into ONE vote (no moving-average, RSI or MACD vote on top).
- Banks, NBFCs and insurers form their own group and are never judged on debt, EBITDA or enterprise value.
- Percentiles are taken against peers in the same sector, shrunk toward the whole group when the sector is small (weight n / (n + SHRINK_K)),
  after winsorising each measure at its 5th and 95th percentile so one extreme figure cannot stretch a scale.
- A denominator that is zero, negative or implausible gives NO value and a named reason, never a zero. A figure that contradicts its sibling
  (earnings over market cap versus earnings per share over price) removes the market-cap-based measures for that stock, named.
- A component needs enough measures and enough of the measures that exist in the group (coverage). If any component is unusable the stock is NOT
  ranked; a gap is never filled with zero and an incomplete stock never receives an inflated score.
- Risk (volatility, worst fall, liquidity) and data coverage are reported BESIDE the rank and never added to it. Liquidity, concentration,
  restrictions, funding and goal protections stay in the plan's gates."""

from dataclasses import dataclass, field

import numpy as np

RANK_VERSION = "stock-rank-p3-unvalidated"   # p2 (2026-10-02) added dividend payout; p3 turns on accruals, cash profitability and FCF yield from annual statements. Older rows stay stored but L9 scores only the current method
DEFAULT_WEIGHTS = {"value": 1.0, "quality": 1.0, "momentum": 1.0}
FLOOR = 60.0                      # a stock must score at least this to be a candidate for new money
MIN_METRICS = {"value": 2, "quality": 3, "momentum": 1}
MIN_COMPONENT_COVERAGE = 0.5      # share of the group's ACTIVE measures a stock must have for the component to count
MIN_ACTIVE_VALUES = 8             # a measure is "active" in a group only if at least this many stocks have it (else it is reported as inactive)
MIN_PEERS = 3                     # percentiles need at least this many comparable values
SHRINK_K = 4                      # sector weight in the percentile blend is n / (n + K)
WINSOR = (5.0, 95.0)
MAX_PLAUSIBLE_EV_EBITDA = 100.0
EPS_DISAGREE = 0.25                # relative gap between Yahoo's trailing EPS and the sum of NSE's last four quarters that is flagged (flag only, never a correction)
PAYOUT_CAP = 1.0                  # paying out more than earnings is not "more quality"
MAX_PLAUSIBLE_PAYOUT = 3.0        # dividends per share over EPS above this means the two are on different bases: measure dropped, flagged
CROSS_CHECK_BAND = (0.5, 2.0)     # (earnings / market cap) over (EPS / price) must fall in this band, else the market-cap figures are not trusted
FINANCIAL_SECTORS = {"Financial Services"}


def parse_weights(text: str | None) -> dict[str, float]:
    """"value:2,quality:1,momentum:1" -> normalised weights summing to 1. Anything malformed falls back to equal weights."""
    w = dict(DEFAULT_WEIGHTS)
    if text:
        try:
            parsed = {k.strip(): float(v) for k, v in (part.split(":") for part in text.split(",") if part.strip())}
            if set(parsed) == set(DEFAULT_WEIGHTS) and all(v >= 0 for v in parsed.values()) and sum(parsed.values()) > 0:
                w = parsed
        except ValueError:
            pass
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


@dataclass
class RankInput:
    symbol: str
    name: str
    sector: str | None
    price: float | None
    eps: float | None = None
    pat: float | None = None
    market_cap: float | None = None
    pb: float | None = None
    ev_ebitda: float | None = None
    free_cash_flow: float | None = None
    operating_cash_flow: float | None = None
    avg_total_assets: float | None = None      # mean of this and last fiscal year-end total assets (both required)
    annual_net_income: float | None = None     # operating_cash_flow, free_cash_flow, annual_net_income and avg_total_assets are all from ONE fiscal year's statements
    annual_period_end: str | None = None
    nse_eps_ttm: float | None = None           # sum of NSE's last four quarterly EPS: a cross-check only
    nse_period_end: str | None = None
    net_margin: float | None = None
    ebitda_margin: float | None = None
    revenue_growth: float | None = None
    eps_growth: float | None = None
    debt_to_equity: float | None = None
    roe_stored: float | None = None
    dividend_ttm: float | None = None           # cash dividends per share, last 365 days, in today's share terms
    dividend_reliable: bool = False             # False when a dividend in the window could not be parsed or scaled
    mom_12_1: float | None = None
    mom_6_1: float | None = None
    momentum_basis: str | None = None           # "total_return" or "price"
    fundamentals_as_of: str | None = None
    price_as_of: str | None = None
    risk: dict = field(default_factory=dict)    # vol_252, max_dd_1y, liquidity_value, circuit_days_20: shown, never scored

    @property
    def financial(self) -> bool:
        return (self.sector or "") in FINANCIAL_SECTORS


# ---------------------------------------------------------------------------------------------- measures

def earnings_yield(eps, price):
    if eps is None or price is None:
        return None, None
    if price <= 0:
        return None, "price is not positive"
    return eps / price, ("negative earnings: ranks last, never cheap" if eps <= 0 else None)


def market_cap_consistent(eps, price, pat, market_cap) -> tuple[bool, str | None]:
    """The market-cap-based measures are trusted only when earnings over market cap agrees with EPS over price. A mismatch (units, currency or share
    count) is what made two large IT companies look 60 times less profitable than they are."""
    if pat is None or market_cap is None or market_cap <= 0:
        return False, None
    if eps is None or price is None or price <= 0:
        return False, "cannot cross-check the market cap (no EPS or price)"
    a, b = pat / market_cap, eps / price
    if a * b <= 0:
        return (a == 0 and b == 0), "earnings over market cap and EPS over price disagree in sign, so market-cap figures are not used"
    ratio = a / b
    if not (CROSS_CHECK_BAND[0] <= ratio <= CROSS_CHECK_BAND[1]):
        return False, f"earnings over market cap is {ratio:.2f} times EPS over price, so market-cap figures are not used"
    return True, None


def ebitda_to_ev(ev_ebitda):
    if ev_ebitda is None:
        return None, None
    if ev_ebitda <= 0:
        return None, "EBITDA is not positive: EBITDA/EV not used"
    if ev_ebitda > MAX_PLAUSIBLE_EV_EBITDA:
        return None, f"EV/EBITDA of {ev_ebitda:,.0f} is not plausible: EBITDA/EV not used"
    return 1.0 / ev_ebitda, None


def book_yield(pb):
    return (None, "price-to-book is not positive: book yield not used") if pb is not None and pb <= 0 else (None if pb is None else 1.0 / pb, None)


def fcf_yield(fcf, market_cap, ok):
    return (fcf / market_cap, None) if ok and fcf is not None and market_cap and market_cap > 0 else (None, None)


def derived_roe(pat, pb, market_cap, ok):
    """Earnings over book equity, where book equity = market cap / price-to-book (current book value, not an average)."""
    if ok and pat is not None and pb is not None and pb > 0 and market_cap and market_cap > 0:
        return pat * pb / market_cap
    return None


def payout_ratio(dps, eps, reliable) -> tuple[float | None, str | None]:
    """Trailing dividends per share over trailing EPS, capped at 1. A non-payer is a real 0 (the dividend feed covers the window). Undefined for losses.
    Why it is in quality: in India profitability AND payout drive the quality premium (low payout goes with promoters diverting profit; IIMA 2022)."""
    if not reliable or dps is None or eps is None:
        return None, None
    if eps <= 0:
        return None, "negative earnings: payout not defined"
    ratio = dps / eps
    if ratio > MAX_PLAUSIBLE_PAYOUT:
        return None, f"dividends per share are {ratio:.1f}x EPS: different bases, payout not used"
    return min(ratio, PAYOUT_CAP), None


def eps_cross_check(s: "RankInput") -> list[str]:
    """Flags only. A disagreement may be a bonus or split between quarters, so nothing is corrected or dropped here."""
    out = []
    if s.eps is not None and s.nse_eps_ttm is not None:
        gap = abs(s.eps - s.nse_eps_ttm) / max(abs(s.nse_eps_ttm), 1e-9)
        if gap > EPS_DISAGREE:
            out.append(f"trailing EPS differs between sources: Yahoo {s.eps:.1f}, NSE filings {s.nse_eps_ttm:.1f} ({gap:.0%} apart); check for a bonus or split before trusting earnings measures")
    if s.nse_period_end and s.fundamentals_as_of and s.nse_period_end > s.fundamentals_as_of:
        out.append(f"NSE has results for the quarter ended {s.nse_period_end}; Yahoo's figures are for {s.fundamentals_as_of}")
    return out


def cash_profitability(ocf, avg_assets):
    return ocf / avg_assets if ocf is not None and avg_assets is not None and avg_assets > 0 else None


def accruals_ratio(net_income, ocf, avg_assets):
    """(net income - operating cash flow) / average assets. Higher means more of the profit is not backed by cash, which weakens quality."""
    return (net_income - ocf) / avg_assets if None not in (net_income, ocf, avg_assets) and avg_assets > 0 else None


# name -> (label, formatter, higher_is_better)
INFO = {
    "earnings_yield": ("earnings yield", lambda v: f"{v:.1%}", True), "ebitda_ev": ("EBITDA / enterprise value", lambda v: f"{v:.1%}", True),
    "book_yield": ("book yield (1 / price-to-book)", lambda v: f"{v:.1%}", True), "fcf_yield": ("free-cash-flow yield", lambda v: f"{v:.1%}", True),
    "roe": ("return on equity", lambda v: f"{v:.0%}", True), "net_margin": ("net margin", lambda v: f"{v:.0%}", True), "ebitda_margin": ("EBITDA margin", lambda v: f"{v:.0%}", True),
    "eps_growth": ("earnings growth", lambda v: f"{v:+.0%}", True), "revenue_growth": ("revenue growth", lambda v: f"{v:+.0%}", True),
    "debt_to_equity": ("debt to equity", lambda v: f"{v:.2f}", False), "cash_profitability": ("cash profitability", lambda v: f"{v:.1%}", True),
    "accruals": ("accruals", lambda v: f"{v:+.1%}", False), "payout": ("dividend payout", lambda v: f"{v:.0%}", True),
    "mom_12_1": ("12-1 month return", lambda v: f"{v:+.0%}", True), "mom_6_1": ("6-1 month return", lambda v: f"{v:+.0%}", True),
}
LAYOUT = {
    False: {"value": ["earnings_yield", "ebitda_ev", "book_yield", "fcf_yield"],
            "quality": ["roe", "net_margin", "ebitda_margin", "eps_growth", "revenue_growth", "debt_to_equity", "payout", "cash_profitability", "accruals"], "momentum": ["mom_12_1", "mom_6_1"]},
    True: {"value": ["earnings_yield", "book_yield"], "quality": ["roe", "eps_growth", "revenue_growth", "payout"], "momentum": ["mom_12_1", "mom_6_1"]},
}


def raw_measures(s: RankInput) -> tuple[dict[str, float | None], list[str], bool]:
    """-> ({measure: value or None}, data flags, market-cap figures trusted)."""
    flags: list[str] = []
    ey, f = earnings_yield(s.eps, s.price)
    flags += [f] if f and "ranks last" not in f else []
    ok, f = market_cap_consistent(s.eps, s.price, s.pat, s.market_cap)
    if f:
        flags.append(f)
    ev, f = ebitda_to_ev(s.ev_ebitda) if not s.financial else (None, None)
    flags += [f] if f else []
    by, f = book_yield(s.pb)
    flags += [f] if f else []
    roe = derived_roe(s.pat, s.pb, s.market_cap, ok)
    if roe is None:
        roe = s.roe_stored
    po, f = payout_ratio(s.dividend_ttm, s.eps, s.dividend_reliable)
    flags += [f] if f else []
    flags += eps_cross_check(s)
    vals = {"earnings_yield": ey, "ebitda_ev": ev, "book_yield": by, "fcf_yield": fcf_yield(s.free_cash_flow, s.market_cap, ok)[0], "roe": roe,
            "net_margin": None if s.financial else s.net_margin, "ebitda_margin": None if s.financial else s.ebitda_margin, "eps_growth": s.eps_growth, "revenue_growth": s.revenue_growth,
            "debt_to_equity": None if s.financial else s.debt_to_equity, "cash_profitability": cash_profitability(s.operating_cash_flow, s.avg_total_assets),
            "accruals": accruals_ratio(s.annual_net_income, s.operating_cash_flow, s.avg_total_assets), "payout": po, "mom_12_1": s.mom_12_1, "mom_6_1": s.mom_6_1}
    if s.financial:
        for k in ("ebitda_ev", "fcf_yield", "net_margin", "ebitda_margin", "debt_to_equity", "cash_profitability", "accruals"):
            vals[k] = None
    return vals, flags, ok


# ---------------------------------------------------------------------------------------------- percentiles

def _winsorise(values: list[float]) -> tuple[float, float]:
    # "higher" at the bottom and "lower" at the top keep the clip points on real observations, so one extreme value is genuinely pulled in
    # (interpolating between the two largest values of a small group would barely move it).
    return float(np.percentile(values, WINSOR[0], method="higher")), float(np.percentile(values, WINSOR[1], method="lower"))


def _pct(value: float, peers: list[float]) -> float | None:
    """Mid-rank percentile 0-100 of `value` among `peers` (which include it); None with too few peers."""
    n = len(peers)
    if n < MIN_PEERS:
        return None
    below = sum(1 for p in peers if p < value)
    equal = sum(1 for p in peers if p == value)
    return round(100.0 * (below + 0.5 * (equal - 1)) / (n - 1), 1)


def score_universe(stocks: list[RankInput], weights: dict[str, float] | None = None, floor: float = FLOOR) -> list[dict]:
    w = weights or parse_weights(None)
    per: dict[str, dict] = {}
    for s in stocks:
        vals, flags, ok = raw_measures(s)
        per[s.symbol] = {"vals": vals, "flags": flags, "mcap_ok": ok}

    # which measures are ACTIVE in each type group (enough stocks have a value); inactive ones are reported, not penalised
    groups: dict[bool, list[RankInput]] = {False: [s for s in stocks if not s.financial], True: [s for s in stocks if s.financial]}
    active: dict[bool, set[str]] = {}
    for fin, members in groups.items():
        active[fin] = {m for comp in LAYOUT[fin].values() for m in comp if sum(1 for s in members if per[s.symbol]["vals"].get(m) is not None) >= MIN_ACTIVE_VALUES}

    # percentile per (stock, measure): sector peers shrunk toward the type group
    pct: dict[tuple[str, str], dict] = {}
    for fin, members in groups.items():
        by_sector: dict[str | None, list[RankInput]] = {}
        for s in members:
            by_sector.setdefault(s.sector, []).append(s)
        for m in active[fin]:
            sign = 1.0 if INFO[m][2] else -1.0
            have = [s for s in members if per[s.symbol]["vals"].get(m) is not None]
            lo, hi = _winsorise([per[s.symbol]["vals"][m] for s in have])
            win = {s.symbol: min(max(per[s.symbol]["vals"][m], lo), hi) * sign for s in have}
            universe_vals = list(win.values())
            for s in have:
                u = _pct(win[s.symbol], universe_vals)
                sector_have = [x for x in by_sector[s.sector] if x.symbol in win]
                sec = _pct(win[s.symbol], [win[x.symbol] for x in sector_have]) if len(sector_have) >= MIN_PEERS else None
                n = len(sector_have)
                p = u if sec is None or len(by_sector) == 1 else (n / (n + SHRINK_K)) * sec + (SHRINK_K / (n + SHRINK_K)) * u
                if p is not None:
                    pct[(s.symbol, m)] = {"raw": per[s.symbol]["vals"][m], "winsorised": win[s.symbol] * sign, "percentile": round(p, 1), "peer_n": n, "universe_n": len(universe_vals)}

    out = []
    for s in stocks:
        fin = s.financial
        comps: dict[str, dict] = {}
        for cname, measures in LAYOUT[fin].items():
            act = [m for m in measures if m in active[fin]]
            got = {m: pct[(s.symbol, m)] for m in act if (s.symbol, m) in pct}
            coverage = len(got) / len(act) if act else 0.0
            usable = len(got) >= MIN_METRICS[cname] and coverage >= MIN_COMPONENT_COVERAGE and (cname != "momentum" or "mom_12_1" in got)
            comps[cname] = {"score": round(sum(g["percentile"] for g in got.values()) / len(got), 1) if got else None, "usable": usable, "coverage": round(coverage, 2),
                            "n_measures": len(got), "n_active": len(act), "measures": got, "missing": [m for m in act if m not in got],
                            "inactive": [m for m in measures if m not in active[fin]]}
        usable_all = all(c["usable"] for c in comps.values())
        composite = round(sum(w[k] * comps[k]["score"] for k in comps) / sum(w.values()), 1) if usable_all else None
        reasons = [f"{k} component is not usable ({c['n_measures']} of {c['n_active']} measures known)" for k, c in comps.items() if not c["usable"]]
        status = "not_ranked" if composite is None else "below_floor" if composite < floor else "eligible"
        strengths, weaknesses = [], []
        for cname, c in comps.items():
            for m, g in c["measures"].items():
                label, fmt, _ = INFO[m]
                text = f"{label} {fmt(g['raw'])} ({cname}, better than {g['percentile']:.0f}% of peers)"
                if g["percentile"] >= 75:
                    strengths.append((g["percentile"], text))
                elif g["percentile"] <= 25:
                    weaknesses.append((g["percentile"], text.replace("better than", "better than only")))
        if per[s.symbol]["vals"].get("earnings_yield") is not None and per[s.symbol]["vals"]["earnings_yield"] <= 0:
            weaknesses.append((0.0, "negative earnings (never treated as cheap)"))
        out.append({"symbol": s.symbol, "name": s.name, "sector": s.sector, "financial": fin, "composite": composite, "status": status, "components": comps,
                    "weights": w, "coverage": round(sum(c["coverage"] for c in comps.values()) / 3, 2), "reasons_not_ranked": reasons, "flags": per[s.symbol]["flags"],
                    "strengths": [t for _, t in sorted(strengths, reverse=True)[:3]], "weaknesses": [t for _, t in sorted(weaknesses)[:3]],
                    "market_cap_trusted": per[s.symbol]["mcap_ok"], "market_cap": s.market_cap if per[s.symbol]["mcap_ok"] else None, "price": s.price, "momentum_basis": s.momentum_basis,
                    "dates": {"fundamentals_as_of": s.fundamentals_as_of, "price_as_of": s.price_as_of}, "risk": s.risk})
    ranked = sorted((r for r in out if r["composite"] is not None), key=lambda r: (-r["composite"], r["symbol"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
        r["rank_of"] = len(ranked)
    for r in out:
        r.setdefault("rank", None)
        r.setdefault("rank_of", len(ranked))
    return out
