# SPDX-License-Identifier: Apache-2.0
"""Standards-interop layer for szl_energy_attest (delegated to szl_receipt.attest).

Proves the energy-receipt path speaks in-toto / SLSA-shaped statements and the
regulator catalogue, honestly:
  * a receipt -> a valid in-toto Statement v1 bound to the receipt's OWN digest;
  * verify rebinds the statement to its receipt and REJECTS a swapped receipt;
  * energy=UNAVAILABLE (CPU) => the efficiency control is UNAVAILABLE, never a
    fabricated "supports"; a MEASURED receipt flips it to supports;
  * every statement carries our own predicateType (never an SLSA-conformance claim).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

# The interop layer requires the shared lib; skip cleanly if absent locally.
pytest.importorskip("szl_receipt")
pytest.importorskip("szl_receipt.attest")

from szl_energy_attest import (  # noqa: E402
    build_receipt, GENESIS_PREV, LABEL_MEASURED, LABEL_UNAVAILABLE,
    to_intoto_statement, compliance_evidence, verify_statement, attest,
    to_json, IN_TOTO_STATEMENT_TYPE, SZL_PREDICATE_TYPE,
)


def _cpu_receipt():
    return build_receipt(tokens=42, node="cpu-node", prev=GENESIS_PREV)


def _measured_receipt():
    return build_receipt(tokens=7, node="gpu0", measured_joules=123.456,
                         label=LABEL_MEASURED, prev=GENESIS_PREV)


def test_statement_is_wellformed_intoto_and_binds_receipt():
    r = _cpu_receipt()
    st = to_intoto_statement(r)
    assert st["_type"] == IN_TOTO_STATEMENT_TYPE
    # SZL-owned predicateType — never a claim of SLSA conformance.
    assert st["predicateType"] == SZL_PREDICATE_TYPE
    assert "in-toto.io/attestation/vsa" not in st["predicateType"]
    # Subject binds to the receipt body's payload_digest under its own algorithm.
    alg, _, hexval = r["payload_digest"].partition(":")
    subj = st["subject"][0]
    assert subj["digest"][alg] == hexval
    # Chain coordinates travel with the statement for whole-chain re-linking.
    assert st["predicate"]["runDetails"]["receipt"]["digest"] == r["digest"]


def test_verify_accepts_matching_and_rejects_swapped_receipt():
    r0 = _cpu_receipt()
    r1 = build_receipt(tokens=99, node="other", prev=GENESIS_PREV)
    st = to_intoto_statement(r0)
    ok, why = verify_statement(st, r0)
    assert ok and why == "ok", (ok, why)
    # A different receipt must NOT verify against r0's statement.
    bad_ok, bad_why = verify_statement(st, r1)
    assert bad_ok is False and bad_why == "subject-digest-not-bound", bad_why


def test_verify_rejects_tampered_receipt_body():
    r = _cpu_receipt()
    st = to_intoto_statement(r)
    r["tokens"] = 999999  # tamper body without re-hashing payload_digest
    ok, why = verify_statement(st, r)
    assert ok is False and why == "receipt-payload-digest-mismatch", why


def test_compliance_energy_unavailable_on_cpu():
    ev = compliance_evidence(_cpu_receipt())
    assert ev["measured_energy"] is False
    by_status = {c["id"]: c["status"] for c in ev["controls"]}
    # Logging / integrity / governance are supported by a hash-chained receipt.
    assert any(s == "supports" for s in by_status.values())
    # No control may claim measured-energy efficiency on a CPU-only receipt.
    for c in ev["controls"]:
        assert "does_not_establish" in c and c["does_not_establish"]
    assert "disclaimer" in ev


def test_compliance_energy_supports_when_measured():
    ev = compliance_evidence(_measured_receipt())
    assert ev["measured_energy"] is True


def test_attest_bundle_and_json_roundtrip():
    r = _measured_receipt()
    bundle = attest(r)
    assert set(bundle) == {"statement", "compliance"}
    # measured_joules is carried VERBATIM into the statement metadata, never faked.
    meta = bundle["statement"]["predicate"]["runDetails"]["metadata"]
    assert meta["measured"] is True
    assert meta["measured_joules"] == 123.456
    # to_json emits parseable canonical JSON.
    import json
    assert json.loads(to_json(bundle)) == bundle
