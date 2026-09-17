"""Tests for the Phase 04 call-budget calculator (app/services/call_budget.py).

Verifies the legacy council call count against the real role list in
app/council/orchestrator.py (5 analysts: bull/bear/fundamental/quant/risk +
1 judge = 6 per candidate, + 1 planner once per run), and the V3 Section
11.2 "five calls when all extraction batches miss cache" / "cached
extraction can reduce this to synthesis plus verification" claims for the
new research shape.
"""

import inspect

from app.council import orchestrator
from app.services.call_budget import (
    CallBudgetEstimate,
    compare,
    estimate_extraction_synthesis_verification,
    estimate_legacy_council,
)


def test_legacy_council_matches_real_orchestrator_role_list():
    # Derive the real per-candidate role count from the orchestrator source
    # itself rather than hardcoding a number that could silently drift.
    source = inspect.getsource(orchestrator.run_candidate_council)
    role_specs_block = source.split("role_specs = [")[1].split("]")[0]
    analyst_role_count = role_specs_block.count("(\"")
    assert analyst_role_count == 5  # bull, bear, fundamental, quant, risk

    # Judge is a separate sequential call after the analysts.
    assert '"judge"' in source or "'judge'" in source

    calls_per_candidate = analyst_role_count + 1  # + judge
    assert calls_per_candidate == 6

    estimate = estimate_legacy_council(3)
    assert estimate.calls_per_unit == calls_per_candidate
    assert estimate.units == 3
    # 1 planner (once per run) + 6 calls * 3 candidates = 19
    assert estimate.total_calls == 1 + calls_per_candidate * 3 == 19
    assert estimate.effective_calls == estimate.total_calls
    assert estimate.strategy == "legacy_council"


def test_legacy_council_zero_candidates_is_just_the_planner():
    estimate = estimate_legacy_council(0)
    assert estimate.total_calls == 1
    assert estimate.effective_calls == 1


def test_extraction_synthesis_verification_five_calls_when_cache_misses():
    estimate = estimate_extraction_synthesis_verification(1, cache_hit_fraction=0.0)
    assert estimate.total_calls == 5  # 3 extraction + 1 synthesis + 1 verification
    assert estimate.effective_calls == 5
    assert estimate.calls_per_unit == 5


def test_extraction_synthesis_verification_full_cache_reduces_to_synthesis_and_verification():
    estimate = estimate_extraction_synthesis_verification(1, cache_hit_fraction=1.0)
    assert estimate.total_calls == 5  # raw total_calls unaffected by caching
    assert estimate.effective_calls == 2  # only synthesis + verification remain


def test_extraction_synthesis_verification_partial_cache():
    # 3 extraction batches, half cached -> 1.5 effective extraction calls
    # + 2 (synthesis/verification) = 3.5 -> rounds to 4.
    estimate = estimate_extraction_synthesis_verification(1, cache_hit_fraction=0.5)
    assert estimate.total_calls == 5
    assert estimate.effective_calls == 4


def test_follow_up_calls_add_exactly_to_total():
    baseline = estimate_extraction_synthesis_verification(2, cache_hit_fraction=0.0)
    with_followups = estimate_extraction_synthesis_verification(2, cache_hit_fraction=0.0, follow_up_calls=2)
    assert with_followups.total_calls == baseline.total_calls + 2
    assert with_followups.effective_calls == baseline.effective_calls + 2


def test_follow_up_calls_not_reduced_by_cache():
    estimate = estimate_extraction_synthesis_verification(1, cache_hit_fraction=1.0, follow_up_calls=2)
    # synthesis(1) + verification(1) + follow_up(2) = 4, extraction fully cached away
    assert estimate.effective_calls == 4


def test_custom_extraction_batches():
    estimate = estimate_extraction_synthesis_verification(1, extraction_batches=1, cache_hit_fraction=0.0)
    assert estimate.total_calls == 3  # 1 extraction + synthesis + verification


def test_invalid_inputs_raise():
    import pytest

    with pytest.raises(ValueError):
        estimate_legacy_council(-1)
    with pytest.raises(ValueError):
        estimate_extraction_synthesis_verification(1, cache_hit_fraction=1.5)
    with pytest.raises(ValueError):
        estimate_extraction_synthesis_verification(1, follow_up_calls=-1)


def test_compare_sorts_by_effective_calls_and_shows_both_strategies():
    legacy = estimate_legacy_council(3)
    new_shape = estimate_extraction_synthesis_verification(3, cache_hit_fraction=0.0)
    table = compare([legacy, new_shape])

    assert "legacy_council" in table
    assert "extraction_synthesis_verification" in table
    assert str(legacy.effective_calls) in table
    assert str(new_shape.effective_calls) in table

    # new_shape (15) should sort before legacy (19) since effective_calls is lower.
    assert table.index("extraction_synthesis_verification") < table.index("legacy_council")


def test_compare_empty_list():
    assert compare([]) == "(no estimates provided)"


def test_call_budget_estimate_is_frozen_dataclass():
    estimate = estimate_legacy_council(1)
    assert isinstance(estimate, CallBudgetEstimate)
    try:
        estimate.total_calls = 999  # type: ignore[misc]
        assert False, "expected FrozenInstanceError"
    except Exception:
        pass
