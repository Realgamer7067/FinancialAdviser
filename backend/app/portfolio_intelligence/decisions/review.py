"""Portfolio review: decide what the owner should see as the CURRENT outcome
(plan sections 5.3, 6, 12.9). Deterministic. Never a Nifty scan, never a
forecast, never "healthy": the valid outcomes are

  NEEDS_INPUT  something required to assess is missing/stale
  REVIEW       a measured issue deserves attention (with previews where possible)
  HOLD         nothing material found in the ASSESSED holdings

"No action required today" is only allowed when every readiness dimension is
complete; otherwise HOLD says "No issue found in the assessed holdings" and
names what remains unassessed."""

from decimal import ROUND_CEILING, Decimal

REVIEW_VERSION = "review-v2"
REVIEW_BY_DAYS = 7

SEVERITY_ORDER = {"urgent": 0, "review": 1, "information": 2}
NEEDS_INPUT_KINDS = {"holdings_unusable", "portfolio_empty", "valuation_unusable", "profile_incomplete", "stale_values", "sync_problem", "reconnect_required"}


def issue(kind, severity, title, detail, *, subject=None, measure=None, **extra):
    """`fingerprint` identifies the issue across reviews (kind + subject); `measure` is the number whose
    growth would make a dismissed issue material again (a weight, a count)."""
    fp = kind if subject is None else f"{kind}:{subject}"
    return {"kind": kind, "severity": severity, "title": title, "detail": detail, "fingerprint": fp,
            "measure": None if measure is None else str(measure), **extra}


def detect_issues(*, readiness: dict, risk: dict | None, constraints: dict, projections: list[dict], limits: dict,
                  claims_needing_review: int, reconnect_accounts: list[str] | None = None,
                  thesis_updates: list[dict] | None = None) -> list[dict]:
    out: list[dict] = []
    for label in reconnect_accounts or []:
        out.append(issue("reconnect_required", "urgent", f"Reconnect {label} to refresh it",
                         "The broker session ended; your last imported holdings are kept and dated, but they are not being refreshed.",
                         subject=label))
    h, v, ident, suit, cov = (readiness[k] for k in ("holdings_status", "valuation_status", "identity_status", "suitability_status", "account_coverage_status"))
    if h["status"] == "unusable":
        out.append(issue("holdings_unusable", "review", "No holdings to assess yet", "; ".join(h["missing"])))
    elif h["missing"]:
        problems = [m for m in h["missing"] if "sync" in m]
        if problems:
            out.append(issue("sync_problem", "review", "A recent sync had a problem", "; ".join(problems)))
    if v["status"] == "unusable" and h["status"] != "unusable" and v["missing"] == ["no positions"]:
        # The accounts are connected and imported, and they simply hold nothing yet. That is a starting point, not a data problem.
        out.append(issue("portfolio_empty", "review", "Nothing is held in these accounts yet",
                         "Your accounts are connected and empty, so there is nothing to review. To start, Plan new investment shows how you could spread money you want to invest; you can also add accounts held elsewhere."))
    elif v["status"] == "unusable" and h["status"] != "unusable":
        out.append(issue("valuation_unusable", "review", "No holding has a known value", "; ".join(v["missing"])))
    profile_gaps = [m for m in suit["missing"] if not m.startswith("goals") and "goal claim" not in m]
    if profile_gaps:
        out.append(issue("profile_incomplete", "review", "Your financial picture is incomplete", "missing: " + ", ".join(profile_gaps)))
    if any(m == "goals" for m in suit["missing"]):
        out.append(issue("goals_missing", "information", "No goal set yet", "Goals let us check whether you are on track."))
    if cov["status"] != "complete":
        out.append(issue("coverage_unconfirmed", "information", "Not all accounts confirmed", "; ".join(cov["missing"])))
    if ident["status"] != "complete":
        out.append(issue("unmatched_holdings", "information", "Some holdings could not be matched", "; ".join(ident["missing"])))
    if claims_needing_review:
        out.append(issue("claims_need_review", "review", "Money set aside for goals needs your review",
                         f"{claims_needing_review} claim(s) were flagged because a holding changed or disappeared.", measure=claims_needing_review))

    if risk is not None:
        fresh = risk["coverage"]["fresh_value_share"]
        if fresh is not None and Decimal(fresh) < limits["min_fresh_value_share"]:
            out.append(issue("stale_values", "review", "Much of your portfolio is valued from old data",
                             f"only {Decimal(fresh):.0%} of value is fresh; refresh your holdings"))
        ic = risk["issuer_concentration"]
        if ic["status"] == "ready" and ic.get("largest_issuer_weight") is not None and Decimal(ic["largest_issuer_weight"]) > limits["max_single_issuer_weight"]:
            out.append(issue("issuer_concentration", "review", f"{ic['largest_issuer']} is a large share of your portfolio",
                             f"{Decimal(ic['largest_issuer_weight']):.1%} of known value in one company (limit {limits['max_single_issuer_weight']:.0%})",
                             issuer=ic["largest_issuer"], weight=ic["largest_issuer_weight"], limit=str(limits["max_single_issuer_weight"]),
                             subject=ic["largest_issuer"], measure=ic["largest_issuer_weight"]))
        sector_buckets = [b for b in risk["sector"]["buckets"] if b["bucket"] not in ("non_equity", "unclassified_equity", "fund_lookthrough_unknown")]
        if sector_buckets:
            top = max(sector_buckets, key=lambda b: Decimal(b["weight"] or 0))
            if Decimal(top["weight"] or 0) > limits["max_sector_weight"]:
                out.append(issue("sector_concentration", "review", f"{top['bucket']} is a large share of your portfolio",
                                 f"{Decimal(top['weight']):.1%} of known value in one sector (limit {limits['max_sector_weight']:.0%})",
                                 sector=top["bucket"], weight=top["weight"], subject=top["bucket"], measure=top["weight"]))
    for b in constraints["ceilings"]:
        if b["source"] == "capacity" and b.get("binding"):
            for rule in b["binding"]:
                if rule["rule"] == "reserve_shortfall":
                    out.append(issue("reserve_shortfall", "review", "Your emergency reserve is below your own target", rule["detail"]))
    for p in projections:
        if p.get("assessment") == "target_needs_revision":
            out.append(issue("goal_needs_revision", "review", f"Goal '{p['description']}' needs revising", p.get("assessment_message", ""),
                             goal=p["goal_chain_id"], subject=p["goal_chain_id"]))
    for t in thesis_updates or []:
        # Information only, by design: a thesis can never turn a review into REVIEW or override any gate.
        out.append(issue("thesis_update", "information", f"Thesis update: {t['symbol']} looks {t['status']}",
                         "New evidence was assessed against your own conditions. Your portfolio action is unchanged by it.",
                         subject=t["chain"]))
    out.sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], i["kind"]))
    return out


def reduction_amount(group_value: Decimal, total: Decimal, limit: Decimal, position_value: Decimal) -> Decimal | None:
    """Sale amount (rounded up to a whole ₹100) that would bring a holding group back to the limit,
    capped at what the chosen position holds. None if nothing needs selling."""
    need = group_value - limit * total
    if need <= 0:
        return None
    amount = (need / 100).to_integral_value(rounding=ROUND_CEILING) * 100
    return min(amount, position_value)


def compose(issues: list[dict], readiness: dict, *, alternatives: list[dict]) -> tuple[str, str, dict]:
    needs = [i for i in issues if i["kind"] in NEEDS_INPUT_KINDS]
    reviews = [i for i in issues if i["severity"] in ("review", "urgent") and i["kind"] not in NEEDS_INPUT_KINDS]
    infos = [i for i in issues if i["severity"] == "information"]
    all_complete = all(d["status"] == "complete" for d in readiness.values())
    if needs:
        status = "NEEDS_INPUT"
        headline = "We need more information before we can review: " + needs[0]["title"].lower()
    elif reviews:
        status = "REVIEW"
        headline = reviews[0]["title"] + (f" (and {len(reviews) - 1} more)" if len(reviews) > 1 else "")
    else:
        status = "HOLD"
        headline = "No action required today" if all_complete and not infos else "No issue found in the assessed holdings"
    unassessed = sorted({m for d in readiness.values() if d["status"] != "complete" for m in d["missing"]})
    explanation = {
        "current_issues": [i["title"] for i in needs + reviews],
        "not_assessed_or_incomplete": unassessed,
        "compared": "Any previewed change was compared with doing nothing on the same snapshot"
                    if alternatives else "No alternative was generated; doing nothing is the baseline",
        "why_hold" if status == "HOLD" else "why_not_hold": (
            "No measured issue crossed a limit in the holdings we could assess." if status == "HOLD" else
            "An issue above needs attention or information before a decision can be made."),
        "next_best_alternative": (alternatives[0]["reasons"][0] if alternatives and alternatives[0].get("reasons") else None),
        "triggers_to_revisit": ["holdings, profile, goals or commitments change", "a newer valuation shows a material move",
                                f"{REVIEW_BY_DAYS} days pass", "the decision policy version changes"],
    }
    return status, headline, explanation
