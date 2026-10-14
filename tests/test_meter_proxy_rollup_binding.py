# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Rollups are bound to their own signed bodies and report honest assurance.

Covers RQ-04 (audit B-006/B-007): a rollup must not verify with an envelope
from another record, must equal the rollup its listed member receipts produce,
and an unsigned, UNCAPPED or unchecked record must never make a store VERIFIED.

Signing uses ephemeral keys generated inside the test run only.
"""
import base64
import copy
import json
import os
import sys

import pytest

from szl_energy_attest.meter_proxy import receipts as receipts_mod
from szl_energy_attest.meter_proxy.receipts import ReceiptIssuer, digest_body
from szl_energy_attest.meter_proxy.rollup import (
    ROLLUP_KIND,
    ROLLUP_PREDICATE_TYPE,
    build_daily_rollup,
    rollup_body,
)
from szl_energy_attest.meter_proxy.verifier import (
    check_envelope_binding,
    main,
    verify_store,
)

DAY1 = "2026-10-01"
DAY2 = "2026-10-02"

# The rollup body schema has been unchanged since the vertical landed (#47).
# The verifier recomputes every one of these fields, so a builder change must
# come with a verifier review.
ROLLUP_BODY_KEYS = {
    "spec_version", "predicate_type", "kind", "date", "receipt_count",
    "counts", "measured_joules_sum", "measured_joules_label",
    "estimated_joules_sum", "estimated_joules_label", "measured_kwh_sum",
    "member_digests", "first_member_digest", "last_member_digest",
    "prev_rollup", "doctrine",
}


@pytest.fixture
def clock(monkeypatch):
    """Deterministic issued_at so receipts can land on chosen UTC days."""
    state = {"day": DAY1, "n": 0}

    def now():
        state["n"] += 1
        return "%sT12:00:%02d.%06dZ" % (state["day"], state["n"] % 60, state["n"])

    monkeypatch.setattr(receipts_mod, "_utcnow", now)
    return state


@pytest.fixture
def keys():
    szl_receipt = pytest.importorskip("szl_receipt")
    return szl_receipt.generate_keypair()


def _issue(issuer, state="UNAVAILABLE", joules=None, est=None, model="m"):
    return issuer.issue(
        model=model, tokens_in=1, tokens_out=2,
        energy={"state": state, "measured_joules": joules,
                "estimated_joules": est, "measurement_mode": None,
                "detail": "test fixture"},
        carbon={"label": "UNAVAILABLE", "carbon_intensity_gco2_per_kwh": None,
                "reason": "test"},
        latency_seconds=0.01,
        synthetic=(state == "ESTIMATED"),
        provenance="demo-synthetic" if state == "ESTIMATED" else "live",
    )


def _store(tmp_path, clock, priv=None):
    """Two UTC days of receipts, one rollup per day, all with *priv*."""
    store = str(tmp_path / "store")
    issuer = ReceiptIssuer(store, private_key_pem=priv)
    clock["day"] = DAY1
    _issue(issuer, "MEASURED", joules=12.5)
    _issue(issuer, "UNAVAILABLE")
    _issue(issuer, "ESTIMATED", est=0.42)
    build_daily_rollup(issuer.records, store_dir=store, for_date=DAY1,
                       private_key_pem=priv)
    clock["day"] = DAY2
    _issue(issuer, "MEASURED", joules=3.0)
    build_daily_rollup(issuer.records, store_dir=store, for_date=DAY2,
                       private_key_pem=priv)
    return store


def _read(store, name):
    with open(os.path.join(store, name), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write(store, name, records):
    with open(os.path.join(store, name), "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _fails_with(res, text):
    assert res["state"] == "FAIL", res
    assert any(text in d for d in res["details"]), res["details"]


def _uncap(rec):
    """Drop a record's envelope, as an issuer without szl-receipt would."""
    rec["signature"] = None
    rec["signature_present"] = False
    rec["signature_note"] = "test: no envelope"


# --------------------------------------------------------------------------
# Intact stores
# --------------------------------------------------------------------------

def test_signed_store_with_key_is_verified_and_authenticated(tmp_path, clock, keys):
    priv, pub = keys
    res = verify_store(_store(tmp_path, clock, priv), pub)
    assert res["state"] == "VERIFIED", res
    assert res["receipts_checked"] == res["signed_verified"] == 4
    assert res["rollups_checked"] == 2
    assert res["rollup_signatures"]["SIGNED-VERIFIED"] == 2
    assert [r["assurance"] for r in res["rollups"]] == ["authenticated"] * 2
    assert res["rollups"][0]["member_count"] == 3
    assert res["rollups"][0]["member_signatures"]["SIGNED-VERIFIED"] == 3


def test_rollup_builder_output_is_what_the_verifier_recomputes(tmp_path, clock):
    store = _store(tmp_path, clock)
    receipts = _read(store, "receipts.jsonl")
    rollups = _read(store, "rollups.jsonl")
    assert set(rollups[0]["body"]) == ROLLUP_BODY_KEYS
    assert rollups[0]["body"] == rollup_body(
        receipts[:3], day=DAY1, prev_rollup="0" * 64)
    assert rollups[1]["body"] == rollup_body(
        receipts[3:], day=DAY2, prev_rollup=rollups[0]["digest"])
    assert rollups[0]["body"]["kind"] == ROLLUP_KIND
    assert rollups[0]["body"]["predicate_type"] == ROLLUP_PREDICATE_TYPE
    assert rollups[0]["body"]["measured_joules_sum"] == 12.5
    assert rollups[0]["body"]["estimated_joules_sum"] == 0.42


def test_non_ascii_body_binds_to_the_bytes_szl_receipt_signs(tmp_path, clock, keys):
    # szl-receipt signs UTF-8 with non-ASCII unescaped; the binding must use
    # those exact bytes rather than the ASCII-escaped hashing form.
    priv, pub = keys
    store = str(tmp_path / "store")
    issuer = ReceiptIssuer(store, private_key_pem=priv)
    _issue(issuer, "MEASURED", joules=1.0, model="modèle-ünïcode-模型")
    build_daily_rollup(issuer.records, store_dir=store, for_date=DAY1,
                       private_key_pem=priv)
    assert verify_store(store, pub)["state"] == "VERIFIED"


# --------------------------------------------------------------------------
# Envelope bound to its own body
# --------------------------------------------------------------------------

def test_valid_envelope_swapped_onto_another_rollup_body_fails(tmp_path, clock, keys):
    priv, pub = keys
    store = _store(tmp_path, clock, priv)
    rollups = _read(store, "rollups.jsonl")
    rollups[0]["signature"], rollups[1]["signature"] = (
        rollups[1]["signature"], rollups[0]["signature"])
    _write(store, "rollups.jsonl", rollups)
    for key in (pub, None):
        res = verify_store(store, key)
        _fails_with(res, "rollup 0 signature: envelope payload is not the "
                    "exact canonical bytes")
        _fails_with(res, "rollup 1 signature: envelope payload is not the "
                    "exact canonical bytes")


def test_valid_envelope_swapped_between_receipts_fails(tmp_path, clock, keys):
    priv, pub = keys
    store = _store(tmp_path, clock, priv)
    receipts = _read(store, "receipts.jsonl")
    receipts[0]["signature"] = copy.deepcopy(receipts[1]["signature"])
    _write(store, "receipts.jsonl", receipts)
    _fails_with(verify_store(store, pub),
                "receipt 0 signature: envelope payload is not the exact")


@pytest.mark.parametrize("mutate, reason", [
    (lambda e: e.update(payloadType="application/vnd.in-toto+json"),
     "payloadType"),
    (lambda e: e.update(payload=e["payload"] + "\n"), "strict base64"),
    (lambda e: e.update(payload=base64.b64encode(json.dumps(
        json.loads(base64.b64decode(e["payload"])), indent=2).encode()).decode()),
     "not the exact canonical bytes"),
    (lambda e: e.update(payload=""), "missing"),
    (lambda e: e.update(digest="0" * 64), "digest does not match"),
    (lambda e: e.update(signed="yes"), "not a boolean"),
    (lambda e: e.update(signed=False), "carries a signature"),
    (lambda e: e.update(signature=""), "carries no signature"),
])
def test_envelope_binding_rejects_altered_envelopes(tmp_path, clock, keys,
                                                    mutate, reason):
    priv, _ = keys
    store = _store(tmp_path, clock, priv)
    rec = _read(store, "rollups.jsonl")[0]
    assert check_envelope_binding(rec["signature"], rec["body"]) is None
    env = copy.deepcopy(rec["signature"])
    mutate(env)
    err = check_envelope_binding(env, rec["body"])
    assert err is not None and reason in err, err


# --------------------------------------------------------------------------
# Cross-kind swaps
# --------------------------------------------------------------------------

def test_receipt_envelope_grafted_onto_rollup_fails(tmp_path, clock, keys):
    priv, pub = keys
    store = _store(tmp_path, clock, priv)
    receipts, rollups = _read(store, "receipts.jsonl"), _read(store, "rollups.jsonl")
    rollups[0]["signature"] = copy.deepcopy(receipts[0]["signature"])
    _write(store, "rollups.jsonl", rollups)
    _fails_with(verify_store(store, pub), "rollup 0 signature: envelope payload")


def test_rollup_envelope_grafted_onto_receipt_fails(tmp_path, clock, keys):
    priv, pub = keys
    store = _store(tmp_path, clock, priv)
    receipts, rollups = _read(store, "receipts.jsonl"), _read(store, "rollups.jsonl")
    receipts[0]["signature"] = copy.deepcopy(rollups[0]["signature"])
    _write(store, "receipts.jsonl", receipts)
    _fails_with(verify_store(store, pub), "receipt 0 signature: envelope payload")


def test_receipt_record_filed_as_rollup_fails_as_cross_kind(tmp_path, clock, keys):
    priv, pub = keys
    store = str(tmp_path / "store")
    issuer = ReceiptIssuer(store, private_key_pem=priv)
    rec = copy.deepcopy(_issue(issuer, "MEASURED", joules=1.0))
    # Give it a rollup-spine link and an empty member list, then re-hash.
    rec["body"]["prev_rollup"] = "0" * 64
    rec["body"]["member_digests"] = []
    rec["digest"] = digest_body(rec["body"])
    _uncap(rec)
    _write(store, "rollups.jsonl", [rec])
    _fails_with(verify_store(store, pub), "rollup 0 is not an energy daily rollup")


def test_rollup_record_filed_as_receipt_fails_as_cross_kind(tmp_path, clock, keys):
    priv, pub = keys
    store = _store(tmp_path, clock, priv)
    receipts, rollups = _read(store, "receipts.jsonl"), _read(store, "rollups.jsonl")
    forged = copy.deepcopy(rollups[1])
    forged["body"]["prev"] = receipts[-1]["digest"]
    forged["digest"] = digest_body(forged["body"])
    _uncap(forged)
    _write(store, "receipts.jsonl", receipts + [forged])
    _fails_with(verify_store(store, pub), "receipt 4 is not a per-inference")


def test_rollup_listing_a_rollup_as_member_fails(tmp_path, clock):
    store = _store(tmp_path, clock)
    rollups = _read(store, "rollups.jsonl")
    body = rollups[1]["body"]
    body["member_digests"] = [rollups[0]["digest"]] + body["member_digests"]
    rollups[1]["digest"] = digest_body(body)
    _uncap(rollups[1])
    _write(store, "rollups.jsonl", rollups)
    _fails_with(verify_store(store, None), "rollup 1 references unknown member")


# --------------------------------------------------------------------------
# Absent signature or backend never becomes VERIFIED
# --------------------------------------------------------------------------

def _strip_all(store):
    for name in ("receipts.jsonl", "rollups.jsonl"):
        records = _read(store, name)
        for rec in records:
            _uncap(rec)
        _write(store, name, records)


def test_stripped_signatures_are_unauthenticated_with_key(tmp_path, clock, keys):
    priv, pub = keys
    store = _store(tmp_path, clock, priv)
    _strip_all(store)
    res = verify_store(store, pub)
    assert res["state"] == "UNAUTHENTICATED", res
    assert res["uncapped"] == 4 and res["signed_verified"] == 0
    assert res["rollup_signatures"]["UNCAPPED"] == 2
    res = verify_store(store, None)
    assert res["state"] == "INTEGRITY-ONLY", res


def test_signed_store_without_key_is_integrity_only_not_fail(tmp_path, clock, keys):
    priv, _ = keys
    res = verify_store(_store(tmp_path, clock, priv), None)
    assert res["state"] == "INTEGRITY-ONLY", res
    assert res["signature_unchecked"] == 4
    assert res["rollup_signatures"]["SIGNATURE-UNCHECKED"] == 2
    assert {r["assurance"] for r in res["rollups"]} == {"integrity-only"}


def test_missing_backend_at_verify_time_is_not_verified(tmp_path, clock, keys,
                                                        monkeypatch):
    priv, pub = keys
    store = _store(tmp_path, clock, priv)
    monkeypatch.setitem(sys.modules, "szl_receipt", None)  # import now fails
    res = verify_store(store, pub)
    assert res["state"] == "UNAUTHENTICATED", res
    assert res["signature_unchecked"] == 4
    assert res["signed_verified"] == 0


def test_missing_backend_at_issue_time_is_uncapped(tmp_path, clock, keys,
                                                   monkeypatch):
    _, pub = keys
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "szl_receipt", None)
        store = _store(tmp_path, clock, None)
    assert all(r["signature"] is None for r in _read(store, "receipts.jsonl"))
    res = verify_store(store, pub)
    assert res["state"] == "UNAUTHENTICATED", res
    assert res["uncapped"] == 4
    assert verify_store(store, None)["state"] == "INTEGRITY-ONLY"


def test_keyless_store_is_never_verified(tmp_path, clock):
    pytest.importorskip("szl_receipt")
    store = _store(tmp_path, clock, None)
    res = verify_store(store, None)
    assert res["state"] == "INTEGRITY-ONLY", res
    assert res["unsigned_honest"] == 4
    assert res["rollup_signatures"]["unsigned-honest"] == 2


def test_signed_marker_downgrade_is_unauthenticated_with_key(tmp_path, clock, keys):
    priv, pub = keys
    store = _store(tmp_path, clock, priv)
    receipts = _read(store, "receipts.jsonl")
    env = receipts[2]["signature"]
    env.update(signed=False, signature="")
    _write(store, "receipts.jsonl", receipts)
    res = verify_store(store, pub)
    assert res["state"] == "UNAUTHENTICATED", res
    assert res["unsigned_honest"] == 1 and res["signed_verified"] == 3
    assert res["rollups"][0]["assurance"] == "integrity-only"
    assert res["rollups"][1]["assurance"] == "authenticated"


@pytest.mark.parametrize("present, env, reason", [
    (False, "keep", "signature_present is false but an envelope"),
    ("true", "keep", "signature_present is not a boolean"),
    (True, None, "envelope is null"),
])
def test_inconsistent_signature_flags_fail(tmp_path, clock, keys, present, env,
                                           reason):
    priv, pub = keys
    store = _store(tmp_path, clock, priv)
    receipts = _read(store, "receipts.jsonl")
    receipts[1]["signature_present"] = present
    if env is None:
        receipts[1]["signature"] = None
    _write(store, "receipts.jsonl", receipts)
    _fails_with(verify_store(store, pub), reason)


# --------------------------------------------------------------------------
# Mixed stores keep their distinctions
# --------------------------------------------------------------------------

def test_mixed_store_preserves_unauthenticated_and_uncapped(tmp_path, clock, keys,
                                                            monkeypatch):
    priv, pub = keys
    store = str(tmp_path / "store")
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "szl_receipt", None)
        _issue(ReceiptIssuer(store), "MEASURED", joules=2.0)          # UNCAPPED
    _issue(ReceiptIssuer(store), "UNAVAILABLE")                       # unsigned-honest
    signed = ReceiptIssuer(store, private_key_pem=priv)
    _issue(signed, "MEASURED", joules=5.0)                            # signed
    _issue(signed, "ESTIMATED", est=0.5)                              # signed
    build_daily_rollup(signed.records, store_dir=store, for_date=DAY1,
                       private_key_pem=priv)

    res = verify_store(store, pub)
    assert res["state"] == "UNAUTHENTICATED", res
    assert (res["signed_verified"], res["unsigned_honest"], res["uncapped"],
            res["signature_unchecked"]) == (2, 1, 1, 0)
    (roll,) = res["rollups"]
    assert roll["signature"] == "SIGNED-VERIFIED"
    assert roll["member_signatures"] == {
        "SIGNED-VERIFIED": 2, "unsigned-honest": 1, "UNCAPPED": 1,
        "SIGNATURE-UNCHECKED": 0}
    # A signed rollup over unauthenticated members is not authenticated.
    assert roll["assurance"] == "integrity-only"

    res = verify_store(store, None)
    assert res["state"] == "INTEGRITY-ONLY", res
    assert (res["signed_verified"], res["unsigned_honest"], res["uncapped"],
            res["signature_unchecked"]) == (0, 1, 1, 2)
    assert res["rollups"][0]["signature"] == "SIGNATURE-UNCHECKED"


# --------------------------------------------------------------------------
# Rollup bodies must match their member records
# --------------------------------------------------------------------------

def _bump_counts(b):
    b["counts"]["measured"] += 1


def _double_sum(b):
    b["measured_joules_sum"] *= 2
    b["measured_kwh_sum"] = b["measured_joules_sum"] / 3_600_000.0


def _swap_first_last(b):
    b["first_member_digest"], b["last_member_digest"] = (
        b["last_member_digest"], b["first_member_digest"])


def _promote_estimate(b):
    b["measured_joules_sum"] += b["estimated_joules_sum"]
    b["estimated_joules_sum"] = None


@pytest.mark.parametrize("mutate, reason", [
    (_bump_counts, "counts"),
    (_double_sum, "measured_joules_sum, measured_kwh_sum"),
    (_promote_estimate, "estimated_joules_sum, measured_joules_sum"),
    (lambda b: b.update(receipt_count=b["receipt_count"] + 1), "receipt_count"),
    (lambda b: b.update(receipt_count=True), "receipt_count"),
    (lambda b: b.update(measured_kwh_sum=1.0), "measured_kwh_sum"),
    (lambda b: b.update(measured_joules_label="MEASURED-SUM-OVER-ALL-MEMBERS"),
     "measured_joules_label"),
    (_swap_first_last, "first_member_digest, last_member_digest"),
    (lambda b: b.update(billed_kwh=99.0), "billed_kwh"),
    (lambda b: b.pop("doctrine"), "doctrine"),
    (lambda b: b["member_digests"].pop(), "inconsistent with its 2 listed"),
    (lambda b: b["member_digests"].append(b["member_digests"][0]), "twice"),
    (lambda b: b["member_digests"].reverse(), "not in chain order"),
    (lambda b: b["member_digests"].append("f" * 64), "unknown member"),
    (lambda b: b.update(member_digests="all"), "not a list"),
    (lambda b: b.update(date=DAY2), "was not issued on " + DAY2),
    (lambda b: b.update(date=""), "has no date"),
])
def test_rollup_edits_with_recomputed_digest_fail(tmp_path, clock, mutate, reason):
    store = _store(tmp_path, clock)
    rollups = _read(store, "rollups.jsonl")
    # Re-hash the edited rollup and re-link the next one to it, and drop the
    # envelopes, so both chains stay intact and nothing is signed: the member
    # and aggregate checks are the only thing that can catch these.
    target = rollups[0]
    mutate(target["body"])
    target["digest"] = digest_body(target["body"])
    rollups[1]["body"]["prev_rollup"] = target["digest"]
    rollups[1]["digest"] = digest_body(rollups[1]["body"])
    for rec in rollups:
        _uncap(rec)
    _write(store, "rollups.jsonl", rollups)
    res = verify_store(store, None)
    _fails_with(res, reason)
    assert any(d.startswith("FAIL: rollup 0 ") for d in res["details"]), res


def test_consistent_subset_rollup_is_never_verified(tmp_path, clock, keys):
    # Dropping a member and recomputing every aggregate yields a rollup that is
    # consistent with what it lists. Unsigned, that is INTEGRITY-ONLY at best;
    # the original signed envelope no longer binds to it.
    priv, pub = keys
    store = _store(tmp_path, clock, priv)
    receipts, rollups = _read(store, "receipts.jsonl"), _read(store, "rollups.jsonl")
    subset = rollup_body([receipts[0], receipts[2]], day=DAY1,
                         prev_rollup="0" * 64)
    rollups = [{"body": subset, "digest": digest_body(subset),
                "signature": rollups[0]["signature"], "signature_present": True,
                "signature_note": None}]
    _write(store, "rollups.jsonl", rollups)
    _fails_with(verify_store(store, pub), "rollup 0 signature: envelope payload")
    _uncap(rollups[0])
    _write(store, "rollups.jsonl", rollups)
    assert verify_store(store, pub)["state"] == "UNAUTHENTICATED"
    assert verify_store(store, None)["state"] == "INTEGRITY-ONLY"


# --------------------------------------------------------------------------
# Malformed stores fail without raising; CLI exit codes
# --------------------------------------------------------------------------

def test_malformed_store_content_is_a_bounded_fail(tmp_path, clock):
    store = _store(tmp_path, clock)
    with open(os.path.join(store, "rollups.jsonl"), "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    _fails_with(verify_store(store, None), "not readable as JSON lines")

    store = _store(tmp_path / "b", clock)
    receipts = _read(store, "receipts.jsonl")
    _write(store, "receipts.jsonl", receipts + [["not", "a", "record"]])
    _fails_with(verify_store(store, None), "receipt 4 missing body")


def test_member_with_malformed_energy_block_fails_not_raises(tmp_path, clock):
    store = str(tmp_path / "store")
    issuer = ReceiptIssuer(store)
    issuer.issue(model="m", tokens_in=1, tokens_out=1, energy="bogus",
                 carbon={"label": "UNAVAILABLE"}, latency_seconds=0.0)
    body = rollup_body([], day=DAY1, prev_rollup="0" * 64)
    body["member_digests"] = [issuer.records[0]["digest"]]
    rec = {"body": body, "digest": digest_body(body)}
    _uncap(rec)
    _write(store, "rollups.jsonl", [rec])
    _fails_with(verify_store(store, None), "rollup 0 could not be checked")


def test_cli_exit_codes_distinguish_assurance(tmp_path, clock, keys, capsys):
    priv, pub = keys
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(pub)
    signed = _store(tmp_path / "signed", clock, priv)
    assert main([signed, "--pubkey", str(pub_path)]) == 0
    assert main([signed]) == 4

    stripped = _store(tmp_path / "stripped", clock, priv)
    _strip_all(stripped)
    assert main([stripped, "--pubkey", str(pub_path)]) == 3
    assert main([stripped]) == 4

    tampered = _store(tmp_path / "tampered", clock, priv)
    receipts = _read(tampered, "receipts.jsonl")
    receipts[0]["body"]["tokens_out"] = 999
    _write(tampered, "receipts.jsonl", receipts)
    assert main([tampered, "--pubkey", str(pub_path)]) == 1

    empty = tmp_path / "empty"
    empty.mkdir()
    assert main([str(empty)]) == 1
    out = capsys.readouterr().out
    assert '"state": "VERIFIED"' in out and '"state": "INTEGRITY-ONLY"' in out
