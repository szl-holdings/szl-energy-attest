# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""ADDITIVE szl-receipt signing layer for szl_energy_attest.

Proves the doctrine contract on the energy-receipt path:
  * With a generated ECDSA-P256 key, build_receipt(... sign_key=priv) carries a
    DSSE signature envelope that verifies via ``szl_receipt.verify_receipt``.
  * Keyless => UNSIGNED-honest (signed=False, honest note). No fake pass.
  * The additive signature does not disturb the hash chain (verify_chain still
    passes), since chain verification reads only the body fields.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from szl_energy_attest import build_receipt, verify_chain, GENESIS_PREV  # noqa: E402

pytest.importorskip("szl_receipt")
from szl_receipt import generate_keypair, verify_receipt  # noqa: E402


def test_signed_receipt_verifies_and_chain_intact():
    priv, pub = generate_keypair()
    r = build_receipt(tokens=7, node="gpu0", prev=GENESIS_PREV,
                      sign_key=priv, organ="attest")
    env = r["signature"]
    assert env["signed"] is True
    assert env["organ"] == "attest"
    ok, why = verify_receipt(env, pub)
    assert ok and why == "ok", (ok, why)

    # Wrong key must NOT verify (real crypto, not a fake pass).
    _, other_pub = generate_keypair()
    bad_ok, _ = verify_receipt(env, other_pub)
    assert bad_ok is False

    # The additive signature must not disturb the hash chain.
    chain_ok, length, brk = verify_chain([r])
    assert chain_ok and length == 1 and brk == -1


def test_keyless_is_unsigned_honest():
    r = build_receipt(tokens=3, node="cpu", prev=GENESIS_PREV)  # no sign_key
    env = r["signature"]
    assert env["signed"] is False
    assert "UNSIGNED-honest" in env["note"]
    ok, why = verify_receipt(env)
    assert (ok, why) == (False, "unsigned-honest")
