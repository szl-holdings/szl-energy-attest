"""A valid envelope authenticates only its own exact rollup body."""
import base64
import json
import sys

import pytest

from szl_energy_attest.meter_proxy.receipts import ReceiptIssuer, canonical_json, digest_body
from szl_energy_attest.meter_proxy.rollup import build_daily_rollup
from szl_energy_attest.meter_proxy.verifier import verify_store


def make_rollup(tmp_path, private_key=None):
    issuer = ReceiptIssuer(str(tmp_path), private_key_pem=private_key)
    row = issuer.issue(model="fixture", tokens_in=1, tokens_out=2,
                       energy={"state": "MEASURED", "measured_joules": 5},
                       carbon={}, latency_seconds=0.01)
    rollup = build_daily_rollup(issuer.records, store_dir=str(tmp_path),
                               for_date=row["body"]["issued_at"][:10],
                               private_key_pem=private_key)
    return rollup


def save_rollup(tmp_path, rollup):
    (tmp_path / "rollups.jsonl").write_text(json.dumps(rollup) + "\n")


@pytest.mark.parametrize("envelope", [
    {"payload": base64.b64encode(b'{"unrelated":true}').decode(), "signed": False},
    {"payload": "", "signed": False},
    {"payload": "%%%", "signed": False},
    {"signed": False}, [], "envelope", None,
])
def test_invalid_rollup_payload_fails_without_signing_dependency(tmp_path, monkeypatch, envelope):
    monkeypatch.setitem(sys.modules, "szl_receipt", None)
    rollup = make_rollup(tmp_path)
    rollup["signature"] = envelope
    rollup["signature_present"] = True
    save_rollup(tmp_path, rollup)
    result = verify_store(str(tmp_path))
    assert result["state"] == "FAIL", result
    assert any("rollup 0 envelope" in detail for detail in result["details"])


def test_signature_for_original_rollup_cannot_authenticate_rehashed_body(tmp_path):
    signing = pytest.importorskip("szl_receipt")
    private, public = signing.generate_keypair()
    rollup = make_rollup(tmp_path, private)
    assert verify_store(str(tmp_path), public)["state"] == "VERIFIED"
    rollup["body"]["measured_joules_sum"] = 5000
    rollup["digest"] = digest_body(rollup["body"])
    # Retain the genuine signature for the old body. The hash chain is intact,
    # but it does not bind this changed body to that signed envelope.
    save_rollup(tmp_path, rollup)
    result = verify_store(str(tmp_path), public)
    assert result["state"] == "FAIL", result
    assert result["rollups_checked"] == 0


def test_matching_unsigned_rollup_payload_preserves_structural_verification(tmp_path):
    rollup = make_rollup(tmp_path)
    rollup["signature"] = {"payload": base64.b64encode(
        canonical_json(rollup["body"]).encode()).decode(), "signed": False}
    rollup["signature_present"] = True
    save_rollup(tmp_path, rollup)
    assert verify_store(str(tmp_path))["state"] == "VERIFIED"


def test_honestly_absent_signature_still_verifies_without_signing_dependency(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "szl_receipt", None)
    rollup = make_rollup(tmp_path)
    assert rollup["signature"] is None and rollup["signature_present"] is False
    assert verify_store(str(tmp_path))["state"] == "VERIFIED"
