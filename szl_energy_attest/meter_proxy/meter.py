# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Honest energy measurement adapter for the per-inference proxy.

Thin adapter over the folded-in ``szl_energy_attest.inference_meter`` NVML
meter. It exists to translate the meter's internal mode strings into this
package's receipt-level honest states:

    MEASURED     — a real NVML hardware joule delta (energy counter) or a
                   trapezoidal power integral from real NVML power readback.
    UNAVAILABLE  — no usable NVML capability on this host (CPU-only box, CI
                   sandbox, no driver, no permission). ``measured_joules``
                   is ``None``. This is an audited state, not an error.
    ESTIMATED    — NEVER produced here. Estimates are only ever minted by the
                   clearly-labelled synthetic demo generator, and they land in
                   the SEPARATE ``estimated_joules`` field. Estimation never
                   blends into MEASURED.

Stdlib + lazy imports only. No network. Never raises from measurement.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

STATE_MEASURED = "MEASURED"
STATE_UNAVAILABLE = "UNAVAILABLE"
STATE_ESTIMATED = "ESTIMATED"  # demo-only; never emitted here


@dataclass
class EnergyMeasurement:
    """Result of attempting to measure one inference region. Never lies."""

    state: str  # MEASURED | UNAVAILABLE
    measured_joules: Optional[float]
    measurement_mode: Optional[str]  # meter's mode string when MEASURED
    wall_seconds: Optional[float]
    detail: str

    def as_receipt_energy(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "measured_joules": self.measured_joules,
            "estimated_joules": None,  # ESTIMATED lives only in synthetic demo
            "measurement_mode": self.measurement_mode,
            "detail": self.detail,
        }


class EnergyState:
    """Process-wide honest capability state, probed once."""

    def __init__(self) -> None:
        self._meter_cls = None
        self.capability: Dict[str, Any] = {
            "nvml_available": False,
            "preferred_mode": "unmeasured",
            "detail": "",
        }
        try:
            from szl_energy_attest.inference_meter import _energy as _e

            self._meter_cls = _e.EnergyMeter
            rep = _e.capability_report()
            avail = bool(rep.get("nvml_init_ok")) and int(rep.get("device_count", 0)) > 0
            self.capability = {
                "nvml_available": avail,
                "preferred_mode": rep.get("preferred_mode", "unmeasured"),
                "detail": (
                    "NVML live: %d device(s), preferred=%s"
                    % (rep.get("device_count", 0), rep.get("preferred_mode"))
                    if avail
                    else "no usable NVML capability on this host (%s)"
                    % (rep.get("import_error") or "no devices / init failed"),
                ),
            }
        except Exception as exc:  # noqa: BLE001 - absence of the meter is honest
            self.capability = {
                "nvml_available": False,
                "preferred_mode": "unmeasured",
                "detail": "inference_meter energy core not importable: %r" % (exc,),
            }

    @property
    def can_measure(self) -> bool:
        return bool(self.capability["nvml_available"])


def measure_inference_energy(state: EnergyState, fn, *args, **kwargs):
    """Run *fn* under an honest energy measurement.

    Returns ``(result, EnergyMeasurement)``. On hosts without NVML capability
    the function still runs and the measurement honestly reports UNAVAILABLE —
    the lack of a GPU never blocks inference and never invents joules.
    """
    t0 = time.perf_counter()
    if not state.can_measure or state._meter_cls is None:
        result = fn(*args, **kwargs)
        wall = time.perf_counter() - t0
        return result, EnergyMeasurement(
            state=STATE_UNAVAILABLE,
            measured_joules=None,
            measurement_mode=None,
            wall_seconds=round(wall, 6),
            detail=state.capability["detail"] or "NVML capability absent",
        )

    meter = state._meter_cls(device_index=0)
    meter.start()
    try:
        result = fn(*args, **kwargs)
    finally:
        reading = meter.stop()
    wall = time.perf_counter() - t0

    mode = reading.get("mode", "unmeasured")
    if mode == "unmeasured" or reading.get("joules") is None:
        em = EnergyMeasurement(
            state=STATE_UNAVAILABLE,
            measured_joules=None,
            measurement_mode=None,
            wall_seconds=round(wall, 6),
            detail="meter engaged but produced no fresh supported counter delta "
            "(mode=%s)" % mode,
        )
    else:
        em = EnergyMeasurement(
            state=STATE_MEASURED,
            measured_joules=float(reading["joules"]),
            measurement_mode=mode,  # measured-energy | measured-power-integral
            wall_seconds=round(wall, 6),
            detail="real NVML delta via %s" % mode,
        )
    return result, em
