# SPDX-License-Identifier: Apache-2.0
"""Offline tests for szl_energy_attest. Run: python -m pytest tests/ -q
or simply: python tests/test_attest.py (no pytest needed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from szl_energy_attest import (build_receipt, verify_chain, measure_joules,
                               nvml_available, GENESIS_PREV, LABEL_MEASURED,
                               LABEL_UNAVAILABLE)


def test_cpu_energy_is_null_and_unavailable():
    """On a box with no GPU, joules must be None and label UNAVAILABLE."""
    if not nvml_available():
        j, lab = measure_joules()
        assert j is None
        assert lab == LABEL_UNAVAILABLE


def test_non_measured_label_forces_null_joules():
    """Honesty invariant: a non-MEASURED label can never carry a joule number."""
    r = build_receipt(tokens=10, node="n", measured_joules=42.0,
                      label=LABEL_UNAVAILABLE, prev=GENESIS_PREV)
    assert r["measured_joules"] is None  # 42.0 must be dropped


def test_chain_verifies():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    r1 = build_receipt(tokens=2, node="b", prev=r0["digest"])
    ok, length, brk = verify_chain([r0, r1])
    assert ok and length == 2 and brk == -1


def test_tamper_breaks_chain():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    r1 = build_receipt(tokens=2, node="b", prev=r0["digest"])
    r0["tokens"] = 999  # tamper the body without re-hashing
    ok, _, brk = verify_chain([r0, r1])
    assert not ok and brk == 0


def test_reorder_breaks_chain():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    r1 = build_receipt(tokens=2, node="b", prev=r0["digest"])
    ok, _, brk = verify_chain([r1, r0])  # wrong order
    assert not ok


def test_measured_path_labels_correctly():
    """When a real reading is handed in with MEASURED, it is carried verbatim."""
    j, lab = measure_joules(reading=123.456, label=LABEL_MEASURED)
    assert j == 123.456 and lab == LABEL_MEASURED
    r = build_receipt(tokens=5, node="gpu0", measured_joules=j, label=lab,
                      prev=GENESIS_PREV)
    assert r["measured_joules"] == 123.456 and r["label"] == LABEL_MEASURED
    ok, _, _ = verify_chain([r])
    assert ok


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed")
