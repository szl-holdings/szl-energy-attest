# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Tests for the per-inference joule-receipt vertical (energy_meter_proxy)."""
import json
import os

import pytest

from energy_meter_proxy import GENESIS_PREV, PREDICATE_TYPE, SPEC_VERSION
from energy_meter_proxy.grid import fetch_carbon_context, LABEL_UNAVAILABLE
from energy_meter_proxy.meter import EnergyState, measure_inference_energy
from energy_meter_proxy.receipts import ReceiptIssuer, canonical_json, digest_body
from energy_meter_proxy.rollup import build_daily_rollup
from energy_meter_proxy.verifier import verify_store


def _energy_unavailable():
    return {
        "state": "UNAVAILABLE",
        "measured_joules": None,
        "estimated_joules": None,
        "measurement_mode": None,
        "detail": "test: no NVML capability",
    }


def _energy_measured():
    return {
        "state": "MEASURED",
        "measured_joules": 12.5,
        "estimated_joules": None,
        "measurement_mode": "measured-energy",
        "detail": "test fixture",
    }


def _carbon_unavail():
    return {"label": LABEL_UNAVAILABLE, "carbon_intensity_gco2_per_kwh": None,
            "reason": "test"}


def test_meter_honest_unavailable_on_cpu_host():
    st = EnergyState()
    # In the CI/sandbox the meter must NOT invent joules.
    result, em = measure_inference_energy(st, lambda: "ok")
    assert result == "ok"
    if not st.can_measure:  # sandbox expectation
        assert em.state == "UNAVAILABLE"
        assert em.measured_joules is None
    else:  # pragma: no cover - GPU host path
        assert em.state in ("MEASURED", "UNAVAILABLE")
    assert em.wall_seconds is not None


def test_carbon_placeholder_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("SZL_GRID_API_KEY", raising=False)
    monkeypatch.delenv("SZL_GRID_PROVIDER", raising=False)
    block = fetch_carbon_context()
    assert block["label"] == LABEL_UNAVAILABLE
    assert block["carbon_intensity_gco2_per_kwh"] is None


def test_receipt_chain_and_unsigned_honest(tmp_path):
    issuer = ReceiptIssuer(str(tmp_path))
    r0 = issuer.issue(model="m", tokens_in=1, tokens_out=2,
                      energy=_energy_unavailable(), carbon=_carbon_unavail(),
                      latency_seconds=0.01)
    r1 = issuer.issue(model="m", tokens_in=3, tokens_out=4,
                      energy=_energy_unavailable(), carbon=_carbon_unavail(),
                      latency_seconds=0.02)
    assert r0["body"]["spec_version"] == SPEC_VERSION
    assert r0["body"]["predicate_type"] == PREDICATE_TYPE
    assert r0["body"]["prev"] == GENESIS_PREV
    assert r1["body"]["prev"] == r0["digest"]
    assert digest_body(r0["body"]) == r0["digest"]
    # UNSIGNED-honest: envelope exists (szl-receipt installed) with signed=False
    # when no key; or honest absence if szl-receipt missing.
    if r0["signature"] is not None:
        assert r0["signature"]["signed"] is False


def test_signed_receipts_and_rollups_verify(tmp_path):
    szl_receipt = pytest.importorskip("szl_receipt")
    priv, pub = szl_receipt.generate_keypair()
    store = str(tmp_path)
    issuer = ReceiptIssuer(store, private_key_pem=priv)
    issuer.issue(model="m1", tokens_in=10, tokens_out=20,
                 energy=_energy_measured(), carbon=_carbon_unavail(),
                 latency_seconds=0.01)
    issuer.issue(model="m2", tokens_in=5, tokens_out=6,
                 energy=_energy_unavailable(), carbon=_carbon_unavail(),
                 latency_seconds=0.02)
    build_daily_rollup(issuer.records, store_dir=store, private_key_pem=priv)

    res = verify_store(store, pub)
    assert res["state"] == "VERIFIED", res
    assert res["receipts_checked"] == 2
    assert res["signed_verified"] >= 2  # per-inference receipts (+ rollup)

    roll = json.loads(open(os.path.join(store, "rollups.jsonl")).read().strip())
    body = roll["body"]
    assert body["counts"] == {"measured": 1, "estimated": 0, "unavailable": 1}
    assert body["measured_joules_sum"] == 12.5
    assert body["measured_kwh_sum"] == pytest.approx(12.5 / 3_600_000.0)


def test_estimated_never_blends_into_measured(tmp_path):
    store = str(tmp_path)
    issuer = ReceiptIssuer(store)
    est = {
        "state": "ESTIMATED",
        "measured_joules": None,
        "estimated_joules": 0.42,
        "measurement_mode": None,
        "detail": "synthetic",
    }
    issuer.issue(model="m", tokens_in=1, tokens_out=1, energy=est,
                 carbon=_carbon_unavail(), latency_seconds=0.01,
                 synthetic=True, provenance="demo-synthetic")
    roll = build_daily_rollup(issuer.records, store_dir=store)
    assert roll["body"]["measured_joules_sum"] is None
    assert roll["body"]["measured_joules_label"] == "UNAVAILABLE-NO-MEASURED-MEMBERS"
    assert roll["body"]["estimated_joules_sum"] == 0.42


def test_tamper_breaks_chain_and_fails(tmp_path):
    szl_receipt = pytest.importorskip("szl_receipt")
    priv, pub = szl_receipt.generate_keypair()
    store = str(tmp_path)
    issuer = ReceiptIssuer(store, private_key_pem=priv)
    issuer.issue(model="m", tokens_in=1, tokens_out=2,
                 energy=_energy_unavailable(), carbon=_carbon_unavail(),
                 latency_seconds=0.01)
    path = os.path.join(store, "receipts.jsonl")
    lines = open(path).readlines()
    rec = json.loads(lines[0])
    rec["body"]["tokens_out"] = 999
    lines[0] = json.dumps(rec, sort_keys=True) + "\n"
    open(path, "w").writelines(lines)
    res = verify_store(store, pub)
    assert res["state"] == "FAIL"
    assert any("digest mismatch" in d for d in res["details"])


def test_empty_store_is_incomplete_never_pass(tmp_path):
    res = verify_store(str(tmp_path), None)
    assert res["state"] == "INCOMPLETE"


def test_canonical_and_digest_deterministic():
    body = {"b": 1, "a": [2, 3], "c": None}
    assert canonical_json(body) == '{"a":[2,3],"b":1,"c":null}'
    assert digest_body(body) == digest_body(dict(reversed(list(body.items()))))
