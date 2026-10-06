"""Call-count budget calculator (Phase 04 benchmark harness, V3 Section 11.2).

Pure, deterministic, no I/O and no randomness -- this module makes the V3
call-count claims concrete and testable. It does NOT run any pipeline live;
it is arithmetic over known/assumed call shapes.

Legacy shape mirrors backend/app/council/orchestrator.py as it exists today:
one planner call per run (not per candidate), plus per candidate 5 analyst
roles (bull/bear/fundamental/quant/risk, run concurrently) + 1 judge = 6
calls per candidate. See run_planner() and run_candidate_council()'s
role_specs list in that file.

Target shape mirrors V3 Section 11.2: "up to three extraction batches, one
synthesis and one verification: five calls when all extraction batches miss
cache... A bounded repair/follow-up allowance can add two calls... Cached
extraction can reduce this to synthesis plus verification."
"""

from dataclasses import dataclass

# Verified against backend/app/council/orchestrator.py's role_specs list
# (bull, bear, fundamental, quant, risk) + the sequential judge call.
_LEGACY_ANALYST_ROLES = 5
_LEGACY_CALLS_PER_CANDIDATE = _LEGACY_ANALYST_ROLES + 1  # + judge = 6


@dataclass(frozen=True)
class CallBudgetEstimate:
    strategy: str  # e.g. "legacy_council", "extraction_synthesis_verification"
    calls_per_unit: int  # "unit" = one candidate for council, one company for the new research shape
    units: int
    total_calls: int
    cache_hit_fraction: float  # 0..1, fraction of extraction/lookup calls assumed served from cache
    effective_calls: int  # total_calls adjusted down for the cached fraction, per the strategy's own caching model


def estimate_legacy_council(num_candidates: int) -> CallBudgetEstimate:
    """1 planner (once per run, not per candidate) + up to 6 calls per candidate
    (5 analysts + 1 judge). Mirrors backend/app/council/orchestrator.py's actual
    shape.
    """
    if num_candidates < 0:
        raise ValueError("num_candidates must be >= 0")

    calls_per_unit = _LEGACY_CALLS_PER_CANDIDATE
    total_calls = 1 + calls_per_unit * num_candidates  # +1 planner, once per run

    # The legacy council has no caching model in this benchmark -- every
    # call is a live model call, so effective == total.
    return CallBudgetEstimate(
        strategy="legacy_council",
        calls_per_unit=calls_per_unit,
        units=num_candidates,
        total_calls=total_calls,
        cache_hit_fraction=0.0,
        effective_calls=total_calls,
    )


def estimate_extraction_synthesis_verification(
    num_companies: int,
    *,
    extraction_batches: int = 3,
    cache_hit_fraction: float = 0.0,
    follow_up_calls: int = 0,
) -> CallBudgetEstimate:
    """extraction_batches + 1 synthesis + 1 verification calls per company,
    plus follow_up_calls (bounded repair/contradiction allowance, 0-2 per
    V3 section 9). cache_hit_fraction reduces only the extraction_batches
    portion (per V3's "cached extraction can reduce this to synthesis plus
    verification" -- synthesis/verification/follow-up are NOT reduced by
    caching in this model, only extraction is).
    """
    if num_companies < 0:
        raise ValueError("num_companies must be >= 0")
    if extraction_batches < 0:
        raise ValueError("extraction_batches must be >= 0")
    if not 0.0 <= cache_hit_fraction <= 1.0:
        raise ValueError("cache_hit_fraction must be within [0.0, 1.0]")
    if follow_up_calls < 0:
        raise ValueError("follow_up_calls must be >= 0")

    synthesis_calls = 1
    verification_calls = 1
    calls_per_unit = extraction_batches + synthesis_calls + verification_calls
    total_calls = calls_per_unit * num_companies + follow_up_calls

    # Only the extraction portion is discounted by cache hits.
    extraction_calls_total = extraction_batches * num_companies
    cached_extraction_calls = extraction_calls_total * cache_hit_fraction
    effective_extraction_calls = extraction_calls_total - cached_extraction_calls

    non_extraction_calls = (synthesis_calls + verification_calls) * num_companies + follow_up_calls
    effective_calls = round(effective_extraction_calls + non_extraction_calls)

    return CallBudgetEstimate(
        strategy="extraction_synthesis_verification",
        calls_per_unit=calls_per_unit,
        units=num_companies,
        total_calls=total_calls,
        cache_hit_fraction=cache_hit_fraction,
        effective_calls=effective_calls,
    )


def compare(estimates: list[CallBudgetEstimate]) -> str:
    """Returns a small human-readable comparison table (plain text, not
    Rich/markdown-heavy) showing strategy/total_calls/effective_calls side
    by side, sorted by effective_calls ascending. This is what the
    coordinator will paste into a phase report as call-budget evidence.
    """
    if not estimates:
        return "(no estimates provided)"

    rows = sorted(estimates, key=lambda e: e.effective_calls)

    strategy_width = max(len("strategy"), *(len(e.strategy) for e in rows))
    header = (
        f"{'strategy':<{strategy_width}}  {'units':>5}  {'calls/unit':>10}  "
        f"{'total':>6}  {'cache_hit':>9}  {'effective':>9}"
    )
    lines = [header, "-" * len(header)]
    for e in rows:
        lines.append(
            f"{e.strategy:<{strategy_width}}  {e.units:>5}  {e.calls_per_unit:>10}  "
            f"{e.total_calls:>6}  {e.cache_hit_fraction:>9.2f}  {e.effective_calls:>9}"
        )
    return "\n".join(lines)
