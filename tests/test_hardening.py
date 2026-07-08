# SPDX-License-Identifier: Apache-2.0
"""Regression tests for szl_energy_attest hardening + upgrades (Upgrade3).

Each test maps to a stress case / fixed bug / new upgrade. All run offline on CPU
with honest UNAVAILABLE labels. Run: python -m pytest tests/ -q
"""
import copy
import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from szl_energy_attest import (  # noqa: E402
    build_receipt, verify_chain, verify_receipt_offline, compute_gco2,
    sign_chain, verify_signature, sha256_canon,
    GENESIS_PREV, LABEL_MEASURED, LABEL_UNAVAILABLE, LABEL_UNSIGNED, LABEL_SIGNED,
)


# ---------------------------------------------------------------------------
# BUG: NaN/inf measured_joules, price, gco2 stored verbatim -> un-attestable.
# ---------------------------------------------------------------------------
def test_nan_joules_with_measured_label_dropped():
    r = build_receipt(tokens=10, node="n", measured_joules=float("nan"),
                      label=LABEL_MEASURED, prev=GENESIS_PREV)
    assert r["measured_joules"] is None
    json.dumps(r, allow_nan=False)  # must not raise


def test_inf_price_dropped():
    r = build_receipt(tokens=10, node="n", price_per_mwh=float("inf"),
                      prev=GENESIS_PREV)
    p = r["price_per_mwh"]
    assert p is None or math.isfinite(p)


def test_nan_gco2_dropped():
    r = build_receipt(tokens=10, node="n", gco2=float("nan"),
                      label=LABEL_MEASURED, measured_joules=5.0, prev=GENESIS_PREV)
    g = r["gCO2"]
    assert g is None or math.isfinite(g)


def test_canon_rejects_non_finite():
    with pytest.raises(ValueError):
        sha256_canon({"x": float("nan")})


# ---------------------------------------------------------------------------
# Honesty invariant: non-MEASURED label cannot carry a joule.
# ---------------------------------------------------------------------------
def test_non_measured_label_forces_null_joules():
    r = build_receipt(tokens=10, node="n", measured_joules=42.0,
                      label=LABEL_UNAVAILABLE, prev=GENESIS_PREV)
    assert r["measured_joules"] is None


def test_negative_or_zero_joules_dropped_even_if_measured():
    r0 = build_receipt(tokens=10, node="n", measured_joules=-5.0,
                       label=LABEL_MEASURED, prev=GENESIS_PREV)
    r1 = build_receipt(tokens=10, node="n", measured_joules=0.0,
                       label=LABEL_MEASURED, prev=GENESIS_PREV)
    assert r0["measured_joules"] is None
    assert r1["measured_joules"] is None


# ---------------------------------------------------------------------------
# BUG: verify_chain crashed (KeyError) on a malformed/missing-field receipt.
# ---------------------------------------------------------------------------
def test_verify_chain_graceful_on_missing_field():
    r = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    del r["note"]
    ok, _, brk = verify_chain([r])  # must not raise
    assert ok is False and brk == 0


def test_verify_chain_graceful_on_non_dict():
    ok, _, brk = verify_chain(["not a dict"])
    assert ok is False and brk == 0


# ---------------------------------------------------------------------------
# Tamper at every body field position + chain fields + reorder.
# ---------------------------------------------------------------------------
def test_tamper_every_body_field_caught():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    r1 = build_receipt(tokens=2, node="b", prev=r0["digest"])
    body_fields = ["schema", "measured_joules", "label", "tokens", "node",
                   "price_per_mwh", "gCO2", "gCO2_label", "decision", "note",
                   "lambda", "sovereign"]
    for f in body_fields:
        chain = copy.deepcopy([r0, r1])
        orig = chain[1][f]
        chain[1][f] = ("ZZ" if not isinstance(orig, (int, float)) else (orig or 0) + 7)
        ok, _, brk = verify_chain(chain)
        assert ok is False and brk == 1, f"tamper on {f} not caught"


def test_tamper_chain_fields_caught():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    r1 = build_receipt(tokens=2, node="b", prev=r0["digest"])
    for f in ("prev", "payload_digest", "digest"):
        chain = copy.deepcopy([r0, r1])
        chain[1][f] = "sha3-256:" + "f" * 64
        ok, _, _ = verify_chain(chain)
        assert ok is False, f"tamper on {f} not caught"


def test_reorder_caught():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    r1 = build_receipt(tokens=2, node="b", prev=r0["digest"])
    ok, _, _ = verify_chain([r1, r0])
    assert ok is False


# ---------------------------------------------------------------------------
# UPGRADE 1 — honest gCO2.
# ---------------------------------------------------------------------------
def test_compute_gco2_real():
    g, lab = compute_gco2(3_600_000.0, LABEL_MEASURED, 400.0)
    assert lab == LABEL_MEASURED and abs(g - 400.0) < 1e-9


def test_compute_gco2_null_without_intensity():
    g, lab = compute_gco2(3_600_000.0, LABEL_MEASURED, None)
    assert g is None


def test_compute_gco2_null_without_measured_energy():
    g, lab = compute_gco2(None, LABEL_UNAVAILABLE, 400.0)
    assert g is None


def test_build_receipt_gco2_only_with_measured_and_intensity():
    # MEASURED joules + intensity -> real gCO2
    r = build_receipt(tokens=1000, node="gpu0", measured_joules=3_600_000.0,
                      label=LABEL_MEASURED, grid_intensity_gco2_per_kwh=400.0,
                      prev=GENESIS_PREV)
    assert r["gCO2"] is not None and r["gCO2_label"] == LABEL_MEASURED
    # No intensity -> null carbon
    r2 = build_receipt(tokens=1000, node="cpu", grid_intensity_gco2_per_kwh=400.0,
                       prev=GENESIS_PREV)  # UNAVAILABLE energy
    assert r2["gCO2"] is None


# ---------------------------------------------------------------------------
# UPGRADE 2 — standalone offline verifier (zero SZL deps).
# ---------------------------------------------------------------------------
def test_offline_verifier_good_chain():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    r1 = build_receipt(tokens=2, node="b", prev=r0["digest"])
    res = verify_receipt_offline([r0, r1])
    assert res["ok"] and res["honesty_ok"] and res["first_break_index"] == -1


def test_offline_verifier_accepts_json_string_and_envelope():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    res = verify_receipt_offline(json.dumps(r0))  # single receipt as JSON string
    assert res["ok"]
    env = {"receipts": [r0]}
    assert verify_receipt_offline(json.dumps(env))["ok"]


def test_offline_verifier_catches_tamper_and_reorder():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    r1 = build_receipt(tokens=2, node="b", prev=r0["digest"])
    bad = copy.deepcopy([r0, r1])
    bad[0]["tokens"] = 999
    assert verify_receipt_offline(bad)["ok"] is False
    assert verify_receipt_offline([r1, r0])["ok"] is False


def test_offline_verifier_uses_only_stdlib():
    """The function body imports only hashlib/json/math + base/builtins — proven
    by executing its extracted source in a namespace with no szl_* available."""
    import inspect
    import szl_energy_attest as pkg
    src = inspect.getsource(pkg.verify_receipt_offline)
    ns = {}
    exec(compile(src, "<standalone>", "exec"), ns)  # noqa: S102 - intentional
    fn = ns["verify_receipt_offline"]
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    r1 = build_receipt(tokens=2, node="b", prev=r0["digest"])
    assert fn([r0, r1])["ok"] is True


def test_offline_verifier_flags_honesty_violation():
    """Hand-craft a receipt whose body says label!=MEASURED but joules!=null and
    is internally hash-consistent: chain links but honesty_ok must be False."""
    body = {
        "schema": "szl_energy_attest/receipt@1",
        "measured_joules": 123.0, "label": "UNAVAILABLE",
        "tokens": 1, "node": "x", "price_per_mwh": None,
        "gCO2": None, "gCO2_label": "UNAVAILABLE_NO_GRID_INTENSITY",
        "decision": "no_choice", "note": "", "lambda": "Conjecture 1",
        "sovereign": False,
    }
    pd = sha256_canon(body)
    dg = sha256_canon({"prev": GENESIS_PREV, "payload_digest": pd})
    r = dict(body, prev=GENESIS_PREV, payload_digest=pd, digest=dg)
    res = verify_receipt_offline([r])
    assert res["ok"] is True          # hashes are internally consistent
    assert res["honesty_ok"] is False  # but the honesty invariant is violated


# ---------------------------------------------------------------------------
# UPGRADE 3 — DSSE/cosign detached signature hook (UNSIGNED when no key).
# ---------------------------------------------------------------------------
def test_sign_chain_unsigned_without_key():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    env = sign_chain([r0])
    assert env["signature_label"] == LABEL_UNSIGNED
    assert env["signatures"] == []
    v = verify_signature([r0], env)
    assert v["signed"] is False and v["valid"] is True


def test_sign_chain_hmac_with_key_roundtrip():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    r1 = build_receipt(tokens=2, node="b", prev=r0["digest"])
    env = sign_chain([r0, r1], key=b"topsecret")
    assert env["signature_label"] == LABEL_SIGNED
    assert env["signatures"][0]["backend"] == "hmac-sha256"
    good = verify_signature([r0, r1], env, key=b"topsecret")
    assert good["signed"] and good["valid"]
    bad = verify_signature([r0, r1], env, key=b"wrong")
    assert bad["signed"] and bad["valid"] is False


def test_sign_chain_env_key(monkeypatch):
    monkeypatch.setenv("SZL_ATTEST_HMAC_KEY", "fromenv")
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    env = sign_chain([r0])
    assert env["signature_label"] == LABEL_SIGNED
    assert verify_signature([r0], env)["valid"] is True


def test_signature_is_detached_chain_unchanged():
    r0 = build_receipt(tokens=1, node="a", prev=GENESIS_PREV)
    before = copy.deepcopy(r0)
    sign_chain([r0], key=b"k")
    assert r0 == before  # signing must not mutate receipts
    assert verify_chain([r0])[0] is True


# ---------------------------------------------------------------------------
# UPGRADE 4 — cross-algorithm verification parity.
# A chain minted under SHA3-256 on a metering node (szl_energy_core active) must
# verify on a CPU-only auditor box whose active canon is the SHA-256 fallback,
# and vice-versa. verify_chain is now algorithm-agnostic (parity with
# verify_receipt_offline): it re-hashes each receipt under the algorithm the
# receipt itself declares, so provenance is checkable by ANYONE regardless of
# which canon source minted the chain. These receipts are hand-minted with
# hashlib directly (the exact SPEC.md §2 / szl_energy_core.sha3_canon formula),
# independent of whichever canon source is active on this test box.
# ---------------------------------------------------------------------------
import hashlib as _hashlib  # noqa: E402


def _sha3_canon(obj):
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()
    return "sha3-256:" + _hashlib.sha3_256(blob).hexdigest()


def _mint_sha3_chain(specs):
    """Hand-mint a receipt chain using SHA3-256 canonicalization directly, so the
    test does not depend on whichever canon source is active on this box."""
    chain = []
    prev = GENESIS_PREV
    for tokens, node in specs:
        body = {
            "schema": "szl_energy_attest/receipt@1",
            "measured_joules": None,
            "label": LABEL_UNAVAILABLE,
            "tokens": tokens,
            "node": node,
            "price_per_mwh": None,
            "gCO2": None,
            "gCO2_label": "UNAVAILABLE_NO_GRID_INTENSITY",
            "decision": "no_choice",
            "note": "",
            "lambda": "Conjecture 1 (advisory; trust never 100%)",
            "sovereign": False,
        }
        pd = _sha3_canon(body)
        dg = _sha3_canon({"prev": prev, "payload_digest": pd})
        chain.append(dict(body, prev=prev, payload_digest=pd, digest=dg))
        prev = dg
    return chain


def test_verify_chain_accepts_foreign_sha3_algorithm():
    chain = _mint_sha3_chain([(1, "a"), (2, "b")])
    # These really are SHA3-256 digests, distinct from the active fallback's algo.
    assert all(r["digest"].startswith("sha3-256:") for r in chain)
    ok, length, brk = verify_chain(chain)
    assert ok is True and length == 2 and brk == -1


def test_verify_chain_and_offline_agree_on_sha3_chain():
    chain = _mint_sha3_chain([(3, "x"), (4, "y"), (5, "z")])
    ok, _, _ = verify_chain(chain)
    off = verify_receipt_offline(chain)
    assert ok is True and off["ok"] is True and off["honesty_ok"] is True


def test_verify_chain_catches_tamper_in_sha3_chain():
    chain = _mint_sha3_chain([(1, "a"), (2, "b")])
    chain[1]["tokens"] = 999  # tamper body without re-hashing under sha3-256
    ok, _, brk = verify_chain(chain)
    assert ok is False and brk == 1


def test_verify_chain_catches_reorder_in_sha3_chain():
    chain = _mint_sha3_chain([(1, "a"), (2, "b")])
    ok, _, _ = verify_chain([chain[1], chain[0]])
    assert ok is False


def test_verify_chain_rejects_unknown_algorithm_prefix():
    chain = _mint_sha3_chain([(1, "a")])
    # Forge an unsupported algorithm prefix: verify must fail closed, not crash.
    chain[0]["digest"] = "sha42-999:" + chain[0]["digest"].split(":", 1)[1]
    ok, _, brk = verify_chain(chain)
    assert ok is False and brk == 0


if __name__ == "__main__":
    import pytest as _p
    raise SystemExit(_p.main([__file__, "-q"]))
