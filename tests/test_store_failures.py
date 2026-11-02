"""Synthetic offline storage failures. No meter, network or signing key."""
import json
import multiprocessing
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from szl_energy_attest.meter_proxy.receipts import ReceiptIssuer, digest_body
from szl_energy_attest.meter_proxy.rollup import build_daily_rollup


def issue(issuer):
    return issuer.issue(model="synthetic", tokens_in=1, tokens_out=1,
                        energy={"state": "UNAVAILABLE", "measured_joules": None},
                        carbon={"label": "UNAVAILABLE"}, latency_seconds=0.01,
                        synthetic=True, provenance="offline-test")


def worker(folder, barrier):
    issuer = ReceiptIssuer(folder)
    barrier.wait(timeout=10)
    issue(issuer)


def test_two_existing_issuers_share_one_chain(tmp_path):
    first = ReceiptIssuer(str(tmp_path)); second = ReceiptIssuer(str(tmp_path))
    a = issue(first); b = issue(second)
    assert b["body"]["seq"] == 1
    assert b["body"]["prev"] == a["digest"]
    assert len(first.records) == 2


def test_process_writers_select_parent_inside_the_lock(tmp_path):
    ctx = multiprocessing.get_context("fork")
    barrier = ctx.Barrier(3)
    children = [ctx.Process(target=worker, args=(str(tmp_path), barrier)) for _ in range(3)]
    for child in children: child.start()
    for child in children:
        child.join(timeout=15)
        if child.is_alive(): child.terminate(); child.join()
        assert child.exitcode == 0
    rows = [json.loads(line) for line in (tmp_path / "receipts.jsonl").read_text().splitlines()]
    assert [r["body"]["seq"] for r in rows] == [0, 1, 2]
    assert all(rows[i]["body"]["prev"] == rows[i-1]["digest"] for i in range(1, 3))


def test_partial_final_line_blocks_resume_and_new_writes(tmp_path):
    issuer = ReceiptIssuer(str(tmp_path)); issue(issuer)
    target = tmp_path / "receipts.jsonl"
    damaged = target.read_bytes().rstrip(b"\n")
    target.write_bytes(damaged)
    with pytest.raises(ValueError): ReceiptIssuer(str(tmp_path))
    with pytest.raises(ValueError): issue(issuer)
    assert target.read_bytes() == damaged


def test_receipt_fsync_failure_keeps_previous_store_and_memory(tmp_path):
    issuer = ReceiptIssuer(str(tmp_path)); issue(issuer)
    path = tmp_path / "receipts.jsonl"; before = path.read_bytes()
    with patch("os.fsync", side_effect=OSError("synthetic sync failure")):
        with pytest.raises(OSError): issue(issuer)
    assert path.read_bytes() == before
    assert len(issuer.records) == 1


def test_duplicate_day_is_idempotent_but_changed_members_are_refused(tmp_path):
    issuer = ReceiptIssuer(str(tmp_path)); issue(issuer)
    first = build_daily_rollup(issuer.records, store_dir=str(tmp_path))
    assert build_daily_rollup(issuer.records, store_dir=str(tmp_path)) == first
    assert len((tmp_path / "rollups.jsonl").read_text().splitlines()) == 1
    issue(issuer)
    with pytest.raises(ValueError): build_daily_rollup(issuer.records, store_dir=str(tmp_path))


def test_rollup_fsync_failure_leaves_no_partial_store(tmp_path):
    issuer = ReceiptIssuer(str(tmp_path)); issue(issuer)
    with patch("os.fsync", side_effect=OSError("synthetic sync failure")):
        with pytest.raises(OSError): build_daily_rollup(issuer.records, store_dir=str(tmp_path))
    path = tmp_path / "rollups.jsonl"
    assert not path.exists() or not path.read_bytes()


def test_nonfinite_body_cannot_be_hashed():
    for value in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValueError): digest_body({"energy": value})


def test_replace_failure_keeps_old_receipts_and_cleans_temp(tmp_path):
    issuer = ReceiptIssuer(str(tmp_path)); issue(issuer)
    target = tmp_path / "receipts.jsonl"; before = target.read_bytes()
    with patch("os.replace", side_effect=OSError("synthetic replace failure")):
        with pytest.raises(OSError): issue(issuer)
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".szl-energy-*"))
    assert len(issuer.records) == 1


def test_directory_sync_failure_reports_error_but_reload_finds_committed_record(tmp_path):
    issuer = ReceiptIssuer(str(tmp_path)); issue(issuer)
    real_sync = os.fsync
    import stat
    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic directory sync failure")
        real_sync(fd)
    with patch("os.fsync", side_effect=fail_directory):
        with pytest.raises(OSError): issue(issuer)
    # Replace already occurred: never claim a rollback or blindly retry.
    assert len(issuer.records) == 2
    assert issue(issuer)["body"]["seq"] == 2


def test_durable_store_rejects_tamper_and_duplicate_json_keys(tmp_path):
    from szl_energy_attest.meter_proxy.verifier import verify_store
    issuer = ReceiptIssuer(str(tmp_path)); issue(issuer)
    target = tmp_path / "receipts.jsonl"
    original = target.read_bytes()
    for damaged in (original[:-1], original + b'{"body":{},"body":{}}\n',
                    original.replace(b'"seq": 0', b'"seq": 2')):
        target.write_bytes(damaged)
        with pytest.raises(ValueError): issue(issuer)
        assert verify_store(str(tmp_path))["state"] == "FAIL"
        assert target.read_bytes() == damaged


def rollup_worker(folder, records, barrier):
    barrier.wait(timeout=10)
    build_daily_rollup(records, store_dir=folder)


def test_concurrent_same_day_rollups_commit_once(tmp_path):
    issuer = ReceiptIssuer(str(tmp_path)); issue(issuer)
    ctx = multiprocessing.get_context("fork"); barrier = ctx.Barrier(3)
    children = [ctx.Process(target=rollup_worker, args=(str(tmp_path), issuer.records, barrier)) for _ in range(3)]
    for child in children: child.start()
    for child in children:
        child.join(timeout=15)
        if child.is_alive(): child.terminate(); child.join()
        assert child.exitcode == 0
    assert len((tmp_path / "rollups.jsonl").read_text().splitlines()) == 1


def test_returned_receipts_cannot_mutate_durable_state(tmp_path):
    issuer = ReceiptIssuer(str(tmp_path)); record = issue(issuer)
    record["body"]["seq"] = 900
    snapshot = issuer.records; snapshot[0]["body"]["seq"] = 800
    assert issuer.records[0]["body"]["seq"] == 0


@pytest.mark.parametrize("number", ["1e999", "-1e999", "1.7976931348623159e308"])
def test_overflowed_json_number_is_refused_even_outside_hashed_body(tmp_path, number):
    from szl_energy_attest.meter_proxy._store import read_records
    from szl_energy_attest.meter_proxy.verifier import verify_store
    issuer = ReceiptIssuer(str(tmp_path)); issue(issuer)
    path = tmp_path / "receipts.jsonl"
    raw = path.read_bytes().replace(b"{", b'{"extra":' + number.encode() + b",", 1)
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="nonfinite JSON number"):
        read_records(path)
    with pytest.raises(ValueError, match="nonfinite JSON number"):
        issue(issuer)
    assert verify_store(str(tmp_path))["state"] == "FAIL"
    assert path.read_bytes() == raw


def test_finite_json_number_remains_readable(tmp_path):
    from szl_energy_attest.meter_proxy._store import read_records
    path = tmp_path / "finite.jsonl"
    path.write_text('{"value":1.7976931348623157e308}\n')
    assert read_records(path) == [{"value": float("1.7976931348623157e308")}]
