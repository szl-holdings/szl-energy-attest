# SPDX-License-Identifier: Apache-2.0
"""Synthetic receipt tests only; no model, network, GPU, or paid calls."""

import copy
import time
from datetime import datetime, timedelta, timezone

import pytest

from szl_energy_attest.agentic_efficiency import (
    FULL_STACK_ENERGY_COMPARISON,
    FULL_STACK_ENERGY_UNAVAILABLE,
    LOCAL_GPU_BOARD_ENERGY_COMPARISON,
    LOCAL_GPU_BOARD_ENERGY_UNAVAILABLE,
    NOT_ATTRIBUTABLE,
    TASKS_NOT_COMPARABLE,
    ReceiptValidationError,
    compare_agentic_efficiency,
)

AS_OF = "2026-11-20T12:00:00Z"
WINDOW_START = "2026-11-20T09:00:00Z"
WINDOW_END = "2026-11-20T11:00:00Z"
TASK_HASH = "a" * 64
RUBRIC_HASH = "b" * 64
MEASUREMENT_HASH = "c" * 64
SOURCE_HASHES = {"SOLO": "1" * 64, "TRIAD": "1" * 64}


def _timestamp(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _attempt(
    task_id,
    attempt_id,
    start,
    *,
    accepted=True,
    joules=10.0,
    input_tokens=100,
    output_tokens=50,
    billed_usd=0.1,
    duration=timedelta(minutes=5),
):
    end = start + duration
    return {
        "task_id": task_id,
        "attempt_id": attempt_id,
        "source_sha256": SOURCE_HASHES["SOLO"],
        "started_at": _timestamp(start),
        "ended_at": _timestamp(end),
        "recorded_at": _timestamp(end + timedelta(seconds=5)),
        "accepted": accepted,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "device_id": "gpu-0",
        "billed_usd": {"state": "OBSERVED", "usd": billed_usd},
        "local_gpu_energy": {
            "state": "MEASURED",
            "joules": joules,
            "device_id": "gpu-0",
            "measurement_id": attempt_id + "-nvml",
            "measurement_source_sha256": MEASUREMENT_HASH,
            "measurement_mode": "measured-energy",
            "started_at": _timestamp(start),
            "ended_at": _timestamp(end),
            "exclusive": True,
            "complete": True,
            "unrelated_workload": False,
            "baseline_subtracted": False,
        },
    }


def _cohort(system, attempts):
    cohort = {
        "system": system,
        "task_cohort_sha256": TASK_HASH,
        "quality_rubric_sha256": RUBRIC_HASH,
        "source_sha256": SOURCE_HASHES[system],
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "attempts": attempts,
        "remote_models": [],
        "system_overhead_energy": {"state": "UNMEASURED", "joules": None},
    }
    for attempt in cohort["attempts"]:
        attempt["source_sha256"] = cohort["source_sha256"]
    if system == "TRIAD":
        cohort["remote_models"] = [
            {"model_id": "GPT-6", "energy": {"state": "UNKNOWN", "joules": None}},
            {"model_id": "Mistral", "energy": {"state": "UNKNOWN", "joules": None}},
        ]
    return cohort


def _fixtures():
    solo = _cohort(
        "SOLO",
        [
            _attempt(
                "task-a",
                "solo-a-1",
                datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc),
                accepted=False,
                joules=10.0,
                input_tokens=100,
                output_tokens=20,
            ),
            _attempt(
                "task-a",
                "solo-a-2",
                datetime(2026, 11, 20, 9, 5, tzinfo=timezone.utc),
                accepted=True,
                joules=20.0,
                input_tokens=120,
                output_tokens=60,
                billed_usd=0.2,
            ),
        ],
    )
    triad = _cohort(
        "TRIAD",
        [
            _attempt(
                "task-a",
                "triad-a-1",
                datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc),
                joules=12.0,
                input_tokens=300,
                output_tokens=60,
                billed_usd=0.5,
            ),
        ],
    )
    return solo, triad


def _compare(solo, triad, **kwargs):
    options = {"as_of": AS_OF, "max_receipt_age_seconds": 86400}
    options.update(kwargs)
    return compare_agentic_efficiency(solo, triad, **options)


def test_equal_quality_exclusive_measurements_allow_only_scoped_local_comparison():
    solo, triad = _fixtures()
    result = _compare(solo, triad)

    assert result["state"] == LOCAL_GPU_BOARD_ENERGY_COMPARISON
    assert result["task_comparison"]["state"] == "COMPARABLE"
    local = result["local_gpu_board_energy"]
    assert local["state"] == LOCAL_GPU_BOARD_ENERGY_COMPARISON
    assert local["winner"] is None
    assert local["reported_lower_energy_system"] == "TRIAD"
    assert result["verification_scope"] == "DECLARED_INPUT_SHAPES_ONLY"
    for flag in ("receipt_signatures_verified", "device_exclusivity_independently_verified",
                 "remote_energy_independently_verified", "energy_savings_proven",
                 "production_qualified", "automatic_routing_authorized"):
        assert result[flag] is False
    assert local["joules"] == {"SOLO": 30.0, "TRIAD": 12.0}
    assert local["joules_per_accepted_task"] == {"SOLO": 30.0, "TRIAD": 12.0}
    assert result["full_stack_energy"]["state"] == FULL_STACK_ENERGY_UNAVAILABLE
    assert result["full_stack_energy"]["winner"] is None
    assert result["cohorts"]["TRIAD"]["cloud_energy"] == {
        "state": "UNKNOWN",
        "joules": None,
    }
    assert result["cohorts"]["SOLO"]["attempt_count"] == 2
    assert result["cohorts"]["SOLO"]["input_tokens"] == 220
    assert result["cohorts"]["SOLO"]["output_tokens"] == 80
    assert result["cohorts"]["SOLO"]["billed_usd"]["usd"] == pytest.approx(0.3)


def test_different_tasks_or_quality_never_produce_an_energy_winner():
    solo, triad = _fixtures()
    triad["attempts"][0]["task_id"] = "different-task"
    result = _compare(solo, triad)
    assert result["state"] == TASKS_NOT_COMPARABLE
    assert result["local_gpu_board_energy"]["winner"] is None
    assert result["full_stack_energy"]["state"] == FULL_STACK_ENERGY_UNAVAILABLE
    assert result["full_stack_energy"]["winner"] is None

    solo, triad = _fixtures()
    triad["attempts"][0]["accepted"] = False
    result = _compare(solo, triad)
    assert result["state"] == TASKS_NOT_COMPARABLE
    assert result["local_gpu_board_energy"]["winner"] is None


def test_shared_unrelated_gpu_workload_is_not_attributable_and_not_zero():
    solo, triad = _fixtures()
    solo["attempts"][0]["local_gpu_energy"].update(
        exclusive=False,
        unrelated_workload=True,
        detail="Unrelated gpt-oss:20b workload shared the board",
    )
    result = _compare(solo, triad)
    assert result["state"] == NOT_ATTRIBUTABLE
    assert result["local_gpu_board_energy"]["joules"]["SOLO"] is None
    assert result["local_gpu_board_energy"]["winner"] is None


def test_missing_local_interval_is_unavailable_never_zero_filled():
    solo, triad = _fixtures()
    solo["attempts"][0]["local_gpu_energy"] = {"state": "UNAVAILABLE", "joules": None}
    result = _compare(solo, triad)
    assert result["state"] == LOCAL_GPU_BOARD_ENERGY_UNAVAILABLE
    assert result["local_gpu_board_energy"]["joules"]["SOLO"] is None
    assert result["local_gpu_board_energy"]["winner"] is None


def test_duplicate_task_attempt_pair_is_rejected():
    solo, triad = _fixtures()
    duplicate = copy.deepcopy(solo["attempts"][0])
    solo["attempts"].append(duplicate)
    with pytest.raises(ReceiptValidationError, match="duplicate task/attempt"):
        _compare(solo, triad)


def test_overlapping_exclusive_device_intervals_are_rejected():
    solo, triad = _fixtures()
    overlap = _attempt(
        "task-a",
        "solo-overlap",
        datetime(2026, 11, 20, 9, 2, tzinfo=timezone.utc),
        accepted=False,
    )
    overlap["source_sha256"] = solo["source_sha256"]
    solo["attempts"].append(overlap)
    with pytest.raises(ReceiptValidationError, match="overlapping"):
        _compare(solo, triad)


@pytest.mark.parametrize("problem", ["missing", "stale", "naive"])
def test_missing_stale_or_naive_timestamps_are_rejected(problem):
    solo, triad = _fixtures()
    if problem == "missing":
        del solo["attempts"][0]["recorded_at"]
    elif problem == "stale":
        with pytest.raises(ReceiptValidationError, match="stale"):
            _compare(solo, triad, as_of="2026-11-22T12:00:00Z")
        return
    else:
        solo["attempts"][0]["recorded_at"] = "2026-11-20T09:05:05"
    with pytest.raises(ReceiptValidationError):
        _compare(solo, triad)


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_tokens", True),
        ("output_tokens", False),
        ("accepted", 1),
    ],
)
def test_bool_is_not_an_integer_and_outcome_must_be_boolean(field, value):
    solo, triad = _fixtures()
    solo["attempts"][0][field] = value
    with pytest.raises(ReceiptValidationError):
        _compare(solo, triad)


def test_nan_and_missing_outcomes_are_rejected():
    solo, triad = _fixtures()
    solo["attempts"][0]["local_gpu_energy"]["joules"] = float("nan")
    with pytest.raises(ReceiptValidationError, match="finite"):
        _compare(solo, triad)

    solo, triad = _fixtures()
    del solo["attempts"][0]["accepted"]
    with pytest.raises(ReceiptValidationError, match="accepted"):
        _compare(solo, triad)


def test_zero_accepted_outcomes_do_not_divide_by_zero_or_pick_winner():
    solo, triad = _fixtures()
    for cohort in (solo, triad):
        for attempt in cohort["attempts"]:
            attempt["accepted"] = False
    result = _compare(solo, triad)
    assert result["state"] == TASKS_NOT_COMPARABLE
    assert result["local_gpu_board_energy"]["joules_per_accepted_task"] == {
        "SOLO": None,
        "TRIAD": None,
    }
    assert result["local_gpu_board_energy"]["winner"] is None


def test_conflicting_receipt_source_and_cohort_hash_are_not_silently_accepted():
    solo, triad = _fixtures()
    solo["attempts"][0]["source_sha256"] = "f" * 64
    with pytest.raises(ReceiptValidationError, match="source"):
        _compare(solo, triad)

    solo, triad = _fixtures()
    triad["quality_rubric_sha256"] = "f" * 64
    result = _compare(solo, triad)
    assert result["state"] == TASKS_NOT_COMPARABLE
    assert result["local_gpu_board_energy"]["winner"] is None

    solo, triad = _fixtures()
    triad["source_sha256"] = "f" * 64
    for attempt in triad["attempts"]:
        attempt["source_sha256"] = "f" * 64
    result = _compare(solo, triad)
    assert result["state"] == TASKS_NOT_COMPARABLE
    assert "pinned source hashes differ" in result["task_comparison"]["reasons"]
    assert result["local_gpu_board_energy"]["reported_lower_energy_system"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("started_at", "2026-11-20T09:00:01Z"),
        ("device_id", "other-gpu"),
        ("complete", False),
        ("baseline_subtracted", True),
    ],
)
def test_local_measurement_must_match_and_be_complete_without_baseline(field, value):
    solo, triad = _fixtures()
    solo["attempts"][0]["local_gpu_energy"][field] = value
    with pytest.raises(ReceiptValidationError):
        _compare(solo, triad)


def test_billing_is_observed_only_and_never_converted_to_energy():
    solo, triad = _fixtures()
    del triad["attempts"][0]["billed_usd"]
    triad["attempts"][0]["input_tokens"] = 999999
    result = _compare(solo, triad)
    billed = result["cohorts"]["TRIAD"]["billed_usd"]
    assert billed["state"] == "UNAVAILABLE"
    assert billed["usd"] is None
    assert result["local_gpu_board_energy"]["joules"]["TRIAD"] == 12.0
    assert result["cohorts"]["TRIAD"]["cloud_energy"]["joules"] is None


def test_independently_measured_remote_and_overhead_can_complete_full_stack():
    solo, triad = _fixtures()
    for cohort in (solo, triad):
        cohort["system_overhead_energy"] = {
            "state": "MEASURED",
            "joules": 1.0,
            "source_sha256": "d" * 64,
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
        }
    for model in triad["remote_models"]:
        model["energy"] = {
            "state": "MEASURED",
            "joules": 2.0,
            "source_sha256": "e" * 64,
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "independent": True,
        }
    result = _compare(solo, triad)
    assert result["state"] == FULL_STACK_ENERGY_COMPARISON
    assert result["full_stack_energy"]["state"] == FULL_STACK_ENERGY_COMPARISON
    assert result["full_stack_energy"]["joules"] == {"SOLO": 31.0, "TRIAD": 17.0}
    assert result["full_stack_energy"]["winner"] is None
    assert result["full_stack_energy"]["reported_lower_energy_system"] == "TRIAD"
    assert result["energy_savings_proven"] is False


def test_large_synthetic_cohort_is_linear_enough_for_offline_admission():
    start = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    solo_attempts = []
    triad_attempts = []
    for index in range(1000):
        solo_attempts.append(
            _attempt(
                f"task-{index}",
                f"solo-{index}",
                start + timedelta(seconds=index),
                joules=2.0,
                duration=timedelta(milliseconds=100),
            )
        )
        triad_attempts.append(
            _attempt(
                f"task-{index}",
                f"triad-{index}",
                start + timedelta(hours=1, seconds=index),
                joules=1.0,
                duration=timedelta(milliseconds=100),
            )
        )
    solo = _cohort("SOLO", solo_attempts)
    triad = _cohort("TRIAD", triad_attempts)
    started = time.perf_counter()
    result = _compare(solo, triad)
    elapsed = time.perf_counter() - started
    assert result["cohorts"]["SOLO"]["task_count"] == 1000
    assert result["local_gpu_board_energy"]["winner"] is None
    assert result["local_gpu_board_energy"]["reported_lower_energy_system"] == "TRIAD"
    assert elapsed < 5.0
