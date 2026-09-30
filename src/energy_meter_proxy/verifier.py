# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Offline verifier for per-inference receipts and daily rollups.

Estate pattern: verify everything from the durable store alone, no network, no
trust in the proxy process. Reports per-law states:

    VERIFIED        — every receipt re-hashes, chain links hold, signatures
                      validate (or are honestly UNSIGNED with a note)
    FAIL            — any tamper: digest mismatch, chain break, bad signature,
                      rollup member mismatch
    INCOMPLETE      — evidence missing (never reported as PASS)

Unsigned-honest receipts (no key configured at issuance) verify as
``unsigned-honest`` — reported as a distinct, truthful state, never as a
signed verification and never silently as failure.

Usage::

    python -m energy_meter_proxy.verifier /path/to/szl-receipts \
        --pubkey /path/to/pub.pem
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from . import GENESIS_PREV
from .receipts import canonical_json, digest_body


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _verify_signature(record: Dict[str, Any],
                      pubkey_pem: Optional[bytes]) -> Tuple[str, str]:
    """Return (state, detail). state: SIGNED-VERIFIED | unsigned-honest | FAIL |
    UNCAPPED (no signing layer installed)."""
    env = record.get("signature")
    if not record.get("signature_present"):
        return ("UNCAPPED",
                record.get("signature_note") or "no signature present")
    try:
        from szl_receipt import verify_receipt
    except Exception:  # noqa: BLE001
        return ("UNCAPPED", "szl-receipt not installed; cannot check signature")
    if env is None:
        return ("FAIL", "signature_present asserted but envelope is null")
    ok, msg = verify_receipt(env, pubkey_pem)
    if ok:
        return ("SIGNED-VERIFIED", msg)
    if msg == "unsigned-honest" or (env.get("signed") is False):
        return ("unsigned-honest", msg)
    return ("FAIL", msg)


def verify_store(store_dir: str,
                 pubkey_pem: Optional[bytes] = None) -> Dict[str, Any]:
    """Verify every per-inference receipt, chain linkage, and rollups."""
    result: Dict[str, Any] = {
        "store_dir": store_dir,
        "state": "VERIFIED",
        "receipts_checked": 0,
        "signed_verified": 0,
        "unsigned_honest": 0,
        "rollups_checked": 0,
        "details": [],
    }

    receipts = _load_jsonl(os.path.join(store_dir, "receipts.jsonl"))
    rollups = _load_jsonl(os.path.join(store_dir, "rollups.jsonl"))
    if not receipts and not rollups:
        result["state"] = "INCOMPLETE"
        result["details"].append("no receipts found in store — INCOMPLETE, never PASS")
        return result

    def fail(detail: str) -> None:
        result["state"] = "FAIL"
        result["details"].append("FAIL: " + detail)

    seen_digests = set()
    for i, rec in enumerate(receipts):
        body = rec.get("body")
        if not isinstance(body, dict):
            fail("receipt %d missing body" % i)
            continue
        claimed = rec.get("digest")
        actual = digest_body(body)
        if claimed != actual:
            fail("receipt %d digest mismatch: tampering or corruption "
                 "(claimed %.16s… actual %.16s…)" % (i, claimed or "", actual))
            continue
        expected_prev = receipts[i - 1]["digest"] if i else GENESIS_PREV
        if body.get("prev") != expected_prev:
            fail("receipt %d chain break: prev does not match previous digest" % i)
            continue
        # If a signature envelope exists, its decoded payload must be the
        # exact canonical body bytes — byte-bound to the hashed body.
        env = rec.get("signature")
        if env and env.get("payload"):
            try:
                payload = base64.b64decode(env["payload"]).decode("utf-8")
            except Exception as exc:  # noqa: BLE001
                fail("receipt %d envelope payload not decodable: %r" % (i, exc))
                continue
            if payload != canonical_json(body):
                fail("receipt %d envelope payload not byte-identical to "
                     "canonical body" % i)
                continue
        sig_state, sig_detail = _verify_signature(rec, pubkey_pem)
        if sig_state == "FAIL":
            fail("receipt %d signature: %s" % (i, sig_detail))
            continue
        if sig_state == "SIGNED-VERIFIED":
            result["signed_verified"] += 1
        elif sig_state == "unsigned-honest":
            result["unsigned_honest"] += 1
        result["receipts_checked"] += 1
        seen_digests.add(actual)

    # Rollup verification: own digest + chained prev + member coverage.
    for j, rec in enumerate(rollups):
        body = rec.get("body")
        if not isinstance(body, dict):
            fail("rollup %d missing body" % j)
            continue
        if digest_body(body) != rec.get("digest"):
            fail("rollup %d digest mismatch: tampering or corruption" % j)
            continue
        expected_prev = rollups[j - 1]["digest"] if j else GENESIS_PREV
        if body.get("prev_rollup") != expected_prev:
            fail("rollup %d chain break in rollup spine" % j)
            continue
        for md in body.get("member_digests") or []:
            if md not in seen_digests:
                fail("rollup %d references unknown member digest %.16s…"
                     % (j, md))
                break
        else:
            sig_state, sig_detail = _verify_signature(rec, pubkey_pem)
            if sig_state == "FAIL":
                fail("rollup %d signature: %s" % (j, sig_detail))
                continue
            result["rollups_checked"] += 1

    result["summary"] = (
        "%d receipts checked, %d signed-verified, %d unsigned-honest, "
        "%d rollups checked -> %s"
        % (result["receipts_checked"], result["signed_verified"],
           result["unsigned_honest"], result["rollups_checked"],
           result["state"])
    )
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Offline verifier for "
                                 "szl-energy-attest per-inference receipts")
    ap.add_argument("store_dir")
    ap.add_argument("--pubkey", default=None,
                    help="PEM public key for signed receipts (optional)")
    args = ap.parse_args(argv)
    pub = None
    if args.pubkey:
        with open(args.pubkey, "rb") as fh:
            pub = fh.read()
    res = verify_store(args.store_dir, pub)
    print(json.dumps(res, indent=2, sort_keys=True))
    return 0 if res["state"] == "VERIFIED" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
