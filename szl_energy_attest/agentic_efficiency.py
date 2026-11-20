# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Offline SOLO/TRIAD comparison of externally recorded attempt receipts.

This module never invokes a model, GPU, network, clock, or environment variable.
It does not measure energy. It admits only source-bound, time-bounded records and
preserves unavailable and non-attributable energy as null rather than zero.
"""

# ruff: noqa: UP045
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

SOLO = "SOLO"
TRIAD = "TRIAD"
MEASURED = "MEASURED"
UNKNOWN = "UNKNOWN"
NOT_ATTRIBUTABLE = "NOT_ATTRIBUTABLE"
TASKS_NOT_COMPARABLE = "TASKS_NOT_COMPARABLE"
LOCAL_GPU_BOARD_ENERGY_COMPARISON = "LOCAL_GPU_BOARD_ENERGY_COMPARISON"
LOCAL_GPU_BOARD_ENERGY_UNAVAILABLE = "LOCAL_GPU_BOARD_ENERGY_UNAVAILABLE"
FULL_STACK_ENERGY_COMPARISON = "FULL_STACK_ENERGY_COMPARISON"
FULL_STACK_ENERGY_UNAVAILABLE = "FULL_STACK_ENERGY_UNAVAILABLE"

_MEASUREMENT_MODES = ("measured-energy", "measured-power-integral")
_HASH_RE = re.compile(r"[0-9a-fA-F]{64}\Z")


class ReceiptValidationError(ValueError):
    """An input receipt is malformed, internally inconsistent, or unsafe to sum."""


def _fail(path: str, message: str) -> None:
    raise ReceiptValidationError(f"{path}: {message}")


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    return value


def _text(container: dict[str, Any], field: str, path: str) -> str:
    value = container.get(field)
    if not isinstance(value, str) or not value.strip():
        _fail(path + "." + field, "must be a non-empty string")
    return value.strip()


def _hash(container: dict[str, Any], field: str, path: str) -> str:
    value = _text(container, field, path)
    if _HASH_RE.fullmatch(value) is None:
        _fail(path + "." + field, "must be a SHA-256 hex digest")
    return value.lower()


def _boolean(container: dict[str, Any], field: str, path: str) -> bool:
    value = container.get(field)
    if not isinstance(value, bool):
        _fail(path + "." + field, "must be a boolean")
    return value


def _integer(container: dict[str, Any], field: str, path: str) -> int:
    value = container.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path + "." + field, "must be a non-negative integer, not a boolean")
    return value


def _number(value: Any, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "must be a finite number, not a boolean")
    try:
        result = float(value)
    except OverflowError:
        _fail(path, "must be finite")
    if not math.isfinite(result):
        _fail(path, "must be finite")
    if result < 0 or (positive and result <= 0):
        _fail(path, "must be %s" % ("positive" if positive else "non-negative"))
    return result


def _timestamp(container: dict[str, Any], field: str, path: str) -> datetime:
    value = container.get(field)
    field_path = path + "." + field
    if not isinstance(value, str) or not value:
        _fail(field_path, "timestamp is required")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        _fail(field_path, "must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(field_path, "timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _reject_nonfinite(value: Any, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _fail(path, "numbers must be finite")
    if isinstance(value, dict):
        for key, member in value.items():
            _reject_nonfinite(member, f"{path}.{key}")
    elif isinstance(value, list):
        for index, member in enumerate(value):
            _reject_nonfinite(member, f"{path}[{index}]")


def _external_energy(
    record: Any,
    path: str,
    allowed_states: tuple[str, ...],
    window_start: datetime,
    window_end: datetime,
    *,
    independent: bool = False,
) -> tuple[str, Optional[float], Optional[str]]:
    energy = _mapping(record, path)
    state = energy.get("state")
    if state not in allowed_states:
        _fail(path + ".state", f"must be one of {allowed_states}")
    if energy.get("baseline_subtracted") is True:
        _fail(path, "baseline subtraction is not supported")
    if state != MEASURED:
        if energy.get("joules") is not None:
            _fail(path + ".joules", "must be null when energy is not MEASURED")
        return state, None, None
    joules = _number(energy.get("joules"), path + ".joules")
    source = _hash(energy, "source_sha256", path)
    measured_start = _timestamp(energy, "window_start", path)
    measured_end = _timestamp(energy, "window_end", path)
    if measured_start != window_start or measured_end != window_end:
        _fail(path, "measurement window must exactly match the cohort window")
    if independent and not _boolean(energy, "independent", path):
        _fail(path + ".independent", "remote energy must be independently measured")
    return state, joules, source


def _billing(attempt: dict[str, Any], path: str) -> tuple[str, Optional[float]]:
    record = attempt.get("billed_usd")
    if record is None:
        return "UNAVAILABLE", None
    billing = _mapping(record, path + ".billed_usd")
    state = billing.get("state")
    if state not in ("OBSERVED", "UNAVAILABLE"):
        _fail(path + ".billed_usd.state", "must be OBSERVED or UNAVAILABLE")
    if state == "UNAVAILABLE":
        if billing.get("usd") is not None:
            _fail(path + ".billed_usd.usd", "must be null when UNAVAILABLE")
        return state, None
    return state, _number(billing.get("usd"), path + ".billed_usd.usd")


def _local_energy(
    attempt: dict[str, Any], path: str, started_at: datetime, ended_at: datetime
) -> tuple[str, Optional[float], Optional[dict[str, Any]], Optional[str]]:
    local = _mapping(attempt.get("local_gpu_energy"), path + ".local_gpu_energy")
    local_path = path + ".local_gpu_energy"
    state = local.get("state")
    if state not in (MEASURED, "UNAVAILABLE", NOT_ATTRIBUTABLE):
        _fail(
            local_path + ".state", "must be MEASURED, UNAVAILABLE, or NOT_ATTRIBUTABLE"
        )
    if local.get("baseline_subtracted") is True:
        _fail(local_path, "baseline subtraction is not supported")
    if state != MEASURED:
        if local.get("joules") is not None:
            _fail(local_path + ".joules", "must be null unless state is MEASURED")
        if local.get("exclusive") is True:
            _fail(
                local_path, "non-measured energy cannot claim an exclusive measurement"
            )
        return state, None, None, None

    joules = _number(local.get("joules"), local_path + ".joules")
    device_id = _text(local, "device_id", local_path)
    if _text(attempt, "device_id", path) != device_id:
        _fail(local_path + ".device_id", "must match the attempt device")
    measurement_id = _text(local, "measurement_id", local_path)
    measurement_source = _hash(local, "measurement_source_sha256", local_path)
    if local.get("measurement_mode") not in _MEASUREMENT_MODES:
        _fail(
            local_path + ".measurement_mode",
            "must identify the existing NVML meter mode",
        )
    measured_start = _timestamp(local, "started_at", local_path)
    measured_end = _timestamp(local, "ended_at", local_path)
    if measured_start != started_at or measured_end != ended_at:
        _fail(local_path, "measurement interval must exactly cover the attempt")
    exclusive = _boolean(local, "exclusive", local_path)
    unrelated = _boolean(local, "unrelated_workload", local_path)
    if _boolean(local, "baseline_subtracted", local_path):
        _fail(local_path, "baseline subtraction is not supported")
    if not exclusive or unrelated:
        return NOT_ATTRIBUTABLE, None, None, None
    if not _boolean(local, "complete", local_path):
        _fail(local_path + ".complete", "missing measurement intervals are UNAVAILABLE")
    interval = {
        "device_id": device_id,
        "measurement_id": measurement_id,
        "started_at": measured_start,
        "ended_at": measured_end,
        "path": local_path,
    }
    return state, joules, interval, measurement_source


def _validate_cohort(
    raw: Any, expected_system: str, as_of: datetime, max_age_seconds: float
) -> dict[str, Any]:
    path = expected_system
    cohort = _mapping(raw, path)
    if cohort.get("system") != expected_system:
        _fail(path + ".system", f"must be {expected_system}")
    task_hash = _hash(cohort, "task_cohort_sha256", path)
    rubric_hash = _hash(cohort, "quality_rubric_sha256", path)
    source_hash = _hash(cohort, "source_sha256", path)
    window_start = _timestamp(cohort, "window_start", path)
    window_end = _timestamp(cohort, "window_end", path)
    if window_start >= window_end or window_end > as_of:
        _fail(path, "cohort window must be ordered and end no later than as_of")

    attempts = _list(cohort.get("attempts"), path + ".attempts")
    if not attempts:
        _fail(path + ".attempts", "at least one attempt is required")
    pairs = set()
    task_ids = set()
    accepted_tasks = set()
    input_tokens = 0
    output_tokens = 0
    accepted_attempt_count = 0
    observed_billing = []
    measurements = []
    measurement_sources = set()
    local_states = []
    local_joules = []

    for index, raw_attempt in enumerate(attempts):
        attempt_path = f"{path}.attempts[{index}]"
        attempt = _mapping(raw_attempt, attempt_path)
        task_id = _text(attempt, "task_id", attempt_path)
        attempt_id = _text(attempt, "attempt_id", attempt_path)
        pair = (task_id, attempt_id)
        if pair in pairs:
            _fail(attempt_path, "duplicate task/attempt ID")
        pairs.add(pair)
        task_ids.add(task_id)
        if _hash(attempt, "source_sha256", attempt_path) != source_hash:
            _fail(attempt_path + ".source_sha256", "conflicts with cohort source")
        started_at = _timestamp(attempt, "started_at", attempt_path)
        ended_at = _timestamp(attempt, "ended_at", attempt_path)
        recorded_at = _timestamp(attempt, "recorded_at", attempt_path)
        if started_at >= ended_at or started_at < window_start or ended_at > window_end:
            _fail(
                attempt_path,
                "attempt interval must be ordered and inside the cohort window",
            )
        if recorded_at < ended_at or recorded_at > as_of:
            _fail(
                attempt_path + ".recorded_at", "must be between attempt end and as_of"
            )
        if (as_of - recorded_at).total_seconds() > max_age_seconds:
            _fail(attempt_path + ".recorded_at", "timestamp is stale")
        accepted = _boolean(attempt, "accepted", attempt_path)
        if accepted:
            accepted_tasks.add(task_id)
            accepted_attempt_count += 1
        input_tokens += _integer(attempt, "input_tokens", attempt_path)
        output_tokens += _integer(attempt, "output_tokens", attempt_path)
        billing_state, billed_usd = _billing(attempt, attempt_path)
        if billing_state == "OBSERVED":
            observed_billing.append(billed_usd)
        local_state, joules, interval, measurement_source = _local_energy(
            attempt, attempt_path, started_at, ended_at
        )
        local_states.append(local_state)
        if joules is not None:
            local_joules.append(joules)
        if interval is not None:
            measurements.append(interval)
        if measurement_source is not None:
            measurement_sources.add(measurement_source)

    if NOT_ATTRIBUTABLE in local_states:
        local_state = NOT_ATTRIBUTABLE
    elif all(state == MEASURED for state in local_states):
        local_state = MEASURED
    else:
        local_state = LOCAL_GPU_BOARD_ENERGY_UNAVAILABLE
    local_total = (
        _finite_sum(local_joules, path + ".local_gpu_energy")
        if local_state == MEASURED
        else None
    )

    remote_models = _list(cohort.get("remote_models"), path + ".remote_models")
    model_ids = set()
    remote_joules = []
    remote_sources = []
    remote_unknown = False
    for index, raw_model in enumerate(remote_models):
        model_path = f"{path}.remote_models[{index}]"
        model = _mapping(raw_model, model_path)
        model_id = _text(model, "model_id", model_path)
        if model_id in model_ids:
            _fail(model_path + ".model_id", "duplicate remote model")
        model_ids.add(model_id)
        state, joules, source = _external_energy(
            model.get("energy"),
            model_path + ".energy",
            (UNKNOWN, MEASURED),
            window_start,
            window_end,
            independent=True,
        )
        if state == UNKNOWN:
            remote_unknown = True
        else:
            remote_joules.append(joules)
            remote_sources.append(source)
    if not remote_models:
        cloud_state = "NOT_APPLICABLE"
        cloud_total = None
    elif remote_unknown:
        cloud_state = UNKNOWN
        cloud_total = None
    else:
        cloud_state = MEASURED
        cloud_total = _finite_sum(remote_joules, path + ".remote_models")

    overhead_state, overhead_joules, overhead_source = _external_energy(
        cohort.get("system_overhead_energy"),
        path + ".system_overhead_energy",
        ("UNMEASURED", MEASURED),
        window_start,
        window_end,
    )
    all_billing_observed = len(observed_billing) == len(attempts)
    billing_total = (
        _finite_sum(observed_billing, path + ".billed_usd")
        if all_billing_observed
        else None
    )
    cloud_energy = {"state": cloud_state, "joules": cloud_total}
    if remote_sources and cloud_state == MEASURED:
        cloud_energy["source_sha256"] = sorted(remote_sources)
    overhead_energy = {"state": overhead_state, "joules": overhead_joules}
    if overhead_source is not None:
        overhead_energy["source_sha256"] = overhead_source
    task_count = len(task_ids)
    summary = {
        "system": expected_system,
        "source_sha256": source_hash,
        "window_start": _iso(window_start),
        "window_end": _iso(window_end),
        "task_count": task_count,
        "attempt_count": len(attempts),
        "accepted_task_count": len(accepted_tasks),
        "accepted_attempt_count": accepted_attempt_count,
        "acceptance_rate": len(accepted_tasks) / task_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "billed_usd": {
            "state": "OBSERVED" if all_billing_observed else "UNAVAILABLE",
            "usd": billing_total,
            "observed_attempt_count": len(observed_billing),
        },
        "local_gpu_board_energy": {
            "state": local_state,
            "joules": local_total,
            "measured_attempt_count": len(local_joules),
            "device_ids": sorted({m["device_id"] for m in measurements}),
            "measurement_source_hashes": sorted(measurement_sources),
        },
        "cloud_energy": cloud_energy,
        "system_overhead_energy": overhead_energy,
    }
    return {
        "summary": summary,
        "task_hash": task_hash,
        "rubric_hash": rubric_hash,
        "window": (window_start, window_end),
        "task_ids": task_ids,
        "accepted_tasks": accepted_tasks,
        "measurements": measurements,
        "local_total": local_total,
        "cloud_total": cloud_total,
        "overhead_joules": overhead_joules,
    }


def _finite_sum(values: list[Optional[float]], path: str) -> float:
    try:
        result = math.fsum(value for value in values if value is not None)
    except OverflowError:
        _fail(path, "sum must be finite")
    if not math.isfinite(result):
        _fail(path, "sum must be finite")
    return result


def _validate_measurement_uniqueness(cohorts: list[dict[str, Any]]) -> None:
    measurements = [m for cohort in cohorts for m in cohort["measurements"]]
    ids = set()
    by_device: dict[str, list[dict[str, Any]]] = {}
    for measurement in measurements:
        measurement_id = measurement["measurement_id"]
        if measurement_id in ids:
            _fail(measurement["path"], "duplicate measurement ID")
        ids.add(measurement_id)
        by_device.setdefault(measurement["device_id"], []).append(measurement)
    for device_measurements in by_device.values():
        ordered = sorted(
            device_measurements, key=lambda m: (m["started_at"], m["ended_at"])
        )
        previous = None
        for current in ordered:
            if previous is not None and current["started_at"] < previous["ended_at"]:
                _fail(current["path"], "overlapping exclusive device intervals")
            previous = current


def _winner(joules: dict[str, Optional[float]]) -> Optional[str]:
    solo = joules[SOLO]
    triad = joules[TRIAD]
    if solo is None or triad is None:
        return None
    if solo == triad:
        return "TIE"
    return SOLO if solo < triad else TRIAD


def _per_accepted_task(
    joules: dict[str, Optional[float]], cohorts: dict[str, dict[str, Any]]
) -> dict[str, Optional[float]]:
    result = {}
    for system in (SOLO, TRIAD):
        total = joules[system]
        denominator = len(cohorts[system]["accepted_tasks"])
        result[system] = (
            total / denominator if total is not None and denominator > 0 else None
        )
    return result


def compare_agentic_efficiency(
    solo: dict[str, Any],
    triad: dict[str, Any],
    *,
    as_of: str,
    max_receipt_age_seconds: float,
) -> dict[str, Any]:
    """Validate two cohort exports and return explicit scoped energy decisions.

    A local board winner requires identical tasks, accepted task sets, rubric and
    windows, plus a complete, exclusive, non-overlapping MEASURED interval for
    every attempt on both sides. No token, price, or baseline energy is inferred.
    """
    _reject_nonfinite({"SOLO": solo, "TRIAD": triad}, "input")
    as_of_container = {"as_of": as_of}
    evaluated_at = _timestamp(as_of_container, "as_of", "comparison")
    max_age = _number(
        max_receipt_age_seconds, "comparison.max_receipt_age_seconds", positive=True
    )
    validated = {
        SOLO: _validate_cohort(solo, SOLO, evaluated_at, max_age),
        TRIAD: _validate_cohort(triad, TRIAD, evaluated_at, max_age),
    }
    _validate_measurement_uniqueness(list(validated.values()))

    reasons = []
    if validated[SOLO]["task_hash"] != validated[TRIAD]["task_hash"]:
        reasons.append("task cohort hashes differ")
    if validated[SOLO]["summary"]["source_sha256"] != validated[TRIAD]["summary"]["source_sha256"]:
        reasons.append("pinned source hashes differ")
    if validated[SOLO]["rubric_hash"] != validated[TRIAD]["rubric_hash"]:
        reasons.append("quality rubric hashes differ")
    if validated[SOLO]["window"] != validated[TRIAD]["window"]:
        reasons.append("cohort time bounds differ")
    if validated[SOLO]["task_ids"] != validated[TRIAD]["task_ids"]:
        reasons.append("task ID sets differ")
    if validated[SOLO]["accepted_tasks"] != validated[TRIAD]["accepted_tasks"]:
        reasons.append("accepted task sets differ")
    for system in (SOLO, TRIAD):
        if not validated[system]["accepted_tasks"]:
            reasons.append(f"{system} has no accepted outcomes")
    comparable = not reasons
    task_state = "COMPARABLE" if comparable else TASKS_NOT_COMPARABLE

    local_joules = {
        system: validated[system]["local_total"] for system in (SOLO, TRIAD)
    }
    per_accepted = (
        _per_accepted_task(local_joules, validated)
        if comparable
        else {SOLO: None, TRIAD: None}
    )
    if not comparable:
        local_state = TASKS_NOT_COMPARABLE
    elif all(
        validated[s]["summary"]["local_gpu_board_energy"]["state"] == MEASURED
        for s in (SOLO, TRIAD)
    ):
        local_state = LOCAL_GPU_BOARD_ENERGY_COMPARISON
    elif any(
        validated[s]["summary"]["local_gpu_board_energy"]["state"] == NOT_ATTRIBUTABLE
        for s in (SOLO, TRIAD)
    ):
        local_state = NOT_ATTRIBUTABLE
    else:
        local_state = LOCAL_GPU_BOARD_ENERGY_UNAVAILABLE
    local_reported_lower = (
        _winner(local_joules)
        if local_state == LOCAL_GPU_BOARD_ENERGY_COMPARISON
        else None
    )
    local_result = {
        "state": local_state,
        "winner": None,
        "reported_lower_energy_system": local_reported_lower,
        "input_verification": "UNATTESTED_EXTERNAL_RECEIPTS",
        "joules": local_joules,
        "joules_per_accepted_task": per_accepted,
        "scope": "gross measured NVML board energy over all attempts; no baseline subtraction",
    }

    full_stack_reasons = list(reasons)
    measurement_reasons = []
    full_joules: dict[str, Optional[float]] = {SOLO: None, TRIAD: None}
    for system in (SOLO, TRIAD):
        summary = validated[system]["summary"]
        if summary["local_gpu_board_energy"]["state"] != MEASURED:
            measurement_reasons.append(
                f"{system} local board energy is not fully MEASURED"
            )
        if summary["cloud_energy"]["state"] == UNKNOWN:
            measurement_reasons.append(f"{system} remote model energy is UNKNOWN")
        if summary["system_overhead_energy"]["state"] != MEASURED:
            measurement_reasons.append(f"{system} system overhead is unmeasured")
    full_stack_reasons.extend(measurement_reasons)
    if comparable and not full_stack_reasons:
        for system in (SOLO, TRIAD):
            cohort = validated[system]
            remote = cohort["cloud_total"] if cohort["cloud_total"] is not None else 0.0
            full_joules[system] = _finite_sum(
                [cohort["local_total"], remote, cohort["overhead_joules"]],
                system + ".full_stack_energy",
            )
    if measurement_reasons:
        full_state = FULL_STACK_ENERGY_UNAVAILABLE
    elif not comparable:
        full_state = TASKS_NOT_COMPARABLE
    else:
        full_state = FULL_STACK_ENERGY_COMPARISON
    full_reported_lower = (
        _winner(full_joules) if full_state == FULL_STACK_ENERGY_COMPARISON else None
    )
    full_result = {
        "state": full_state,
        "winner": None,
        "reported_lower_energy_system": full_reported_lower,
        "input_verification": "UNATTESTED_EXTERNAL_RECEIPTS",
        "joules": full_joules,
        "joules_per_accepted_task": (
            _per_accepted_task(full_joules, validated)
            if full_state == FULL_STACK_ENERGY_COMPARISON
            else {SOLO: None, TRIAD: None}
        ),
        "reasons": full_stack_reasons,
    }

    return {
        "schema": "szl_energy_attest/agentic-efficiency@1",
        "verification_scope": "DECLARED_INPUT_SHAPES_ONLY",
        "receipt_signatures_verified": False,
        "device_exclusivity_independently_verified": False,
        "remote_energy_independently_verified": False,
        "energy_savings_proven": False,
        "production_qualified": False,
        "automatic_routing_authorized": False,
        "state": full_state
        if full_state == FULL_STACK_ENERGY_COMPARISON
        else local_state,
        "evaluated_as_of": _iso(evaluated_at),
        "max_receipt_age_seconds": max_age,
        "task_comparison": {
            "state": task_state,
            "task_cohort_sha256": {s: validated[s]["task_hash"] for s in (SOLO, TRIAD)},
            "quality_rubric_sha256": {
                s: validated[s]["rubric_hash"] for s in (SOLO, TRIAD)
            },
            "window": {
                s: {
                    "start": _iso(validated[s]["window"][0]),
                    "end": _iso(validated[s]["window"][1]),
                }
                for s in (SOLO, TRIAD)
            },
            "reasons": reasons,
        },
        "cohorts": {s: validated[s]["summary"] for s in (SOLO, TRIAD)},
        "local_gpu_board_energy": local_result,
        "full_stack_energy": full_result,
    }


__all__ = [
    "FULL_STACK_ENERGY_COMPARISON",
    "FULL_STACK_ENERGY_UNAVAILABLE",
    "LOCAL_GPU_BOARD_ENERGY_COMPARISON",
    "LOCAL_GPU_BOARD_ENERGY_UNAVAILABLE",
    "MEASURED",
    "NOT_ATTRIBUTABLE",
    "SOLO",
    "TASKS_NOT_COMPARABLE",
    "TRIAD",
    "UNKNOWN",
    "ReceiptValidationError",
    "compare_agentic_efficiency",
]
