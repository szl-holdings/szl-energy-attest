"""Untrusted store flags cannot suppress checks on a present envelope."""
import base64
import json
import sys

import pytest

from szl_energy_attest.meter_proxy.receipts import ReceiptIssuer, canonical_json
from szl_energy_attest.meter_proxy.rollup import build_daily_rollup
from szl_energy_attest.meter_proxy.verifier import verify_store


@pytest.mark.parametrize("filename,index", [("receipts.jsonl", 0), ("rollups.jsonl", 1)])
@pytest.mark.parametrize("flag", [False, None, 0, "false"])
def test_presence_conflict_is_rejected_even_without_signing_library(
        tmp_path, monkeypatch, filename, index, flag):
    monkeypatch.setitem(sys.modules, "szl_receipt", None)
    issuer = ReceiptIssuer(str(tmp_path))
    row = issuer.issue(model="synthetic", tokens_in=1, tokens_out=1,
                       energy={"state": "UNAVAILABLE", "measured_joules": None},
                       carbon={}, latency_seconds=0.01)
    rollup = build_daily_rollup(issuer.records, store_dir=str(tmp_path),
                               for_date=row["body"]["issued_at"][:10])
    record = (row, rollup)[index]
    record["signature"] = {
        "payload": base64.b64encode(canonical_json(record["body"]).encode()).decode(),
        "signed": True, "signature": "invalid-signature",
    }
    record["signature_present"] = flag
    (tmp_path / filename).write_text(json.dumps(record) + "\n")
    assert verify_store(str(tmp_path))["state"] == "FAIL"


def signed_store(tmp_path):
    signing = pytest.importorskip("szl_receipt")
    private, public = signing.generate_keypair()
    issuer = ReceiptIssuer(str(tmp_path), private_key_pem=private)
    row = issuer.issue(model="synthetic", tokens_in=1, tokens_out=1,
                       energy={"state": "UNAVAILABLE", "measured_joules": None},
                       carbon={}, latency_seconds=0.01)
    rollup = build_daily_rollup(issuer.records, store_dir=str(tmp_path),
                               for_date=row["body"]["issued_at"][:10],
                               private_key_pem=private)
    assert verify_store(str(tmp_path), public)["state"] == "VERIFIED"
    return row, rollup, public


@pytest.mark.parametrize("filename,index", [("receipts.jsonl", 0), ("rollups.jsonl", 1)])
@pytest.mark.parametrize("flag", [False, None, 0, "false"])
def test_present_signature_cannot_be_hidden_by_record_flag(tmp_path, filename, index, flag):
    row, rollup, public = signed_store(tmp_path)
    record = (row, rollup)[index]
    record["signature_present"] = flag
    record["signature"]["signature"] = "invalid-signature"
    (tmp_path / filename).write_text(json.dumps(record) + "\n")
    result = verify_store(str(tmp_path), public)
    assert result["state"] == "FAIL", result


@pytest.mark.parametrize("filename,index", [("receipts.jsonl", 0), ("rollups.jsonl", 1)])
def test_deleted_presence_flag_cannot_hide_existing_signature(tmp_path, filename, index):
    row, rollup, public = signed_store(tmp_path)
    record = (row, rollup)[index]
    del record["signature_present"]
    record["signature"]["signature"] = "invalid-signature"
    (tmp_path / filename).write_text(json.dumps(record) + "\n")
    assert verify_store(str(tmp_path), public)["state"] == "FAIL"


def test_genuine_unsigned_envelopes_remain_unsigned_honest(tmp_path):
    pytest.importorskip("szl_receipt")
    issuer = ReceiptIssuer(str(tmp_path))
    issuer.issue(model="synthetic", tokens_in=1, tokens_out=1,
                 energy={"state": "UNAVAILABLE", "measured_joules": None},
                 carbon={}, latency_seconds=0.01)
    result = verify_store(str(tmp_path))
    assert result["state"] == "VERIFIED", result
    assert result["unsigned_honest"] == 1
    assert result["signed_verified"] == 0
