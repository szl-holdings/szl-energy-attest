"""Offline envelope/body binding checks with fresh, ephemeral test keys."""
import json

import pytest

signing = pytest.importorskip("szl_receipt")

from szl_energy_attest.meter_proxy.receipts import ReceiptIssuer, digest_body
from szl_energy_attest.meter_proxy.rollup import build_daily_rollup
from szl_energy_attest.meter_proxy.verifier import verify_store


def signed_store(tmp_path):
    private, public = signing.generate_keypair()
    issuer = ReceiptIssuer(str(tmp_path), private_key_pem=private)
    inference = issuer.issue(
        model="offline-synthetic", tokens_in=1, tokens_out=1,
        energy={"state": "MEASURED", "measured_joules": 1.0},
        carbon={"label": "UNAVAILABLE"}, latency_seconds=0.01,
        synthetic=True, provenance="offline-test",
    )
    rollup = build_daily_rollup(issuer.records, store_dir=str(tmp_path), private_key_pem=private)
    assert rollup["signature"]["signed"] is True
    assert verify_store(str(tmp_path), public)["state"] == "VERIFIED"
    return public, inference, rollup


@pytest.mark.parametrize("field,value", [
    ("measured_joules_sum", 9_000_000_000.0),
    ("receipt_count", 999),
    ("date", "2000-01-01"),
])
def test_signed_rollup_rejects_changed_body_even_with_recomputed_digest(tmp_path, field, value):
    public, _, rollup = signed_store(tmp_path)
    rollup["body"][field] = value
    rollup["digest"] = digest_body(rollup["body"])
    # The untouched envelope still verifies cryptographically, but it signed
    # different body bytes. A valid unrelated signature must not bless this row.
    assert signing.verify_receipt(rollup["signature"], public)[0]
    (tmp_path / "rollups.jsonl").write_text(json.dumps(rollup) + "\n")
    result = verify_store(str(tmp_path), public)
    assert result["state"] == "FAIL"
    assert any("byte-identical" in detail for detail in result["details"])


def test_rollup_rejects_replayed_inference_envelope(tmp_path):
    public, inference, rollup = signed_store(tmp_path)
    rollup["signature"] = inference["signature"]
    assert signing.verify_receipt(rollup["signature"], public)[0]
    (tmp_path / "rollups.jsonl").write_text(json.dumps(rollup) + "\n")
    assert verify_store(str(tmp_path), public)["state"] == "FAIL"


@pytest.mark.parametrize("payload", ["", "%%%", None])
def test_rollup_rejects_missing_or_invalid_payload_without_throwing(tmp_path, payload):
    public, _, rollup = signed_store(tmp_path)
    rollup["signature"]["payload"] = payload
    (tmp_path / "rollups.jsonl").write_text(json.dumps(rollup) + "\n")
    assert verify_store(str(tmp_path), public)["state"] == "FAIL"


def test_unsigned_rollup_keeps_honest_state_but_must_bind_its_body(tmp_path):
    public, _, signed = signed_store(tmp_path)
    unsigned = signing.sign_receipt(signing.Receipt(kind="energy-inference", body=signed["body"]), None)
    signed["signature"] = unsigned
    path = tmp_path / "rollups.jsonl"
    path.write_text(json.dumps(signed) + "\n")
    assert verify_store(str(tmp_path), public)["state"] == "VERIFIED"
    signed["body"]["receipt_count"] = 999
    signed["digest"] = digest_body(signed["body"])
    path.write_text(json.dumps(signed) + "\n")
    assert verify_store(str(tmp_path), public)["state"] == "FAIL"
