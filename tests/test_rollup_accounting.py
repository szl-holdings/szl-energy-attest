"""A valid hash does not prove a rollup's billing arithmetic or membership."""
import json
import sys

import pytest

from szl_energy_attest.meter_proxy.receipts import ReceiptIssuer, digest_body
from szl_energy_attest.meter_proxy.rollup import build_daily_rollup
from szl_energy_attest.meter_proxy.verifier import verify_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    # Exercise accounting independently of the optional signing dependency.
    monkeypatch.setitem(sys.modules, "szl_receipt", None)
    issuer = ReceiptIssuer(str(tmp_path))
    for energy in (
        {"state": "MEASURED", "measured_joules": 5},
        {"state": "ESTIMATED", "estimated_joules": 20},
        {"state": "UNAVAILABLE"},
    ):
        issuer.issue(model="fixture", tokens_in=1, tokens_out=2, energy=energy,
                     carbon={}, latency_seconds=0.01)
    row = build_daily_rollup(issuer.records, store_dir=str(tmp_path))
    return issuer, row


def save(tmp_path, row):
    row["digest"] = digest_body(row["body"])
    (tmp_path / "rollups.jsonl").write_text(json.dumps(row) + "\n")


@pytest.mark.parametrize(("key", "value"), [
    ("receipt_count", 100), ("receipt_count", True),
    ("counts", {"measured": 2, "estimated": 0, "unavailable": 1}),
    ("measured_joules_sum", 5000), ("measured_joules_sum", -5),
    ("measured_joules_label", "MEASURED"),
    ("estimated_joules_sum", 0), ("estimated_joules_label", None),
    ("measured_kwh_sum", 1), ("first_member_digest", "f" * 64),
    ("last_member_digest", None), ("date", "2000-01-01"),
    ("date", "invalid"), ("member_digests", None),
    ("member_digests", "not-a-list"), ("member_digests", [{}]),
])
def test_rehashed_inconsistent_rollup_fails(tmp_path, store, key, value):
    _, row = store
    row["body"][key] = value
    save(tmp_path, row)
    result = verify_store(str(tmp_path))
    assert result["state"] == "FAIL", result
    assert result["rollups_checked"] == 0


@pytest.mark.parametrize("change", ["duplicate", "reverse", "unknown", "missing-field"])
def test_invalid_declared_members_fail(tmp_path, store, change):
    _, row = store
    if change == "duplicate":
        row["body"]["member_digests"].append(row["body"]["member_digests"][0])
    elif change == "reverse":
        row["body"]["member_digests"].reverse()
    elif change == "unknown":
        row["body"]["member_digests"][0] = "0" * 64
    else:
        del row["body"]["counts"]
    save(tmp_path, row)
    assert verify_store(str(tmp_path))["state"] == "FAIL"


def test_valid_split_accounting_and_later_receipts_preserved(tmp_path, store):
    issuer, row = store
    body = row["body"]
    assert body["measured_joules_sum"] == 5
    assert body["estimated_joules_sum"] == 20
    assert body["measured_kwh_sum"] == 5 / 3_600_000
    assert body["counts"] == {"measured": 1, "estimated": 1, "unavailable": 1}
    assert verify_store(str(tmp_path))["state"] == "VERIFIED"
    issuer.issue(model="later", tokens_in=1, tokens_out=2,
                 energy={"state": "MEASURED", "measured_joules": 7},
                 carbon={}, latency_seconds=0.01)
    # A sealed rollup represents its declared snapshot, not later receipts.
    assert verify_store(str(tmp_path))["state"] == "VERIFIED"


@pytest.mark.parametrize("energy", [
    {"state": "MEASURED", "measured_joules": True},
    {"state": "MEASURED", "measured_joules": -1},
    {"state": "MEASURED"},
    {"state": "ESTIMATED", "estimated_joules": "20"},
    {"state": "unknown"},
])
def test_invalid_member_cannot_be_billed(tmp_path, energy, monkeypatch):
    monkeypatch.setitem(sys.modules, "szl_receipt", None)
    issuer = ReceiptIssuer(str(tmp_path))
    issuer.issue(model="invalid", tokens_in=1, tokens_out=2, energy=energy,
                 carbon={}, latency_seconds=0.01)
    with pytest.raises(ValueError):
        build_daily_rollup(issuer.records, store_dir=str(tmp_path))
    assert not (tmp_path / "rollups.jsonl").exists()


def test_overflowed_sum_cannot_be_billed(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "szl_receipt", None)
    issuer = ReceiptIssuer(str(tmp_path))
    for _ in range(2):
        issuer.issue(model="large", tokens_in=1, tokens_out=2,
                     energy={"state": "MEASURED", "measured_joules": 1e308},
                     carbon={}, latency_seconds=0.01)
    with pytest.raises(ValueError):
        build_daily_rollup(issuer.records, store_dir=str(tmp_path))
    assert not (tmp_path / "rollups.jsonl").exists()


def test_historical_float_summation_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "szl_receipt", None)
    issuer = ReceiptIssuer(str(tmp_path))
    values = [1e16, 1.0, 1.0]
    for value in values:
        issuer.issue(model="float-history", tokens_in=1, tokens_out=2,
                     energy={"state": "MEASURED", "measured_joules": value},
                     carbon={}, latency_seconds=0.01)
    row = build_daily_rollup(issuer.records, store_dir=str(tmp_path))
    # The old generator uses built-in sum, whose float algorithm changed in
    # Python 3.12. In that runtime, repeated += loses the two one-joule members.
    historical_total = sum(value for value in values)
    assert row["body"]["measured_joules_sum"] == historical_total
    row["body"]["measured_joules_sum"] = historical_total
    row["body"]["measured_kwh_sum"] = historical_total / 3_600_000.0
    save(tmp_path, row)
    assert verify_store(str(tmp_path))["state"] == "VERIFIED"


@pytest.mark.parametrize("timestamp", [
    "2026-11-01Tgarbage", "2026-11-01T12:00:00", None,
    "2026-11-01T23:00:00-02:00",
])
def test_invalid_or_wrong_utc_day_member_fails_verification(tmp_path, monkeypatch, timestamp):
    monkeypatch.setitem(sys.modules, "szl_receipt", None)
    monkeypatch.setattr("szl_energy_attest.meter_proxy.receipts._utcnow",
                        lambda: "2026-11-01T12:00:00.000000Z")
    issuer = ReceiptIssuer(str(tmp_path))
    receipt = issuer.issue(model="dated", tokens_in=1, tokens_out=1,
                           energy={"state": "MEASURED", "measured_joules": 5},
                           carbon={}, latency_seconds=0.01)
    row = build_daily_rollup(issuer.records, store_dir=str(tmp_path), for_date="2026-11-01")
    receipt["body"]["issued_at"] = timestamp
    receipt["digest"] = digest_body(receipt["body"])
    (tmp_path / "receipts.jsonl").write_text(json.dumps(receipt) + "\n")
    row["body"].update(member_digests=[receipt["digest"]],
                       first_member_digest=receipt["digest"],
                       last_member_digest=receipt["digest"])
    save(tmp_path, row)
    assert verify_store(str(tmp_path))["state"] == "FAIL"
    if timestamp != "2026-11-01T23:00:00-02:00":
        with pytest.raises(ValueError, match="timestamp"):
            build_daily_rollup([receipt], store_dir=str(tmp_path / "new"),
                               for_date="2026-11-01")


def test_offset_timestamp_is_assigned_to_actual_utc_day(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "szl_receipt", None)
    monkeypatch.setattr("szl_energy_attest.meter_proxy.receipts._utcnow",
                        lambda: "2026-11-01T23:00:00-02:00")
    issuer = ReceiptIssuer(str(tmp_path))
    issuer.issue(model="offset", tokens_in=1, tokens_out=1,
                 energy={"state": "MEASURED", "measured_joules": 5},
                 carbon={}, latency_seconds=0.01)
    first = build_daily_rollup(issuer.records, store_dir=str(tmp_path), for_date="2026-11-01")
    second = build_daily_rollup(issuer.records, store_dir=str(tmp_path), for_date="2026-11-02")
    assert first["body"]["receipt_count"] == 0
    assert second["body"]["receipt_count"] == 1
    assert verify_store(str(tmp_path))["state"] == "VERIFIED"
