# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Canonical szl-receipt spine fold for szl_energy_attest (emit_receipt).

Proves the energy-attest path folds onto the shared szl-receipt spine honestly:
  * emit_receipt binds subject/meter id + input digest + output/measurement
    digest + governing policy id + energy into ONE canonical szl-receipt;
  * MEASURED-NVML joules are carried VERBATIM only when the receipt truly
    measured them; the unmeasured (CPU) path yields the literal "UNAVAILABLE"
    with measured=False — never a fabricated joule;
  * keyless => honest UNSIGNED envelope (signed=False), never a fake signature;
  * a real ECDSA-P256 key signs a verifiable envelope; a wrong key fails and a
    tampered payload fails (integrity/reproducibility, NOT correctness);
  * the same inputs reproduce a byte-identical canonical payload + digest.
"""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

# The spine fold requires the shared lib; skip cleanly if absent locally.
pytest.importorskip("szl_receipt")

from szl_energy_attest import (  # noqa: E402
    build_receipt, GENESIS_PREV, LABEL_MEASURED, LABEL_UNAVAILABLE,
    emit_receipt, energy_binding, PCGI_RECEIPT_SCHEMA, DEFAULT_POLICY_ID,
)
from szl_receipt import generate_keypair, verify_receipt  # noqa: E402


def _cpu_receipt():
    return build_receipt(tokens=42, node="cpu-node", prev=GENESIS_PREV)


def _measured_receipt():
    return build_receipt(tokens=7, node="gpu0", measured_joules=123.456,
                         label=LABEL_MEASURED, prev=GENESIS_PREV)


def _decode_body(env):
    return json.loads(base64.b64decode(env["payload"]).decode("utf-8"))


def test_measured_path_binds_joule_verbatim():
    r = _measured_receipt()
    env = emit_receipt(r, input_digest="sha256:deadbeef",
                       policy_id="pol/xyz@1")
    body = _decode_body(env)
    assert body["schema"] == PCGI_RECEIPT_SCHEMA
    assert body["subject"] == "szl-energy-attest/meter/gpu0"
    assert body["input_digest"] == "sha256:deadbeef"
    # output digest binds to the exact energy record it describes.
    assert body["output_digest"] == r["payload_digest"]
    assert body["policy_id"] == "pol/xyz@1"
    # MEASURED joule carried VERBATIM.
    assert body["energy"]["measured"] is True
    assert body["energy"]["joules"] == 123.456
    assert body["energy"]["label"] == LABEL_MEASURED


def test_unmeasured_path_is_unavailable_never_fabricated():
    r = _cpu_receipt()
    env = emit_receipt(r)
    body = _decode_body(env)
    assert body["energy"]["measured"] is False
    # honest literal UNAVAILABLE, not a number.
    assert body["energy"]["joules"] == LABEL_UNAVAILABLE
    assert body["energy"]["label"] == LABEL_UNAVAILABLE
    # a caller who supplies no input digest gets an honest UNAVAILABLE, not a fake.
    assert body["input_digest"] == LABEL_UNAVAILABLE
    # defaults: subject from node, spine policy id.
    assert body["subject"] == "szl-energy-attest/meter/cpu-node"
    assert body["policy_id"] == DEFAULT_POLICY_ID


def test_energy_binding_drops_joule_when_label_not_measured():
    # A non-MEASURED receipt can never carry a joule (build_receipt drops it),
    # and the binding reports the honest UNAVAILABLE regardless.
    r = build_receipt(tokens=1, node="n", measured_joules=99.0,
                      label=LABEL_UNAVAILABLE, prev=GENESIS_PREV)
    b = energy_binding(r)
    assert b["measured"] is False
    assert b["joules"] == LABEL_UNAVAILABLE


def test_keyless_is_unsigned_honest():
    env = emit_receipt(_cpu_receipt())  # no sign_key
    assert env["signed"] is False
    assert env["organ"] == "szl-energy-attest"
    # verify of a keyless envelope never reports a fake pass.
    ok, why = verify_receipt(env)
    assert (ok, why) == (False, "unsigned-honest")


def test_signed_receipt_verifies_and_wrong_key_and_tamper_fail():
    priv, pub = generate_keypair()
    env = emit_receipt(_measured_receipt(), input_digest="sha256:abc",
                       sign_key=priv, organ="attest", keyid="k1")
    assert env["signed"] is True
    assert env["organ"] == "attest" and env["keyid"] == "k1"
    ok, why = verify_receipt(env, pub)
    assert ok and why == "ok", (ok, why)

    # Wrong key must NOT verify (real crypto, not a fake pass).
    _, other_pub = generate_keypair()
    bad_ok, _ = verify_receipt(env, other_pub)
    assert bad_ok is False

    # Tampering the signed payload must break verification.
    tampered = dict(env)
    body = _decode_body(env)
    body["energy"]["joules"] = 0.0  # forge a different joule
    tampered["payload"] = base64.b64encode(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).decode("ascii")
    t_ok, _ = verify_receipt(tampered, pub)
    assert t_ok is False


def test_deterministic_canonical_payload_and_digest():
    # Same inputs => byte-identical canonical payload + content digest (keyless,
    # so nothing random is involved). Integrity/reproducibility, not correctness.
    r = _measured_receipt()
    a = emit_receipt(r, input_digest="sha256:abc", policy_id="pol/1@1")
    b = emit_receipt(r, input_digest="sha256:abc", policy_id="pol/1@1")
    assert a["payload"] == b["payload"]
    assert a["digest"] == b["digest"]
    # a different input digest changes the receipt (it is genuinely bound).
    c = emit_receipt(r, input_digest="sha256:other", policy_id="pol/1@1")
    assert c["payload"] != a["payload"]
    assert c["digest"] != a["digest"]


def test_receipt_is_evidence_not_correctness():
    body = _decode_body(emit_receipt(_measured_receipt()))
    assert "doctrine" in body
    assert "not the correctness" in body["doctrine"].lower()
