"""Regression tests for szl_energy_core hardening (Upgrade3: harden energy).

Every test here corresponds to a stress-test case or a bug fixed during the
hardening pass. They all run on CPU (no GPU/NVML) and assert the honesty
invariant: NO code path emits a numeric joule / cost / carbon that is not real.
"""
from __future__ import annotations

import math
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from szl_energy_core import (  # noqa: E402
    CheapestWattLedger,
    GENESIS_PREV,
    cheapest_watt_choice,
    gco2_from_joules,
    sha3_canon,
)


def _m(name, j, tok, price=100.0):
    return {"name": name, "power_w": 40.0, "tokens": tok, "price_per_mwh": price,
            "joules_measured": j, "joules_label": "MEASURED"}


# ---------------------------------------------------------------------------
# BUG: NaN / inf price leaked into grid price and produced a NaN cost_per_token.
# ---------------------------------------------------------------------------
def test_nan_price_never_becomes_grid_price():
    nodes = [_m("a", 100.0, 1000), _m("b", 200.0, 1000)]
    nodes[0]["price_per_mwh"] = float("nan")
    d = cheapest_watt_choice(nodes)["decision"]
    grid = d["grid_price_per_mwh"]
    assert grid is None or math.isfinite(grid)
    for c in d["candidates"]:
        cpt = c["cost_per_token"]
        assert cpt is None or math.isfinite(cpt)


def test_inf_price_never_becomes_grid_price():
    nodes = [_m("a", 100.0, 1000, float("inf")), _m("b", 200.0, 1000, float("inf"))]
    d = cheapest_watt_choice(nodes)["decision"]
    grid = d["grid_price_per_mwh"]
    assert grid is None or math.isfinite(grid)


# ---------------------------------------------------------------------------
# BUG: a NaN/inf must never silently enter a digest (allow_nan=False).
# ---------------------------------------------------------------------------
def test_sha3_canon_rejects_non_finite():
    import pytest
    with pytest.raises(ValueError):
        sha3_canon({"x": float("nan")})
    with pytest.raises(ValueError):
        sha3_canon({"x": float("inf")})


def test_receipt_is_strict_json_serializable_under_nan_inputs():
    import json
    nodes = [_m("a", float("nan"), 1000), _m("b", 200.0, 1000, float("inf"))]
    receipt = cheapest_watt_choice(nodes)
    # allow_nan=False would raise if any NaN/inf survived into the receipt.
    json.dumps(receipt, allow_nan=False)


# ---------------------------------------------------------------------------
# NaN / negative / zero joules must never be ranked as MEASURED intensity.
# ---------------------------------------------------------------------------
def test_nan_joules_not_ranked():
    nodes = [_m("a", float("nan"), 1000), _m("b", 200.0, 1000)]
    d = cheapest_watt_choice(nodes)["decision"]
    a = [c for c in d["candidates"] if c["node"] == "a"][0]
    assert a["intensity_label"] == "UNKNOWN"
    assert a["joules_per_token"] is None
    # only one comparable -> no_choice
    assert d["decision"] == "no_choice"


def test_negative_joules_not_ranked():
    nodes = [_m("a", -100.0, 1000), _m("b", 200.0, 1000)]
    d = cheapest_watt_choice(nodes)["decision"]
    a = [c for c in d["candidates"] if c["node"] == "a"][0]
    assert a["intensity_label"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Ties / single node / zero tokens / neg-zero power / missing price.
# ---------------------------------------------------------------------------
def test_ties_are_deterministic_and_zero_delta():
    nodes = [_m("a", 100.0, 1000), _m("b", 100.0, 1000)]
    d = cheapest_watt_choice(nodes)["decision"]
    assert d["decision"] == "placed"
    assert d["saving"]["delta_cost_per_token"] == 0.0


def test_single_node_no_choice():
    d = cheapest_watt_choice([_m("solo", 100.0, 1000)])["decision"]
    assert d["decision"] == "no_choice"


def test_zero_tokens_div_by_zero_safe():
    nodes = [_m("a", 100.0, 0), _m("b", 50.0, 0)]
    d = cheapest_watt_choice(nodes)["decision"]
    assert d["decision"] == "no_choice"
    for c in d["candidates"]:
        assert c["joules_per_token"] is None


def test_negative_and_zero_power_safe():
    nodes = [_m("a", 100.0, 1000), _m("b", 100.0, 1000)]
    nodes[0]["power_w"] = -50.0
    nodes[1]["power_w"] = 0.0
    d = cheapest_watt_choice(nodes)["decision"]
    assert d["decision"] == "placed"  # power is metadata, intensity is from joules


def test_missing_price_yields_estimate_no_fabricated_cost():
    nodes = [_m("a", 100.0, 1000, None), _m("b", 200.0, 1000, None)]
    d = cheapest_watt_choice(nodes)["decision"]
    assert d["saving_label"] == "ESTIMATE"
    assert all(c["cost_per_token"] is None for c in d["candidates"])


def test_zero_price_no_crash():
    nodes = [_m("a", 100.0, 1000, 0.0), _m("b", 200.0, 1000, 0.0)]
    d = cheapest_watt_choice(nodes)["decision"]
    assert d["decision"] in ("placed", "no_choice")


# ---------------------------------------------------------------------------
# Very long chain (10k) performance + verification.
# ---------------------------------------------------------------------------
def test_long_chain_10k_verifies():
    led = CheapestWattLedger()
    two = [_m("a", 100.0, 1000), _m("b", 200.0, 1000)]
    for _ in range(10_000):
        led.record(two)
    ok, length, brk = led.verify()
    assert ok and length == 10_000 and brk == -1


# ---------------------------------------------------------------------------
# Concurrent emission: thread-safety; chain still verifies and length is exact.
# ---------------------------------------------------------------------------
def test_concurrent_emission_thread_safe():
    led = CheapestWattLedger()
    two = [_m("a", 100.0, 1000), _m("b", 200.0, 1000)]
    errs = []

    def worker():
        try:
            for _ in range(300):
                led.record(two)
        except Exception as e:  # pragma: no cover
            errs.append(repr(e))

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs
    ok, length, brk = led.verify()
    assert ok and length == 2400 and brk == -1


# ---------------------------------------------------------------------------
# Tamper at EVERY field position + chain-level digests must be caught.
# ---------------------------------------------------------------------------
def test_tamper_every_field_position_caught():
    import copy
    led = CheapestWattLedger()
    two = [_m("a", 100.0, 1000), _m("b", 200.0, 1000)]
    led.record(two)
    led.record(two)
    led.record(two)
    for k in list(led._records[1]["decision"].keys()):
        snap = copy.deepcopy(led._records)
        orig = led._records[1]["decision"][k]
        led._records[1]["decision"][k] = (
            "ZZZ" if not isinstance(orig, (int, float)) else (orig or 0) + 12345)
        ok, _, brk = led.verify()
        assert ok is False and brk == 1, f"tamper on {k} not caught"
        led._records = snap


def test_tamper_chain_digests_caught():
    two = [_m("a", 100.0, 1000), _m("b", 200.0, 1000)]
    for fld in ("prev_digest", "payload_digest", "entry_digest"):
        led = CheapestWattLedger()
        led.record(two)
        led.record(two)
        led._records[1][fld] = "sha3-256:" + "f" * 64
        ok, _, _ = led.verify()
        assert ok is False, f"tamper on {fld} not caught"


def test_reorder_caught():
    two = [_m("a", 100.0, 1000), _m("b", 200.0, 1000)]
    led = CheapestWattLedger()
    led.record(two)
    led.record(two)
    led.record(two)
    led._records[0], led._records[1] = led._records[1], led._records[0]
    ok, _, _ = led.verify()
    assert ok is False


# ---------------------------------------------------------------------------
# UPGRADE 1 — honest gCO2. Carbon only when joules MEASURED AND real intensity.
# ---------------------------------------------------------------------------
def test_gco2_measured_when_joules_and_intensity_real():
    # 1 kWh = 3.6e6 J ; @ 400 gCO2/kWh -> 400 gCO2
    g, lab = gco2_from_joules(3_600_000.0, "MEASURED", 400.0)
    assert lab == "MEASURED"
    assert abs(g - 400.0) < 1e-9


def test_gco2_null_when_no_intensity():
    g, lab = gco2_from_joules(3_600_000.0, "MEASURED", None)
    assert g is None and lab == "UNAVAILABLE_NO_GRID_INTENSITY"


def test_gco2_null_when_energy_unavailable():
    g, lab = gco2_from_joules(None, "UNAVAILABLE_NO_NVML", 400.0)
    assert g is None and lab == "UNAVAILABLE_NO_NVML"


def test_gco2_never_from_nan_intensity():
    g, lab = gco2_from_joules(3_600_000.0, "MEASURED", float("nan"))
    assert g is None and lab == "UNAVAILABLE_NO_GRID_INTENSITY"


def test_cheapest_watt_gco2_in_receipt_only_for_measured():
    nodes = [_m("a", 3_600_000.0, 1000), _m("b", 7_200_000.0, 1000),
             {"name": "ghost", "power_w": 5.0, "tokens": 99, "price_per_mwh": 100.0,
              "joules_measured": 0.0, "joules_label": "PENDING_EXPORTER"}]
    d = cheapest_watt_choice(nodes, grid_intensity_gco2_per_kwh=400.0)["decision"]
    assert d["grid_intensity_label"] == "MEASURED"
    cands = {c["node"]: c for c in d["candidates"]}
    assert cands["a"]["gCO2"] is not None and cands["a"]["gCO2_label"] == "MEASURED"
    # ghost has no MEASURED joules -> no carbon, ever
    assert cands["ghost"]["gCO2"] is None


def test_cheapest_watt_no_intensity_means_null_carbon():
    nodes = [_m("a", 3_600_000.0, 1000), _m("b", 7_200_000.0, 1000)]
    d = cheapest_watt_choice(nodes)["decision"]  # no intensity supplied
    assert d["grid_intensity_gco2_per_kwh"] is None
    for c in d["candidates"]:
        assert c["gCO2"] is None


# ---------------------------------------------------------------------------
# Fuzz: across many random node sets, NO numeric joule/jpt is ever attached to a
# non-MEASURED intensity, and the whole receipt is always strict-JSON safe.
# ---------------------------------------------------------------------------
def test_fuzz_honesty_invariant():
    import json
    import random
    rnd = random.Random(20260623)
    weird = [float("nan"), float("inf"), float("-inf"), -5.0, 0.0, None,
             "junk", True, 100.0, 1e9]
    for _ in range(500):
        nodes = []
        for k in range(rnd.randint(1, 5)):
            nodes.append({
                "name": f"n{k}",
                "power_w": rnd.choice(weird),
                "tokens": rnd.choice([0, 1, 1000, -10, "x", float("nan")]),
                "price_per_mwh": rnd.choice(weird),
                "joules_measured": rnd.choice(weird),
                "joules_label": rnd.choice(["MEASURED", "PENDING_EXPORTER", "", "NONE"]),
            })
        gi = rnd.choice(weird)
        receipt = cheapest_watt_choice(nodes, grid_intensity_gco2_per_kwh=gi)
        d = receipt["decision"]
        for c in d["candidates"]:
            if c["intensity_label"] != "MEASURED":
                assert c["joules_per_token"] is None
                assert c["cost_per_token"] is None
                assert c["gCO2"] is None
        # Whole receipt must be strict-JSON serializable (no NaN/inf anywhere).
        json.dumps(receipt, allow_nan=False)
