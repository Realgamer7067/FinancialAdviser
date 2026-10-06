"""Multidimensional readiness (plan section 12.2). Each dimension is
complete / partial / unusable with named missing items; a complete Angel import
never implies all accounts are represented, and unknown values are never 0."""


def _dim(status: str, missing: list[str]) -> dict:
    return {"status": status, "missing": missing}


def compute_readiness(*, account_inputs: list[dict], attestation_status: str, attestation_missing: list[str],
                      position_resolutions: list[str], unknown_value_count: int, valued_count: int,
                      stale_or_error_accounts: list[str], profile_missing: list[str] | None = None,
                      goal_count: int = 0, allocations_needing_review: int = 0) -> dict:
    # account coverage: only the user's declaration can make this complete
    if attestation_status == "complete":
        coverage = _dim("complete", [])
    elif attestation_status == "partial":
        coverage = _dim("partial", [f"missing account: {m}" for m in attestation_missing] or ["some accounts not added"])
    else:
        coverage = _dim("partial", ["account completeness not confirmed"])

    imported = [a for a in account_inputs if a["status"] == "imported"]
    if not imported:
        holdings = _dim("unusable", ["no included account has an imported holdings snapshot"])
    else:
        gaps = [f"{a['label']}: no import" for a in account_inputs if a["status"] != "imported"]
        gaps += [f"{name}: last sync had a problem" for name in stale_or_error_accounts]
        holdings = _dim("partial" if gaps else "complete", gaps)

    if valued_count == 0:
        valuation = _dim("unusable", ["no position has a value"] if position_resolutions or unknown_value_count else ["no positions"])
    elif unknown_value_count:
        valuation = _dim("partial", [f"{unknown_value_count} position(s) have no value"])
    else:
        valuation = _dim("complete", [])

    unresolved = sum(1 for r in position_resolutions if r in ("unresolved", "ambiguous"))
    identity = _dim("partial", [f"{unresolved} holding(s) not matched to a known instrument"]) if unresolved else _dim("complete", [])

    # Suitability needs the user's profile AND at least one goal, and no claim awaiting review.
    if profile_missing is None:
        suitability = _dim("unusable", ["financial profile", *([] if goal_count else ["goals"]),
                                        *([f"{allocations_needing_review} goal claim(s) need review"] if allocations_needing_review else [])])
    else:
        gaps = list(profile_missing)
        if not goal_count:
            gaps.append("goals")
        if allocations_needing_review:
            gaps.append(f"{allocations_needing_review} goal claim(s) need review")
        suitability = _dim("partial" if gaps else "complete", gaps)

    return {"account_coverage_status": coverage, "holdings_status": holdings, "valuation_status": valuation,
            "identity_status": identity, "suitability_status": suitability}
