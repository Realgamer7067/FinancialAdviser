"""Pure allocation planner: target mix, drift, and a BUY-ONLY plan for new money.

No sells are ever proposed: tax lots are unknown, so a sale's tax cannot be estimated. A bucket above its target gets
"point future money elsewhere". Every number comes from policy.py (declared in the output) or from the inputs; nothing is
fitted or forecast. The plan is a proposal for the owner's own money, executed by hand in Angel One."""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.portfolio_intelligence.allocation import policy as P

_ZERO = Decimal(0)
_PAISE = Decimal("0.01")


def q(x: Decimal) -> Decimal:
    return x.quantize(_PAISE, rounding=ROUND_HALF_UP)


def s(x: Decimal | None) -> str | None:
    return None if x is None else format(x.normalize(), "f")


def units_for(amount: Decimal, price: Decimal, lot: int, fee: Decimal) -> int:
    return int(((amount / (price * (1 + fee))) / lot).to_integral_value(rounding=ROUND_FLOOR)) * lot


def debit_for(units: int, price: Decimal, fee: Decimal) -> Decimal:
    """What the engine will take from cash for `units`: the trade value plus the friction on it, each rounded to the paisa."""
    trade = q(Decimal(units) * price)
    return trade + q(trade * fee)


def budget_for(units: int, price: Decimal, fee: Decimal) -> Decimal:
    """The amount to hand the engine so that flooring gives back exactly `units` (rounded UP to the paisa)."""
    trade = q(Decimal(units) * price)
    return (trade * (1 + fee)).quantize(_PAISE, rounding=ROUND_CEILING)


def decide_mix(*, tolerance: dict, constraints: dict, what_if_band: str | None) -> dict:
    """Which mix applies, and why. Gates 1 and 2 of the policy (3 is applied to values later)."""
    if what_if_band is not None:
        if what_if_band not in P.MIX:
            raise ValueError("what_if_band must be conservative, moderate or aggressive")
        return {"source": "what_if_band", "band": what_if_band, "mix": dict(P.MIX[what_if_band]), "needs_input": True,
                "reasons": ["this is a what-if: your own risk answers decide the real plan"]
                           + ([f"added risk is currently blocked ({', '.join(constraints['limiting_factors'])}), so the engine will not clear the risk legs"]
                              if not constraints["risk_increasing_allowed"] else [])}
    if tolerance["status"] != "ready":
        return {"source": "safe_only_no_tolerance", "band": None, "mix": dict(P.SAFE_ONLY), "needs_input": True,
                "reasons": ["your risk tolerance is not known (answer the three risk questions), so only the safe bucket is used"]}
    if not constraints["risk_increasing_allowed"]:
        return {"source": "safe_only_capacity", "band": tolerance["band"], "mix": dict(P.SAFE_ONLY), "needs_input": True,
                "reasons": [f"added risk is blocked by: {', '.join(constraints['limiting_factors'])}, so only the safe bucket is used"]}
    return {"source": "profile_band", "band": tolerance["band"], "mix": dict(P.MIX[tolerance["band"]]), "needs_input": False, "reasons": []}


def target_values(mix: dict, base_total: Decimal, short_horizon_claimed: Decimal) -> tuple[dict, list[str]]:
    """Weights -> rupee targets on the classified base. International weight moves to Indian equity (policy); money claimed for
    goals due within 3 years is held in the safe bucket first and the risk buckets share what is left."""
    notes = []
    w = dict(mix)
    if P.INTL_ETF_BLOCKED and w["equity_intl"] > 0:
        w["equity_india"] += w["equity_intl"]
        notes.append(P.INTL_REASON)
        w["equity_intl"] = _ZERO
    vals = {b: w[b] * base_total for b in P.BUCKETS}
    if short_horizon_claimed > 0 and vals["debt"] < short_horizon_claimed:
        risk_total = sum(vals[b] for b in P.BUCKETS if b != "debt")
        keep = max(base_total - short_horizon_claimed, _ZERO)
        scale = (keep / risk_total) if risk_total > 0 else _ZERO
        for b in P.BUCKETS:
            if b != "debt":
                vals[b] *= scale
        vals["debt"] = base_total - sum(vals[b] for b in P.BUCKETS if b != "debt")
        notes.append(f"₹{s(q(short_horizon_claimed))} is claimed for goals due within {P.SHORT_HORIZON_YEARS} years, so the safe bucket is raised to cover it before any risk bucket")
    return vals, notes


def allocate_new_money(new_money: Decimal, targets: dict, current: dict, fillable: set[str], weights: dict) -> dict:
    """Buy-only: fill the most underweight buckets first; once every shortfall is closed, split the rest by target weight.
    Buckets that cannot be filled (no instrument) get nothing and their share moves to the others."""
    short = {b: max(targets[b] - current.get(b, _ZERO), _ZERO) if b in fillable else _ZERO for b in P.BUCKETS}
    tot_short = sum(short.values())
    if new_money <= 0 or not fillable:
        return {b: _ZERO for b in P.BUCKETS}
    if tot_short >= new_money:
        return {b: new_money * short[b] / tot_short for b in P.BUCKETS}
    rest = new_money - tot_short
    wsum = sum(weights[b] for b in fillable)
    out = {b: short[b] + (rest * weights[b] / wsum if b in fillable and wsum > 0 else _ZERO) for b in P.BUCKETS}
    return out


def consolidate(amounts: dict, shortfall: dict, min_amount: Decimal, fee: Decimal) -> dict:
    """Drop buckets too small to clear the minimum leg and give their money to the bucket with the largest remaining shortfall,
    so a small amount becomes fewer, larger legs instead of legs the engine would reject."""
    floor = min_amount * (1 + fee)
    amounts = dict(amounts)
    while True:
        small = [b for b, a in amounts.items() if _ZERO < a < floor]
        if not small:
            return amounts
        b = min(small, key=lambda x: (amounts[x], x))
        moved = amounts.pop(b)
        amounts[b] = _ZERO
        keep = [x for x, a in amounts.items() if a > 0 and x != b]
        dest = max(keep, key=lambda x: (shortfall.get(x, _ZERO), amounts[x], x)) if keep else b
        amounts[dest] = amounts.get(dest, _ZERO) + moved
        if dest == b:
            return amounts


def split_equity(amount: Decimal, band: str | None, core: dict, satellites: list[dict], base_total: Decimal, fee: Decimal) -> tuple[list[dict], list[str]]:
    """Indian-equity amount -> core index-ETF legs (+ a small equal-weight Nifty-50 stock satellite when the amount allows)."""
    notes: list[str] = []
    share = P.SATELLITE_SHARE_OF_EQUITY.get(band or "", _ZERO)
    legs: list[dict] = []
    sat_amount = amount * share
    n = min(P.SATELLITE_MAX_STOCKS, len(satellites))
    per_stock = (sat_amount / n) if n else _ZERO
    cap = P.SATELLITE_MAX_WEIGHT_OF_PORTFOLIO * base_total
    while n >= 3 and per_stock < P.SATELLITE_MIN_LEG:
        n -= 1
        per_stock = (sat_amount / n) if n else _ZERO
    if n < 3:
        if share > 0 and 0 < len(satellites) < 3:
            notes.append("fewer than three stocks clear the ranking floor and the safety checks, so no direct stocks are suggested; it goes into the index ETFs")
        elif share > 0 and satellites:
            notes.append("the amount is too small to hold at least three separate stocks sensibly, so no direct stocks are suggested; it goes into the index ETFs")
        n, sat_amount, per_stock = 0, _ZERO, _ZERO
    elif per_stock > cap:
        per_stock = q(cap)
        sat_amount = per_stock * n
        notes.append(f"each stock is capped at {P.SATELLITE_MAX_WEIGHT_OF_PORTFOLIO:.0%} of the portfolio, so some of the stock share goes into the index ETFs")
    for st in satellites[:n]:
        legs.append({"role": "satellite", "bucket": "equity_india", "inst": st, "budget": per_stock, "cap": cap})
    core_amount = amount - sat_amount
    split = P.CORE_EQUITY_SPLIT_CONSERVATIVE if band == "conservative" else P.CORE_EQUITY_SPLIT
    avail = {k: v for k, v in split.items() if k in core}
    tot = sum(avail.values())
    parts = {k: core_amount * v / tot for k, v in avail.items()} if tot > 0 else {}
    parts = consolidate(parts, {k: _ZERO for k in parts}, P.MIN_LEG_AMOUNT, fee) if parts else {}
    for k, amt in sorted(parts.items()):
        if amt > 0:
            legs.append({"role": "core", "bucket": "equity_india", "inst": core[k], "budget": amt, "underlying": k})
    return legs, notes


def build_plan(*, tolerance: dict, constraints: dict, what_if_band: str | None, new_money: Decimal, holdings: dict, short_horizon_claimed: Decimal,
               candidates: dict, fee_pct: Decimal = P.FEE_PCT) -> dict:
    """candidates: {"core": {"large"|"next50"|"mid150": inst}, "satellite": [inst...], "gold": [inst...], "debt": [inst...]} where inst =
    {id, symbol, name, kind, isin, lot_size, price, price_as_of, sector, turnover, why}."""
    if new_money < 0:
        raise ValueError("new_money must be zero or positive")
    mix = decide_mix(tolerance=tolerance, constraints=constraints, what_if_band=what_if_band)
    cur = {b: holdings["buckets"].get(b, _ZERO) for b in P.BUCKETS}
    classified = sum(cur.values())
    unknown = holdings["unknown"]
    known_total = classified + unknown
    unknown_share = (unknown / known_total) if known_total > 0 else _ZERO
    base_total = classified + new_money
    targets, notes = target_values(mix["mix"], base_total, short_horizon_claimed)
    weights = {b: (targets[b] / base_total if base_total > 0 else _ZERO) for b in P.BUCKETS}
    cur_w = {b: (cur[b] / classified if classified > 0 else None) for b in P.BUCKETS}

    fillable = {b for b in P.BUCKETS if targets[b] > 0 and (bool(candidates["gold"]) if b == "gold" else bool(candidates["debt"]) if b == "debt"
                                                            else bool(candidates["core"]) if b == "equity_india" else False)}
    warnings = list(notes)
    for b in P.BUCKETS:
        if targets[b] > 0 and b not in fillable and b != "equity_intl":
            warnings.append(f"no suitable instrument was found for {P.BUCKET_LABEL[b]} (liquid, fresh price, clean history), so nothing is suggested there")
    raw = allocate_new_money(new_money, targets, cur, fillable, weights)
    shortfall = {b: max(targets[b] - cur[b], _ZERO) for b in P.BUCKETS}
    amounts = consolidate(raw, shortfall, P.MIN_LEG_AMOUNT, fee_pct)
    if _ZERO < new_money < P.SMALL_AMOUNT_FLOOR:
        amounts = {}      # below the smallest purchase the engine accepts: no legs, the caller explains what works at this size

    legs: list[dict] = []
    for b in P.BUCKETS:
        amt = amounts.get(b, _ZERO)
        if amt <= 0:
            continue
        if b == "equity_india":
            l, n = split_equity(amt, mix["band"] if mix["source"] in ("profile_band", "what_if_band") else None, candidates["core"], candidates["satellite"], base_total, fee_pct)
            legs += l
            warnings += n
        else:
            legs.append({"role": "safe" if b == "debt" else "core", "bucket": b, "inst": (candidates["gold"] if b == "gold" else candidates["debt"])[0], "budget": amt})

    # whole units only, then spend the rounding leftovers one lot at a time on the leg furthest below its budget
    for leg in legs:
        i = leg["inst"]
        leg["units"] = units_for(leg["budget"], i["price"], i["lot_size"], fee_pct)
    spent = sum((debit_for(l["units"], l["inst"]["price"], fee_pct) for l in legs), _ZERO)
    leftover = new_money - spent
    while legs:
        order = sorted(legs, key=lambda l: (-(l["budget"] - debit_for(l["units"], l["inst"]["price"], fee_pct)), l["inst"]["symbol"]))
        for l in order:
            step = debit_for(l["units"] + l["inst"]["lot_size"], l["inst"]["price"], fee_pct) - debit_for(l["units"], l["inst"]["price"], fee_pct)
            nxt = debit_for(l["units"] + l["inst"]["lot_size"], l["inst"]["price"], fee_pct)
            if l.get("cap") is not None and nxt > l["cap"]:
                continue   # a direct stock never goes past its hard cap, even to use up rounding leftovers
            if step <= leftover and l["units"] + l["inst"]["lot_size"] > 0:
                l["units"] += l["inst"]["lot_size"]
                leftover -= step
                break
        else:
            break
    legs = [l for l in legs if l["units"] > 0]
    out_legs = []
    for l in legs:
        i = l["inst"]
        debit = debit_for(l["units"], i["price"], fee_pct)
        out_legs.append({"bucket": l["bucket"], "role": l["role"], "underlying": l.get("underlying"), "instrument_id": i["id"], "symbol": i["symbol"], "name": i["name"],
                         "kind": i["kind"], "isin": i.get("isin"), "engine_key": i.get("instrument_id") or i["id"], "cash_like": bool(i.get("cash_like")), "units": l["units"], "price": s(i["price"]), "price_as_of": i["price_as_of"].isoformat(),
                         "planned_debit": s(debit), "budget_for_engine": s(budget_for(l["units"], i["price"], fee_pct)), "sector": i.get("sector"), "why": i.get("why")})
    spent = sum((Decimal(l["planned_debit"]) for l in out_legs), _ZERO)

    drift = []
    for b in P.BUCKETS:
        tw = weights[b]
        cw = cur_w[b]
        off = cw is not None and abs(cw - tw) > P.DRIFT_BAND
        drift.append({"bucket": b, "label": P.BUCKET_LABEL[b], "target_weight": s(q(tw * 100) / 100), "current_weight": None if cw is None else s(q(cw * 100) / 100),
                      "current_value": s(q(cur[b])), "target_value": s(q(targets[b])), "outside_band": bool(off),
                      "direction": None if not off else ("above target" if cw > tw else "below target"),
                      "note": ("above target: point future money elsewhere; no sale is suggested because the tax on a sale cannot be estimated without purchase lots"
                               if off and cw > tw else None)})
    reasons = list(mix["reasons"])
    status = "needs_input" if mix["needs_input"] else "ready"
    if unknown_share > P.UNKNOWN_SHARE_LIMIT:
        status = "needs_input"
        reasons.append(f"{unknown_share:.0%} of what you hold could not be placed in an asset bucket (limit {P.UNKNOWN_SHARE_LIMIT:.0%}), so its drift from target cannot be trusted")
    if not out_legs:
        status = "needs_input" if status == "needs_input" else "nothing_to_do"
        reasons.append("no purchase is suggested" + (" (add new money to get a plan)" if new_money == 0 else
                                                      " (the amount is below the smallest purchase this planner proposes; see the options below)" if new_money < P.SMALL_AMOUNT_FLOOR else ""))
    return {
        "policy": P.declared(), "mix": {"source": mix["source"], "band": mix["band"], "needs_input": mix["needs_input"]},
        "status": status, "reasons": reasons, "warnings": warnings,
        "new_money": s(new_money), "classified_total": s(q(classified)), "unknown_value": s(q(unknown)), "unknown_share": s(q(unknown_share * 100) / 100), "cash_not_counted": s(q(holdings["cash"])),
        "base_total_after_plan": s(q(base_total)), "target": {b: {"weight": s(q(weights[b] * 100) / 100), "value": s(q(targets[b]))} for b in P.BUCKETS},
        "drift": drift, "legs": out_legs, "spent": s(q(spent)), "leftover_cash": s(q(new_money - spent)),
        "no_sales_note": "No sale is ever suggested here: the tax on a sale cannot be estimated without purchase lots.",
        "satellite_note": ("Direct stocks are chosen only from the Nifty 50, equal weight, from those that are liquid and have clean price history, "
                           "ranked on value, quality and momentum together (equal weights, an unvalidated policy), at least the floor, at most two per sector, none forced. The ranking is a screen; it is not a forecast "
                           "and has not yet been tested against later prices (only its momentum part can be tested on past data). Trend, volatility and the price forecast add no points. Index ETFs have no look-through in the risk engine, so a stock bought on "
                           "top of an ETF that already holds it understates that stock's concentration (the ranking card shows an approximate look-through for Nifty 50 index funds)."),
        "liquid_note": P.LIQUID_PAYOUT_NOTE,
    }
