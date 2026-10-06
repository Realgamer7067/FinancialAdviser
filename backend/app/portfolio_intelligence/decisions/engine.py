"""Counterfactual action evaluation (plan sections 5.3, 12.7). Pure.

Freeze one baseline (positions, valuation, constraints, goals). Apply the SAME
external contribution/withdrawal to HOLD and to every alternative; HOLD keeps
new money as cash. Each alternative is applied to a copy of the baseline, run
through independent hard gates, then the WHOLE risk picture is recomputed with
the same code /risk uses, and compared with HOLD by metric deltas, materiality
thresholds and a Pareto rule. No scalar score, no return forecast, no claim a
change is "best": the default is always HOLD. Conservation (to the paisa):

    assets_after + friction = assets_before + contribution - withdrawal

Unknown cost is never zero; sale tax is unknown without tax lots, so a sale is
a review-required PREVIEW only."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.portfolio_intelligence.goals.projection import SCENARIOS, project_goal
from app.portfolio_intelligence.risk.exposure import asset_class_of, compute_exposures, compute_liquidity
from app.portfolio_intelligence.risk.stress import CATALOG, resolve_scenario, run_scenario

ENGINE_VERSION = "actions-v1"
POLICY_VERSION = "decision-p0-unreviewed"
_PAISE = Decimal("0.01")
_ZERO = Decimal(0)

# --- unreviewed policy defaults (every one is declared in the output) -----------------------
POLICY = {
    "version": POLICY_VERSION,
    "default_fee_pct": Decimal("0.003"),        # illustrative friction: statutory charges + slippage assumption
    "max_fee_pct": Decimal("0.05"),
    "max_cost_pct_of_trade": Decimal("0.01"),
    "min_action_amount": Decimal("1000"),
    "max_single_issuer_weight": Decimal("0.25"),
    "max_sector_weight": Decimal("0.40"),
    "min_fresh_value_share": Decimal("0.80"),
    "concentration_slack": Decimal("0.005"),    # drift from friction alone is not "worsening"
    "price_stale_days": 10,
    "materiality": {                              # metric -> (direction, threshold)
        "largest_issuer_weight": ("lower", Decimal("0.02")),
        "largest_sector_weight": ("lower", Decimal("0.02")),
        "worst_scenario_loss_pct": ("lower_magnitude", Decimal("0.01")),
        "effective_positions": ("higher", Decimal("0.25")),
        "cash_months": ("higher", Decimal("0.5")),
        "unknown_weight": ("lower", Decimal("0.02")),
        "goal_shortfall_base": ("lower", Decimal("1000")),
    },
}
RISK_INCREASING_CLASSES = {"equity", "fund_or_etf", "gold"}


class ActionInvalid(ValueError):
    """The request itself is malformed (422); distinct from a valid action failing a gate."""


def q(x: Decimal) -> Decimal:
    return x.quantize(_PAISE, rounding=ROUND_HALF_UP)


def f(x: Decimal | None) -> str | None:
    return None if x is None else format(x.normalize(), "f")


def gate(gid: str, result: str, observed, allowed, source: str, reason: str) -> dict:
    return {"gate_id": gid, "result": result, "observed": observed, "allowed": allowed, "data_source": source, "reason": reason}


def candidate_hash(positions: list[dict]) -> str:
    rows = sorted((p["position_id"], p["account_label"], p["asset_type"], f(p["value"])) for p in positions)
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


# ------------------------------------------------------------------------------------------------
# metrics (same exposure/stress code as /risk)
# ------------------------------------------------------------------------------------------------

_NON_SECTOR = {"non_equity", "unclassified_equity", "fund_lookthrough_unknown"}


def metrics_for(positions: list[dict], capacity: dict, claims_by_position: dict) -> dict:
    exp = compute_exposures(positions)
    liq = compute_liquidity(positions, claims_by_position, capacity)
    iss = exp["issuer_concentration"]
    sectors = [Decimal(b["weight"]) for b in exp["sector"]["buckets"] if b["bucket"] not in _NON_SECTOR and b["weight"] is not None]
    worst_pct, worst_id, outside = None, None, None
    for c in CATALOG:
        if c["status"] != "supported":
            continue
        r = run_scenario(resolve_scenario({"id": c["id"]}), positions)
        pct = r["modeled_change_pct_of_known_total"]
        if pct is not None and (worst_pct is None or Decimal(pct) < worst_pct):
            worst_pct, worst_id = Decimal(pct), c["id"]
        outside = r["outside_coverage"]["share_of_known_total"] if c["id"] == "equity_broad_-20" else outside
    return {
        "known_total": Decimal(exp["asset_mix"]["known_total"]),
        "largest_issuer_weight": Decimal(iss["largest_issuer_weight"]) if iss.get("largest_issuer_weight") else None,
        "effective_positions": Decimal(iss["effective_positions_over_identified"]) if iss.get("effective_positions_over_identified") else None,
        "largest_sector_weight": max(sectors) if sectors else None,
        "direct_equity_share": Decimal(exp["asset_mix"]["direct_equity_share"]) if exp["asset_mix"]["direct_equity_share"] else None,
        "equity_share_upper_bound": Decimal(exp["asset_mix"]["equity_share_upper_bound"]) if exp["asset_mix"]["equity_share_upper_bound"] else None,
        "unknown_weight": Decimal(exp["sector"]["unknown_weight"]) if exp["sector"]["unknown_weight"] else None,
        "worst_scenario_loss_pct": worst_pct, "worst_scenario_id": worst_id,
        "scenario_outside_coverage_share": Decimal(outside) if outside else None,
        "accessible_cash": Decimal(liq["accessible_cash_after_claims"]),
        "cash_months": Decimal(liq["months_of_outgo"]) if liq["months_of_outgo"] else None,
        "fresh_value_share": Decimal(exp["coverage"]["fresh_value_share"]) if exp["coverage"]["fresh_value_share"] else None,
    }


def metrics_out(m: dict) -> dict:
    return {k: (f(v) if isinstance(v, Decimal) else v) for k, v in m.items()}


# ------------------------------------------------------------------------------------------------
# baseline + flows
# ------------------------------------------------------------------------------------------------

def valued(positions: list[dict]) -> list[dict]:
    return [p for p in positions if p["value"] is not None]


def total_value(positions: list[dict]) -> Decimal:
    return sum((p["value"] for p in valued(positions)), _ZERO)


def unclaimed_cash(positions: list[dict], claims: dict) -> Decimal:
    return sum((max(p["value"] - claims.get(p["position_id"], _ZERO), _ZERO) for p in valued(positions)
                if asset_class_of(p["asset_type"]) == "cash"), _ZERO)


def apply_flows(baseline: list[dict], claims: dict, contribution: Decimal, withdrawal: Decimal) -> list[dict]:
    """Same flows for HOLD and every alternative. Contribution -> synthetic 'new money' cash position.
    Withdrawal comes out of new money first, then unclaimed cash (largest first); never from claims."""
    out = deepcopy(baseline)
    new_cash = {"position_id": "new-money", "account_label": "New money (unallocated)", "asset_type": "cash", "resolution": "not_applicable",
                "instrument_id": None, "isin": None, "label": "New money", "value": contribution, "quality": "fresh",
                "sector": None, "as_of": date.today().isoformat()}
    out.append(new_cash)
    remaining = withdrawal
    cash_positions = [new_cash] + sorted((p for p in out if p is not new_cash and valued([p]) and asset_class_of(p["asset_type"]) == "cash"),
                                         key=lambda p: -p["value"])
    for p in cash_positions:
        free = p["value"] if p is new_cash else max(p["value"] - claims.get(p["position_id"], _ZERO), _ZERO)
        take = min(free, remaining)
        p["value"] -= take
        remaining -= take
    if remaining > 0:
        raise ActionInvalid("external_withdrawal is more than the new money plus unclaimed cash available")
    return out


def _take_cash(positions: list[dict], claims: dict, amount: Decimal, funding: str) -> Decimal:
    """Reduce cash by `amount` from the funding source. Returns the shortfall (0 if fully funded)."""
    remaining = amount
    if funding == "new_money":
        pool = [p for p in positions if p["position_id"] == "new-money"]
    else:  # existing_cash: unclaimed cash that is NOT this period's new money
        pool = sorted((p for p in positions if p["position_id"] != "new-money" and valued([p]) and asset_class_of(p["asset_type"]) == "cash"),
                      key=lambda p: -p["value"])
    for p in pool:
        free = p["value"] if p["position_id"] == "new-money" else max(p["value"] - claims.get(p["position_id"], _ZERO), _ZERO)
        take = min(free, remaining)
        p["value"] -= take
        remaining -= take
    return remaining


# ------------------------------------------------------------------------------------------------
# actions
# ------------------------------------------------------------------------------------------------

@dataclass
class Outcome:
    positions: list[dict]
    friction: Decimal
    gates: list[dict]
    notes: list[str]
    goal_shortfall: Decimal | None = None
    cost_detail: dict | None = None
    review_required: bool = False
    risk_increasing: bool = False
    designation: Decimal = _ZERO


def _risk_gate(ctx: dict, risk_increasing: bool) -> dict:
    if not risk_increasing:
        return gate("risk_capacity", "pass", "not risk-increasing", "n/a", "risk-constraints", "this action does not add risk")
    rc = ctx["constraints"]
    if rc["risk_increasing_allowed"]:
        return gate("risk_capacity", "pass", "allowed", "allowed", "risk-constraints", "no tolerance or capacity rule blocks added risk")
    unknown = [x for x in rc["limiting_factors"] if x.endswith("_unknown")]
    return gate("risk_capacity", "unknown" if unknown and len(unknown) == len(rc["limiting_factors"]) else "fail",
                ", ".join(rc["limiting_factors"]), "none binding", "risk-constraints",
                "adding risk is blocked: " + ", ".join(rc["limiting_factors"]))


def _restrictions_gate(ctx: dict, *, asset_type: str, sector: str | None, isin: str | None) -> dict:
    hit = [r for r in ctx["restrictions"] if (r["kind"] == "exclude_asset_type" and r["value"].lower() == asset_type)
           or (r["kind"] == "exclude_sector" and sector and r["value"].lower() == sector.lower())
           or (r["kind"] == "exclude_isin" and isin and r["value"].upper() == isin.upper())]
    return gate("user_restrictions", "fail" if hit else "pass", [f"{r['kind']}={r['value']}" for r in hit] or "none", "none",
                "preferences", "you excluded this" if hit else "no confirmed restriction applies")


def _concentration_gates(before: dict, after: dict) -> list[dict]:
    out = []
    for gid, key, limit, label in (("max_issuer_weight", "largest_issuer_weight", POLICY["max_single_issuer_weight"], "single-company weight"),
                                   ("max_sector_weight", "largest_sector_weight", POLICY["max_sector_weight"], "single-sector weight")):
        a, b = after.get(key), before.get(key)
        if a is None:
            out.append(gate(gid, "pass", None, f(limit), "risk", f"no {label} to measure"))
        elif a <= limit or (b is not None and a <= b + POLICY["concentration_slack"]):  # over the limit is only tolerated if the action did not materially worsen it
            out.append(gate(gid, "pass", f(a), f(limit), "risk", f"{label} {a:.1%} (limit {limit:.0%}; not worsened)" if a > limit else f"{label} within the limit"))
        else:
            out.append(gate(gid, "fail", f(a), f(limit), "risk", f"{label} would rise to {a:.1%}, above the {limit:.0%} limit"))
    return out


def _freshness_gate(m: dict) -> dict:
    s = m.get("fresh_value_share")
    lim = POLICY["min_fresh_value_share"]
    if s is None:
        return gate("data_freshness", "unknown", None, f(lim), "valuation", "no fresh-value share available")
    return gate("data_freshness", "pass" if s >= lim else "unknown", f(s), f(lim), "valuation",
                "values are fresh enough" if s >= lim else "too much of the portfolio is valued from stale data")


def evaluate_buy(a: dict, ctx: dict, flows_positions: list[dict], fee_pct: Decimal) -> Outcome:
    positions = deepcopy(flows_positions)
    inst = ctx["instruments"].get(a["instrument_id"])
    if inst is None:
        raise ActionInvalid("buy needs an instrument from the master (unknown instrument_id)")
    amount = a["amount"]
    gates: list[dict] = []
    funding = a["funding"]
    claims = ctx["claims"]
    avail = (next((p["value"] for p in positions if p["position_id"] == "new-money"), _ZERO) if funding == "new_money"
             else unclaimed_cash([p for p in positions if p["position_id"] != "new-money"], claims))
    gates.append(gate("funding_available", "pass" if amount <= avail else "fail", f(amount), f(avail), "baseline + flows",
                      f"{funding.replace('_', ' ')} available: {f(avail)}" if amount <= avail else f"only {f(avail)} of {funding.replace('_', ' ')} is available for this purchase"))
    gates.append(gate("min_action_size", "pass" if amount >= POLICY["min_action_amount"] else "fail", f(amount), f(POLICY["min_action_amount"]),
                      "policy", "large enough to matter" if amount >= POLICY["min_action_amount"] else "below the minimum action size (avoids churn)"))
    if any(g["result"] == "fail" for g in gates):
        return Outcome(positions, _ZERO, gates, ["a pre-trade check failed: nothing was priced or applied"], risk_increasing=True)
    price = ctx["prices"].get(a["instrument_id"])
    if price is None:
        gates.append(gate("price_available", "fail", None, "a recent adjusted close", "candles", "no price on file for this instrument"))
        return Outcome(positions, _ZERO, gates, ["no price: nothing priced or applied"], risk_increasing=True)
    age = (ctx["today"] - price["as_of"]).days
    gates.append(gate("price_available", "pass" if age <= POLICY["price_stale_days"] else "unknown", f"{price['price']} as of {price['as_of']}",
                      f"<= {POLICY['price_stale_days']} days old", "candles",
                      "recent price" if age <= POLICY["price_stale_days"] else f"price is {age} days old"))
    px = price["price"]
    if inst.get("fractional"):
        # Mutual fund: bought by amount, in thousandths of a unit (rounded DOWN so the cost never exceeds the budget).
        lot = Decimal("0.001")
        units = ((amount / (px * (1 + fee_pct))) / lot).to_integral_value(rounding=ROUND_FLOOR) * lot
        gates.append(gate("lot_size", "pass" if units >= lot else "fail", f(units), f">= {f(lot)} unit", "instrument master",
                          f"{f(units)} unit(s) at {f(px)} (amount-based purchase)" if units >= lot else "the amount does not buy any units at this price"))
    else:
        lot = max(int(inst.get("lot_size") or 1), 1)
        units = int(((amount / (px * (1 + fee_pct))) / lot).to_integral_value(rounding=ROUND_FLOOR)) * lot
        gates.append(gate("lot_size", "pass" if units >= lot else "fail", units, f">= {lot}", "instrument master",
                          f"{units} unit(s) at {f(px)}" if units >= lot else "the amount does not buy one lot at this price"))
    trade = q(Decimal(units) * px)
    friction = q(trade * fee_pct)
    if units < lot:
        return Outcome(positions, _ZERO, gates, ["no whole lot purchasable: nothing applied"], risk_increasing=True)
    short = _take_cash(positions, claims, trade + friction, funding)
    if short > 0:
        gates[0] = gate("funding_available", "fail", f(trade + friction), f(avail), "baseline + flows", "trade plus friction exceeds the available cash")
        return Outcome(positions, _ZERO, gates, ["not fully funded: nothing applied"], risk_increasing=True)
    sector = inst.get("sector")
    target_acct = a["account_label"]
    existing = next((p for p in positions if p["account_label"] == target_acct and p["instrument_id"] == a["instrument_id"] and valued([p])), None)
    if existing is not None:
        existing["value"] += trade
    else:
        positions.append({"position_id": f"proposed-{a['instrument_id']}", "account_label": target_acct, "asset_type": inst.get("asset_type", "listed_equity"),
                          "resolution": "resolved", "instrument_id": a["instrument_id"], "isin": inst.get("isin"), "label": f"{inst['symbol']} (proposed)",
                          "value": trade, "quality": "fresh", "sector": sector, "as_of": price["as_of"].isoformat()})
    asset_type = inst.get("asset_type", "listed_equity")
    gates.append(_restrictions_gate(ctx, asset_type=asset_type, sector=sector, isin=inst.get("isin")))
    cost_pct = (friction / trade) if trade else _ZERO
    gates.append(gate("cost_reasonable", "pass" if cost_pct <= POLICY["max_cost_pct_of_trade"] else "fail", f(cost_pct), f(POLICY["max_cost_pct_of_trade"]),
                      "friction assumption", f"friction {f(friction)} is {cost_pct:.2%} of the trade (assumed rate, not a quote)"))
    notes = [f"{f(units) if inst.get('fractional') else units} unit(s) at {f(px)} (as of {price['as_of']}) = {f(trade)}; assumed friction {f(friction)} at {fee_pct:.2%}; "
             f"{f(q(amount - trade - friction))} left over stays as cash (lot/rounding residual)"]
    # A liquid/overnight ETF is cash-like debt: it must not be treated as "added risk" just because the engine cannot look inside ETFs.
    return Outcome(positions, friction, gates, notes, risk_increasing=asset_class_of(asset_type) in RISK_INCREASING_CLASSES and not inst.get("cash_like"),
                   cost_detail={"trade_value": f(trade), "friction": f(friction), "friction_basis": f"{fee_pct:.2%} assumed (statutory charges + slippage), not a broker quote",
                                "tax": "none on a purchase", "residual_cash": f(q(amount - trade - friction)), "units": (f(units) if inst.get("fractional") else units), "price": f(px)})


def evaluate_reduce(a: dict, ctx: dict, flows_positions: list[dict], fee_pct: Decimal) -> Outcome:
    positions = deepcopy(flows_positions)
    target = next((p for p in positions if p["position_id"] == a["position_id"]), None)
    if target is None or target["value"] is None:
        raise ActionInvalid("reduce needs a valued position from the current snapshot (unknown position_id)")
    amount = a["amount"]
    gates = [gate("sale_within_holding", "pass" if amount <= target["value"] else "fail", f(amount), f(target["value"]), "baseline",
                  "within the holding's value" if amount <= target["value"] else "more than the holding is worth")]
    claimed = ctx["claims"].get(a["position_id"], _ZERO)
    gates.append(gate("not_claimed_for_goals", "pass" if target["value"] - amount >= claimed else "fail", f(target["value"] - amount), f">= {f(claimed)} claimed",
                      "goal claims", "leaves enough to cover goal claims" if target["value"] - amount >= claimed else "would dip into money claimed for goals"))
    gates.append(gate("tax_lots_known", "unknown", "no lots / acquisition dates", "known lots", "holdings import",
                      "tax on a sale cannot be estimated without purchase lots; this is a preview only and no after-tax benefit is claimed"))
    if amount > target["value"]:
        return Outcome(positions, _ZERO, gates, ["sale larger than the holding: nothing applied"], review_required=True)
    friction = q(amount * fee_pct)
    target["value"] -= amount
    proceeds = amount - friction
    positions.append({"position_id": f"sale-proceeds-{a['position_id']}", "account_label": target["account_label"], "asset_type": "cash",
                      "resolution": "not_applicable", "instrument_id": None, "isin": None, "label": "Sale proceeds (pre-tax)", "value": proceeds,
                      "quality": "fresh", "sector": None, "as_of": date.today().isoformat()})
    return Outcome(positions, friction, gates, [f"pre-tax proceeds {f(proceeds)} after assumed friction {f(friction)}; tax unknown"],
                   review_required=True, cost_detail={"sale_value": f(amount), "friction": f(friction), "tax": "unknown (no tax lots)",
                                                      "friction_basis": f"{fee_pct:.2%} assumed"})


def evaluate_reserve(a: dict, ctx: dict, flows_positions: list[dict]) -> Outcome:
    positions = deepcopy(flows_positions)
    avail = unclaimed_cash(positions, ctx["claims"])
    gates = [gate("cash_available", "pass" if a["amount"] <= avail else "fail", f(a["amount"]), f(avail), "baseline + flows",
                  "cash exists to designate" if a["amount"] <= avail else "more than the unclaimed cash")]
    return Outcome(positions, _ZERO, gates, ["a designation only: no asset changes and nothing is bought or sold"], designation=a["amount"])


def evaluate_contribution(a: dict, ctx: dict) -> Outcome:
    chain = a["commitment_chain_id"]
    c = ctx["commitments"].get(chain)
    if c is None:
        raise ActionInvalid("unknown commitment (it must be an active, user-reported contribution)")
    delta = a["new_monthly_amount"] - c["monthly"]
    gates = []
    rem = ctx["budget"].get("remaining_for_new_monthly")
    if delta > 0:
        if rem is None:
            gates.append(gate("budget_available", "unknown", f(delta), None, "budget", "your monthly investable amount is unknown"))
        else:
            ok = delta <= Decimal(rem)
            gates.append(gate("budget_available", "pass" if ok else "fail", f(delta), rem, "budget", "fits in your monthly budget" if ok else "more than your remaining monthly budget"))
    else:
        gates.append(gate("budget_available", "pass", f(delta), "n/a", "budget", "a reduction frees money"))
    goal = ctx["goals"].get(c["goal_chain_id"]) if c.get("goal_chain_id") else None
    shortfall = None
    notes = []
    if goal is None:
        notes.append("this contribution is not linked to a goal, so no goal effect can be shown")
    else:
        monthly = goal["monthly"] - c["monthly"] + a["new_monthly_amount"]
        p = project_goal(target_amount=goal["target_amount"], target_basis=goal["target_basis"], target_date=goal["target_date"],
                         inflation=goal["inflation"], starting_value=goal["starting"], monthly_contribution=monthly, today=ctx["today"])
        if p["status"] == "ready":
            shortfall = Decimal(p["scenarios"]["base"]["gap_to_target"] or "0")
            notes.append(f"base-scenario shortfall for '{goal['description']}' becomes {f(shortfall)}")
    return Outcome(deepcopy(ctx["_flows_positions"]), _ZERO, gates, notes, goal_shortfall=shortfall,
                   cost_detail={"friction": "0", "note": "no purchase; changes the plan's monthly contribution only"})


# ------------------------------------------------------------------------------------------------
# comparison
# ------------------------------------------------------------------------------------------------

def compare(hold: dict, cand: dict, *, priorities: list[str]) -> dict:
    rows, improved, worsened, improved_priority = [], [], [], []
    for key, (direction, thr) in POLICY["materiality"].items():
        b, a = hold.get(key), cand.get(key)
        if b is None or a is None:
            rows.append({"metric": key, "before": f(b), "after": f(a), "delta": None, "verdict": "not_comparable",
                         "materiality_threshold": f(thr)})
            continue
        delta = a - b
        if direction == "lower":
            better, worse = delta <= -thr, delta >= thr
        elif direction == "higher":
            better, worse = delta >= thr, delta <= -thr
        else:  # loss pct is negative; a smaller magnitude is better
            better, worse = (abs(a) - abs(b)) <= -thr, (abs(a) - abs(b)) >= thr
        verdict = "improved" if better else "worsened" if worse else "within_threshold"
        rows.append({"metric": key, "before": f(b), "after": f(a), "delta": f(delta), "verdict": verdict, "materiality_threshold": f(thr)})
        if better:
            improved.append(key)
            if key in priorities:
                improved_priority.append(key)
        if worse:
            worsened.append(key)
    return {"rows": rows, "improved": improved, "worsened": worsened, "improved_priority": improved_priority}


def classify(outcome: Outcome, cmp: dict | None) -> tuple[str, list[str]]:
    fails = [g for g in outcome.gates if g["result"] == "fail"]
    unknown = [g for g in outcome.gates if g["result"] == "unknown"]
    if fails:
        return "rejected", [g["reason"] for g in fails]
    if outcome.review_required:
        return "review_required", [g["reason"] for g in unknown] or ["needs review before it could be considered"]
    if unknown:
        return "needs_input", [g["reason"] for g in unknown]
    if cmp is None:
        return "no_material_benefit", ["no comparable metric changed"]
    if cmp["improved_priority"] and not cmp["worsened"]:
        return "dominates_hold", [f"improves {', '.join(cmp['improved_priority'])} without worsening any compared metric"]
    if cmp["improved"] and cmp["worsened"]:
        return "tradeoff", [f"improves {', '.join(cmp['improved'])} but worsens {', '.join(cmp['worsened'])}"]
    if cmp["worsened"]:
        return "worse_than_hold", [f"worsens {', '.join(cmp['worsened'])} without a compensating improvement"]
    return "no_material_benefit", ["every compared metric is within its materiality threshold, so HOLD stays the default"]


RANK = {"dominates_hold": 0, "tradeoff": 1, "no_material_benefit": 2, "worse_than_hold": 3, "review_required": 4, "needs_input": 5, "rejected": 6}


def invariant(before_total: Decimal, contribution: Decimal, withdrawal: Decimal, after_total: Decimal, friction: Decimal) -> Decimal:
    """Residual of: after + friction = before + contribution - withdrawal (must be exactly 0)."""
    return q(after_total + friction) - q(before_total + contribution - withdrawal)


def evaluate(ctx: dict) -> dict:
    """ctx: baseline, claims, capacity, constraints, restrictions, instruments, prices, commitments, goals, budget,
    contribution, withdrawal, actions, priorities, fee_pct, today."""
    contribution, withdrawal = ctx["contribution"], ctx["withdrawal"]
    if contribution < 0 or withdrawal < 0:
        raise ActionInvalid("contribution and withdrawal must be zero or positive")
    fee_pct = ctx["fee_pct"]
    if fee_pct < 0 or fee_pct > POLICY["max_fee_pct"]:
        raise ActionInvalid(f"fee_pct must be between 0 and {POLICY['max_fee_pct']}")
    baseline = ctx["baseline"]
    before_total = total_value(baseline)
    flows_positions = apply_flows(baseline, ctx["claims"], contribution, withdrawal)
    ctx["_flows_positions"] = flows_positions
    hold_positions = flows_positions
    hold_metrics = metrics_for(hold_positions, ctx["capacity"], ctx["claims"])
    base_goal_shortfall = None
    hold_residual = invariant(before_total, contribution, withdrawal, total_value(hold_positions), _ZERO)
    priorities = ctx["priorities"] or [k for k in POLICY["materiality"]]

    # goal metric baseline: sum of base-scenario shortfalls over ready goals
    def goal_total(monthly_override: dict | None = None) -> Decimal | None:
        tot, any_ready = _ZERO, False
        for g in ctx["goals"].values():
            monthly = g["monthly"] if not monthly_override else monthly_override.get(g["chain_id"], g["monthly"])
            p = project_goal(target_amount=g["target_amount"], target_basis=g["target_basis"], target_date=g["target_date"], inflation=g["inflation"],
                             starting_value=g["starting"], monthly_contribution=monthly, today=ctx["today"])
            if p["status"] == "ready":
                tot += Decimal(p["scenarios"]["base"]["gap_to_target"] or "0")
                any_ready = True
        return tot if any_ready else None

    base_goal_shortfall = goal_total()
    hold_metrics["goal_shortfall_base"] = base_goal_shortfall

    alternatives = []
    for idx, a in enumerate(ctx["actions"]):
        kind = a["type"]
        if kind == "BUY":
            out = evaluate_buy(a, ctx, flows_positions, fee_pct)
        elif kind == "REDUCE_PREVIEW":
            out = evaluate_reduce(a, ctx, flows_positions, fee_pct)
        elif kind == "RESERVE":
            out = evaluate_reserve(a, ctx, flows_positions)
        elif kind == "ADJUST_CONTRIBUTION":
            out = evaluate_contribution(a, ctx)
        else:
            raise ActionInvalid(f"unknown action type {kind!r}")
        residual = invariant(before_total, contribution, withdrawal, total_value(out.positions), out.friction)
        cand_metrics = metrics_for(out.positions, ctx["capacity"], ctx["claims"])
        if kind == "ADJUST_CONTRIBUTION":
            c = ctx["commitments"][a["commitment_chain_id"]]
            cand_metrics["goal_shortfall_base"] = goal_total({c["goal_chain_id"]: ctx["goals"][c["goal_chain_id"]]["monthly"] - c["monthly"] + a["new_monthly_amount"]}) \
                if c.get("goal_chain_id") in ctx["goals"] else base_goal_shortfall
        else:
            cand_metrics["goal_shortfall_base"] = base_goal_shortfall
        if kind in ("BUY", "REDUCE_PREVIEW"):
            out.gates += _concentration_gates(hold_metrics, cand_metrics)
            out.gates.append(_freshness_gate(cand_metrics))
            out.gates.append(_risk_gate(ctx, out.risk_increasing))
        if kind == "RESERVE":
            out.gates.append(_freshness_gate(cand_metrics))
        cmp = compare(hold_metrics, cand_metrics, priorities=priorities)
        status, reasons = classify(out, cmp)
        alternatives.append({
            "index": idx, "action": {k: (f(v) if isinstance(v, Decimal) else v) for k, v in a.items()}, "status": status, "reasons": reasons,
            "gates": out.gates, "notes": out.notes, "cost": out.cost_detail, "metrics_after": metrics_out(cand_metrics),
            "comparison_vs_hold": cmp, "candidate_state_hash": candidate_hash(out.positions),
            "accounting": {"assets_before": f(before_total), "external_contribution": f(contribution), "external_withdrawal": f(withdrawal),
                           "assets_after": f(total_value(out.positions)), "friction": f(out.friction), "residual": f(residual),
                           "conserved": residual == 0},
            "designated_reserve": f(out.designation) if out.designation else None,
        })
    ranked = sorted(alternatives, key=lambda x: (RANK[x["status"]], x["index"]))
    best = next((x for x in ranked if x["status"] == "dominates_hold"), None)
    runner = next((x for x in ranked if x is not best and x["status"] != "dominates_hold"), None)
    return {
        "engine_version": ENGINE_VERSION,
        "policy": {k: (f(v) if isinstance(v, Decimal) else v) for k, v in POLICY.items() if k != "materiality"} | {
            "materiality": {k: {"direction": d, "threshold": f(t)} for k, (d, t) in POLICY["materiality"].items()}},
        "default": "HOLD",
        "published": False,
        "note": "A simulation, not advice and not a published action. HOLD is the default unless an alternative clearly dominates it.",
        "flows": {"external_contribution": f(contribution), "external_withdrawal": f(withdrawal), "fee_pct": f(fee_pct)},
        "hold": {"metrics": metrics_out(hold_metrics), "candidate_state_hash": candidate_hash(hold_positions),
                 "accounting": {"assets_before": f(before_total), "assets_after": f(total_value(hold_positions)), "residual": f(hold_residual),
                                "conserved": hold_residual == 0, "note": "new money stays as cash"}},
        "alternatives": alternatives,
        "summary": {"best_alternative_index": None if best is None else best["index"],
                    "runner_up_index": None if runner is None else runner["index"],
                    "headline": ("An alternative dominates HOLD on the compared metrics; review it." if best else
                                 "Nothing clearly beats HOLD. Doing nothing is the default." if alternatives else "No alternatives were evaluated; HOLD is the baseline."),
                    "why_runner_up_lost": None if runner is None else runner["reasons"]},
    }



def evaluate_plan(ctx: dict) -> dict:
    """Evaluate SEVERAL buys as ONE plan: apply the legs one after another on cumulative positions (each through
    evaluate_buy, so every per-leg gate still runs), then run concentration, freshness and risk-capacity gates ONCE on the
    final state and check the conservation invariant once for the whole plan.

    The plan's status rests on the HARD GATES (`gates_pass` | `blocked` | `needs_input`). The comparison with HOLD is
    reported beside it, not folded into the status: HOLD keeps new money as idle cash, so any investing plan "worsens"
    cash_months, and ETFs/funds have no look-through here, so their value is counted as `unknown_weight`. Those are limits
    of this engine's metrics, not findings about the plan, and they must be shown as a trade-off, never as a verdict."""
    contribution = ctx["contribution"]
    fee_pct = ctx["fee_pct"]
    if contribution < 0 or fee_pct < 0 or fee_pct > POLICY["max_fee_pct"]:
        raise ActionInvalid("contribution must be >= 0 and fee_pct within policy")
    baseline = ctx["baseline"]
    before_total = total_value(baseline)
    flows_positions = apply_flows(baseline, ctx["claims"], contribution, _ZERO)
    hold_metrics = metrics_for(flows_positions, ctx["capacity"], ctx["claims"])
    positions, friction_total, risk_increasing = flows_positions, _ZERO, False
    legs = []
    for idx, a in enumerate(ctx["actions"]):
        if a["type"] != "BUY":
            raise ActionInvalid("a plan consists of BUY legs only")
        out = evaluate_buy(a, ctx, positions, fee_pct)
        legs.append({"index": idx, "action": {k: (f(v) if isinstance(v, Decimal) else v) for k, v in a.items()}, "gates": out.gates, "notes": out.notes, "cost": out.cost_detail,
                     "failed": any(g["result"] == "fail" for g in out.gates)})
        if not legs[-1]["failed"]:
            positions = out.positions
            friction_total += out.friction
            risk_increasing = risk_increasing or out.risk_increasing
    cand_metrics = metrics_for(positions, ctx["capacity"], ctx["claims"])
    final_gates = _concentration_gates(hold_metrics, cand_metrics) + [_freshness_gate(cand_metrics), _risk_gate(ctx, risk_increasing)]
    residual = invariant(before_total, contribution, _ZERO, total_value(positions), friction_total)
    leg_fails = [g for leg in legs for g in leg["gates"] if g["result"] == "fail"]
    all_unknown = [g for leg in legs for g in leg["gates"] if g["result"] == "unknown"] + [g for g in final_gates if g["result"] == "unknown"]
    final_fails = [g for g in final_gates if g["result"] == "fail"]
    if leg_fails or final_fails:
        status, reasons = "blocked", [g["reason"] for g in leg_fails + final_fails]
    elif all_unknown:
        status, reasons = "needs_input", [g["reason"] for g in all_unknown]
    else:
        status, reasons = "gates_pass", ["every hard gate passes on every leg and on the final portfolio"]
    cmp = compare(hold_metrics, cand_metrics, priorities=[])
    return {
        "engine_version": ENGINE_VERSION, "policy_version": POLICY_VERSION, "status": status, "reasons": reasons, "legs": legs, "final_gates": final_gates,
        "hold_metrics": metrics_out(hold_metrics), "metrics_after": metrics_out(cand_metrics), "comparison_vs_hold": cmp,
        "comparison_caveat": ("HOLD keeps the new money as idle cash, so investing it lowers 'cash_months'; and the engine cannot look inside ETFs or funds, "
                              "so their value is counted as 'unknown_weight' and stress scenarios do not see them. These are limits of the metrics, not findings about the plan."),
        "candidate_state_hash": candidate_hash(positions),
        "accounting": {"assets_before": f(before_total), "external_contribution": f(contribution), "assets_after": f(total_value(positions)), "friction": f(friction_total),
                       "residual": f(residual), "conserved": residual == 0},
    }
