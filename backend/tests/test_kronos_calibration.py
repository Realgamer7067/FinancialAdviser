"""Tests for the Kronos calibration harness (docs/V2-RETHINK.md section 2a),
`app/backtesting/kronos_calibration.py`. No test file existed for this module
before Phase 09 -- this covers artifact save/load correctness, malformed/
incomplete artifact handling, and low-sample-size behavior (never fabricate
confidence from a handful of samples).

Note (V3 15.2 gap, stated openly rather than silently skipped): the module as
written has NO configurable minimum-sample-count threshold below which a
bucket is refused -- `build_calibration_table` records `hit_rate` for any
bucket with >=1 sample, and `lookup_confidence` only refuses a bucket with
*zero* samples. A bucket with, say, 2 samples produces a hit_rate of 0.0, 0.5,
or 1.0 with no confidence interval or minimum-N gate. This is a real
architectural gap, not something these tests can paper over without changing
the module (out of scope for this read-mostly phase) -- so the low-sample
tests below assert the CURRENT (permissive) behavior and flag it explicitly,
rather than asserting a threshold that doesn't exist in the code.
"""

import json

import pytest

from app.backtesting.kronos_calibration import (
    CalibrationSample,
    _bucket,
    _table_path,
    build_calibration_table,
    lookup_confidence,
    save_calibration_table,
)


def test_bucket_boundaries():
    assert _bucket(0.5) == "<=0.5"
    assert _bucket(0.55) == "<=0.6"
    assert _bucket(0.61) == "<=0.7"
    assert _bucket(1.0) == "<=1.0"
    # out-of-range inputs are clamped into [0.5, 1.0] rather than crashing
    assert _bucket(0.0) == "<=0.5"
    assert _bucket(2.0) == "<=1.0"


def test_build_calibration_table_reports_naive_baseline_alongside_hit_rate():
    samples = [
        CalibrationSample(direction_agreement=0.65, kronos_correct=True, naive_correct=False),
        CalibrationSample(direction_agreement=0.65, kronos_correct=True, naive_correct=False),
        CalibrationSample(direction_agreement=0.65, kronos_correct=False, naive_correct=False),
        CalibrationSample(direction_agreement=0.95, kronos_correct=True, naive_correct=False),
    ]
    table = build_calibration_table(samples)

    assert table["<=0.7"]["sample_size"] == 3
    assert table["<=0.7"]["hit_rate"] == pytest.approx(2 / 3)
    assert table["<=0.7"]["naive_baseline_hit_rate"] == pytest.approx(0.0)

    assert table["<=1.0"]["sample_size"] == 1
    assert table["<=1.0"]["hit_rate"] == pytest.approx(1.0)

    # buckets with zero samples are present but explicitly null, never a
    # fabricated hit rate.
    assert table["<=0.5"] == {"sample_size": 0, "hit_rate": None, "naive_baseline_hit_rate": None}


def test_build_calibration_table_single_sample_bucket_is_not_gated(monkeypatch):
    """Documents the actual (permissive) current behavior: a bucket with a
    single sample produces a fully-confident-looking 0%/100% hit_rate with no
    minimum-sample-count gate anywhere in this module. This is the V3 15.2 gap
    -- flagged in the module docstring above, not silently accepted as correct
    design. If a minimum-sample threshold is later added to
    `build_calibration_table`, this test should be updated to assert the new
    gated behavior instead."""
    samples = [CalibrationSample(direction_agreement=0.55, kronos_correct=True, naive_correct=False)]
    table = build_calibration_table(samples)
    assert table["<=0.6"]["sample_size"] == 1
    assert table["<=0.6"]["hit_rate"] == 1.0  # no shrinkage/interval -- gap, not a guarantee


def test_save_and_lookup_confidence_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("app.backtesting.kronos_calibration._CALIBRATION_ROOT", tmp_path)
    samples = [
        CalibrationSample(direction_agreement=0.8, kronos_correct=True, naive_correct=False),
        CalibrationSample(direction_agreement=0.8, kronos_correct=True, naive_correct=False),
        CalibrationSample(direction_agreement=0.8, kronos_correct=False, naive_correct=False),
    ]
    table = build_calibration_table(samples)
    path = save_calibration_table("Kronos-small+sc8+T1.0+p0.9", "30d", table)
    assert path.exists()

    confidence = lookup_confidence(
        model_version="Kronos-small+sc8+T1.0+p0.9", horizon="30d", direction_agreement=0.8
    )
    assert confidence == pytest.approx(2 / 3)


def test_lookup_confidence_returns_none_when_no_table_exists(tmp_path, monkeypatch):
    monkeypatch.setattr("app.backtesting.kronos_calibration._CALIBRATION_ROOT", tmp_path)
    confidence = lookup_confidence(model_version="never-seen-version", horizon="30d", direction_agreement=0.9)
    assert confidence is None


def test_lookup_confidence_returns_none_for_zero_sample_bucket(tmp_path, monkeypatch):
    monkeypatch.setattr("app.backtesting.kronos_calibration._CALIBRATION_ROOT", tmp_path)
    table = {
        "<=0.5": {"sample_size": 0, "hit_rate": None, "naive_baseline_hit_rate": None},
        "<=1.0": {"sample_size": 5, "hit_rate": 0.8, "naive_baseline_hit_rate": 0.1},
    }
    save_calibration_table("v1", "7d", table)

    # direction_agreement 0.3 clamps into the "<=0.5" bucket, which has zero
    # samples -- must return None, never fabricate a confidence.
    assert lookup_confidence(model_version="v1", horizon="7d", direction_agreement=0.3) is None
    assert lookup_confidence(model_version="v1", horizon="7d", direction_agreement=0.99) == pytest.approx(0.8)


def test_lookup_confidence_returns_none_on_malformed_json(tmp_path, monkeypatch):
    monkeypatch.setattr("app.backtesting.kronos_calibration._CALIBRATION_ROOT", tmp_path)
    path = _table_path("v1", "30d")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json")

    assert lookup_confidence(model_version="v1", horizon="30d", direction_agreement=0.9) is None


def test_lookup_confidence_returns_none_on_incomplete_artifact_missing_bucket(tmp_path, monkeypatch):
    """An artifact that only has some buckets (e.g. produced by a partial/
    aborted calibration run) must fail closed for a bucket it doesn't cover --
    never silently return another bucket's value or a fabricated one."""
    monkeypatch.setattr("app.backtesting.kronos_calibration._CALIBRATION_ROOT", tmp_path)
    incomplete_table = {"<=0.5": {"sample_size": 3, "hit_rate": 0.6, "naive_baseline_hit_rate": 0.2}}
    save_calibration_table("v1", "90d", incomplete_table)

    assert lookup_confidence(model_version="v1", horizon="90d", direction_agreement=0.5) == pytest.approx(0.6)
    # a bucket the artifact never recorded (e.g. "<=1.0") must be a clean None
    assert lookup_confidence(model_version="v1", horizon="90d", direction_agreement=1.0) is None


def test_lookup_confidence_returns_none_when_entry_present_but_hit_rate_missing(tmp_path, monkeypatch):
    """Guards a malformed-but-valid-JSON artifact: a bucket entry present
    without a usable sample_size must not be treated as calibrated."""
    monkeypatch.setattr("app.backtesting.kronos_calibration._CALIBRATION_ROOT", tmp_path)
    path = _table_path("v1", "30d")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"<=0.6": {"hit_rate": 0.9}}))  # sample_size absent entirely

    assert lookup_confidence(model_version="v1", horizon="30d", direction_agreement=0.55) is None


@pytest.mark.parametrize(
    "entry",
    [
        {"sample_size": 5, "hit_rate": None},  # nonzero samples but null hit_rate (as
        # build_calibration_table itself emits for a zero-sample bucket -- a
        # hand-edited/partially-merged artifact could pair a nonzero sample_size
        # with this null)
        {"sample_size": 5},  # hit_rate key entirely absent
        {"sample_size": 5, "hit_rate": "0.8"},  # wrong type -- must not be silently accepted
        {"sample_size": 5, "hit_rate": [0.8]},
    ],
)
def test_lookup_confidence_fails_closed_on_malformed_hit_rate_values(tmp_path, monkeypatch, entry):
    """A nonzero sample_size paired with a null/missing/wrong-typed hit_rate
    must return None, not raise (TypeError from float(None), KeyError from a
    missing key) and not silently coerce a string/list into a float."""
    monkeypatch.setattr("app.backtesting.kronos_calibration._CALIBRATION_ROOT", tmp_path)
    path = _table_path("v1", "30d")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"<=0.6": entry}))

    assert lookup_confidence(model_version="v1", horizon="30d", direction_agreement=0.55) is None
