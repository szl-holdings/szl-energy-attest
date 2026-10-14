# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Offline verifier for per-inference receipts and daily rollups.

Estate pattern: verify everything from the durable store alone, no network, no
trust in the proxy process. Integrity and authenticity are separate outcomes,
and the store reports exactly one ``state``:

    VERIFIED         — every receipt and rollup re-hashes, both chains hold,
                       every DSSE envelope carries the exact bytes of its own
                       record's body, every rollup equals the rollup its listed
                       member receipts produce, AND every receipt and rollup
                       carries a signature that verified against the supplied
                       public key
    INTEGRITY-ONLY   — every integrity check holds, but at least one receipt
                       or rollup is not authenticated (``unsigned-honest``,
                       ``UNCAPPED`` or ``SIGNATURE-UNCHECKED``) and no public
                       key was supplied. Never reported as VERIFIED.
    UNAUTHENTICATED  — every integrity check holds, a public key was supplied
                       (which requires authentication), and at least one
                       receipt or rollup is not authenticated
    FAIL             — any tamper: digest mismatch, chain break, envelope not
                       bound to its body, cross-kind record, bad signature,
                       rollup member or aggregate mismatch, malformed record
    INCOMPLETE       — evidence missing (never reported as PASS)

Each receipt and rollup also gets a signature state:

    SIGNED-VERIFIED      signed envelope verified with the supplied key
    unsigned-honest      envelope with ``signed=False`` (no key at issuance)
    UNCAPPED             no envelope (szl-receipt absent at issuance)
    SIGNATURE-UNCHECKED  signed envelope bound to its body, but this verifier
                         had no public key or no szl-receipt to check it

A rollup is ``authenticated`` only when its own signature and the signature of
every member receipt it lists are SIGNED-VERIFIED. The verifier checks that a
rollup is consistent with the members it lists; it does not prove the issuer
listed every receipt of that day (for a signed rollup the member list is the
signer's claim).

Usage::

    python -m szl_energy_attest.meter_proxy.verifier /path/to/szl-receipts \\
        --pubkey /path/to/pub.pem

Exit codes: 0 VERIFIED, 1 FAIL or INCOMPLETE, 3 UNAUTHENTICATED,
4 INTEGRITY-ONLY.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from . import GENESIS_PREV, PREDICATE_TYPE
from .receipts import canonical_json, digest_body
from .rollup import ROLLUP_KIND, ROLLUP_PREDICATE_TYPE, rollup_body

STATE_VERIFIED = "VERIFIED"
STATE_INTEGRITY_ONLY = "INTEGRITY-ONLY"
STATE_UNAUTHENTICATED = "UNAUTHENTICATED"
STATE_FAIL = "FAIL"
STATE_INCOMPLETE = "INCOMPLETE"

EXIT_CODES = {
    STATE_VERIFIED: 0,
    STATE_FAIL: 1,
    STATE_INCOMPLETE: 1,
    STATE_UNAUTHENTICATED: 3,
    STATE_INTEGRITY_ONLY: 4,
}

SIG_SIGNED_VERIFIED = "SIGNED-VERIFIED"
SIG_UNSIGNED_HONEST = "unsigned-honest"
SIG_UNCAPPED = "UNCAPPED"
SIG_UNCHECKED = "SIGNATURE-UNCHECKED"
SIG_FAIL = "FAIL"
SIGNATURE_STATES = (SIG_SIGNED_VERIFIED, SIG_UNSIGNED_HONEST, SIG_UNCAPPED,
                    SIG_UNCHECKED)

#: DSSE payload type every szl-receipt envelope declares.
ENVELOPE_PAYLOAD_TYPE = "application/vnd.szl.receipt+json"

# Receipt-level counter key for each passing signature state.
_RECEIPT_COUNTERS = {
    SIG_SIGNED_VERIFIED: "signed_verified",
    SIG_UNSIGNED_HONEST: "unsigned_honest",
    SIG_UNCAPPED: "uncapped",
    SIG_UNCHECKED: "signature_unchecked",
}

_ABSENT = "<absent>"  # never equal to canonical JSON of any value


def _load_jsonl(path: str) -> List[Any]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def envelope_payload_bytes(body: Dict[str, Any]) -> bytes:
    """The exact bytes szl-receipt puts in a DSSE envelope for *body*.

    Sorted-key compact JSON in UTF-8 with non-ASCII left unescaped, as
    ``szl_receipt`` canonicalises. For an ASCII-only body this is
    byte-identical to ``canonical_json(body)``.
    """
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def check_envelope_binding(env: Any, body: Dict[str, Any]) -> Optional[str]:
    """Return why *env* is not bound to *body*, or None when it is.

    Shared by receipt and rollup verification. An envelope is bound when it
    declares the szl-receipt payload type, its payload is strict canonical
    base64 of exactly ``envelope_payload_bytes(body)``, its advisory
    ``digest`` (if any) matches those bytes, and its ``signed`` marker is a
    boolean consistent with the signature field. An envelope copied from any
    other record, receipt or rollup, fails here even when its own signature
    verifies.
    """
    if not isinstance(env, dict):
        return "envelope is not an object"
    if env.get("payloadType") != ENVELOPE_PAYLOAD_TYPE:
        return "envelope payloadType is not %r" % ENVELOPE_PAYLOAD_TYPE
    payload = env.get("payload")
    if not isinstance(payload, str) or not payload:
        return "envelope payload is missing or not a string"
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return "envelope payload is not strict base64"
    if base64.b64encode(raw).decode("ascii") != payload:
        return "envelope payload is not canonical base64"
    try:
        expected = envelope_payload_bytes(body)
    except (TypeError, ValueError) as exc:
        return "body cannot be canonicalised (%s)" % type(exc).__name__
    if raw != expected:
        return ("envelope payload is not the exact canonical bytes of this "
                "record's body")
    advertised = env.get("digest")
    if advertised is not None and advertised != hashlib.sha256(raw).hexdigest():
        return "envelope digest does not match its payload"
    signed = env.get("signed")
    if not isinstance(signed, bool):
        return "envelope 'signed' marker is not a boolean"
    sig = env.get("signature")
    if signed and (not isinstance(sig, str) or not sig):
        return "envelope claims signed=true but carries no signature"
    if not signed and sig != "":
        return "envelope claims signed=false but carries a signature"
    return None


def _signature_state(record: Dict[str, Any], body: Dict[str, Any],
                     pubkey_pem: Optional[bytes]) -> Tuple[str, str]:
    """Return (state, detail) for one receipt or rollup record.

    state is one of SIGNATURE_STATES, or SIG_FAIL.
    """
    present = record.get("signature_present")
    env = record.get("signature")
    if not isinstance(present, bool):
        return (SIG_FAIL, "signature_present is not a boolean")
    if not present:
        if env is not None:
            return (SIG_FAIL, "signature_present is false but an envelope "
                    "is attached")
        return (SIG_UNCAPPED,
                str(record.get("signature_note") or "no signature present"))
    if env is None:
        return (SIG_FAIL, "signature_present asserted but envelope is null")
    unbound = check_envelope_binding(env, body)
    if unbound:
        return (SIG_FAIL, unbound)
    if not env["signed"]:
        return (SIG_UNSIGNED_HONEST, "unsigned-honest")
    try:
        from szl_receipt import verify_receipt
    except Exception:  # noqa: BLE001
        return (SIG_UNCHECKED, "szl-receipt not installed; signature not checked")
    if not pubkey_pem:
        return (SIG_UNCHECKED, "no public key supplied; signature not checked")
    try:
        ok, msg = verify_receipt(env, pubkey_pem)
    except Exception as exc:  # noqa: BLE001
        return (SIG_FAIL, "signature check raised %s" % type(exc).__name__)
    if ok:
        return (SIG_SIGNED_VERIFIED, msg)
    return (SIG_FAIL, msg)


def _canon_field(d: Dict[str, Any], key: str) -> str:
    return canonical_json(d[key]) if key in d else _ABSENT


def _prev_digest(records: List[Any], i: int) -> Optional[str]:
    if i == 0:
        return GENESIS_PREV
    prev = records[i - 1]
    return prev.get("digest") if isinstance(prev, dict) else None


def verify_store(store_dir: str,
                 pubkey_pem: Optional[bytes] = None) -> Dict[str, Any]:
    """Verify every per-inference receipt, both chains, and every rollup.

    Supplying *pubkey_pem* requires authentication: a store that is intact
    but not fully signed-verified is UNAUTHENTICATED rather than
    INTEGRITY-ONLY. Neither is ever VERIFIED.
    """
    result: Dict[str, Any] = {
        "store_dir": store_dir,
        "state": None,
        "authentication_required": bool(pubkey_pem),
        "receipts_checked": 0,
        "signed_verified": 0,
        "unsigned_honest": 0,
        "uncapped": 0,
        "signature_unchecked": 0,
        "rollups_checked": 0,
        "rollup_signatures": {s: 0 for s in SIGNATURE_STATES},
        "rollups": [],
        "details": [],
    }
    failed = []

    def fail(detail: str) -> None:
        failed.append(detail)
        result["details"].append("FAIL: " + detail)

    try:
        receipts = _load_jsonl(os.path.join(store_dir, "receipts.jsonl"))
        rollups = _load_jsonl(os.path.join(store_dir, "rollups.jsonl"))
    except (OSError, ValueError) as exc:
        fail("store is not readable as JSON lines (%s)" % type(exc).__name__)
        return _finish(result, failed)
    if not receipts and not rollups:
        result["state"] = STATE_INCOMPLETE
        result["details"].append("no receipts found in store — INCOMPLETE, never PASS")
        return _finish(result, failed)

    # digest -> (chain index, record, signature state), passing receipts only
    verified: Dict[str, Tuple[int, Dict[str, Any], str]] = {}

    def check_receipt(i: int, rec: Any) -> Optional[str]:
        if not isinstance(rec, dict) or not isinstance(rec.get("body"), dict):
            return "receipt %d missing body" % i
        body = rec["body"]
        claimed = rec.get("digest")
        actual = digest_body(body)
        if claimed != actual:
            return ("receipt %d digest mismatch: tampering or corruption "
                    "(claimed %.16s… actual %.16s…)" % (i, claimed or "", actual))
        if body.get("predicate_type") != PREDICATE_TYPE or "kind" in body:
            return ("receipt %d is not a per-inference energy receipt "
                    "(cross-kind record)" % i)
        if body.get("prev") != _prev_digest(receipts, i):
            return "receipt %d chain break: prev does not match previous digest" % i
        state, detail = _signature_state(rec, body, pubkey_pem)
        if state == SIG_FAIL:
            return "receipt %d signature: %s" % (i, detail)
        result[_RECEIPT_COUNTERS[state]] += 1
        result["receipts_checked"] += 1
        verified[actual] = (i, rec, state)
        return None

    for i, rec in enumerate(receipts):
        try:
            err = check_receipt(i, rec)
        except Exception as exc:  # noqa: BLE001 - malformed content is a FAIL
            err = "receipt %d could not be checked (%s)" % (i, type(exc).__name__)
        if err:
            fail(err)

    def rollup_members(j: int, body: Dict[str, Any]):
        day = body.get("date")
        if not isinstance(day, str) or not day:
            return "rollup %d has no date" % j
        listed = body.get("member_digests")
        if not isinstance(listed, list):
            return "rollup %d member_digests is not a list" % j
        members = []
        seen = set()
        last_index = -1
        for md in listed:
            if not isinstance(md, str) or md not in verified:
                return ("rollup %d references unknown member digest %.16s…"
                        % (j, md))
            if md in seen:
                return "rollup %d lists member %.16s… twice" % (j, md)
            seen.add(md)
            index, member, state = verified[md]
            if index <= last_index:
                return "rollup %d members are not in chain order" % j
            last_index = index
            issued = member["body"].get("issued_at")
            if not isinstance(issued, str) or not issued.startswith(day):
                return ("rollup %d member %.16s… was not issued on %s"
                        % (j, md, day))
            members.append((member, state))
        return members

    def check_rollup(j: int, rec: Any) -> Optional[str]:
        if not isinstance(rec, dict) or not isinstance(rec.get("body"), dict):
            return "rollup %d missing body" % j
        body = rec["body"]
        if digest_body(body) != rec.get("digest"):
            return "rollup %d digest mismatch: tampering or corruption" % j
        if (body.get("kind") != ROLLUP_KIND
                or body.get("predicate_type") != ROLLUP_PREDICATE_TYPE):
            return "rollup %d is not an energy daily rollup (cross-kind record)" % j
        if body.get("prev_rollup") != _prev_digest(rollups, j):
            return "rollup %d chain break in rollup spine" % j
        members = rollup_members(j, body)
        if isinstance(members, str):
            return members
        # The stored body must be exactly the rollup its listed members make.
        expected = rollup_body([m for m, _ in members], day=body["date"],
                               prev_rollup=body["prev_rollup"])
        mismatched = sorted(
            k for k in set(expected) | set(body)
            if _canon_field(body, k) != _canon_field(expected, k)
        )
        if mismatched:
            return ("rollup %d is inconsistent with its %d listed member "
                    "receipt(s): %s" % (j, len(members), ", ".join(mismatched)))
        state, detail = _signature_state(rec, body, pubkey_pem)
        if state == SIG_FAIL:
            return "rollup %d signature: %s" % (j, detail)
        member_states = {s: 0 for s in SIGNATURE_STATES}
        for _, member_state in members:
            member_states[member_state] += 1
        authenticated = (state == SIG_SIGNED_VERIFIED
                         and member_states[SIG_SIGNED_VERIFIED] == len(members))
        result["rollup_signatures"][state] += 1
        result["rollups_checked"] += 1
        result["rollups"].append({
            "index": j,
            "date": body["date"],
            "digest": rec["digest"],
            "signature": state,
            "member_count": len(members),
            "member_signatures": member_states,
            "assurance": "authenticated" if authenticated else "integrity-only",
        })
        return None

    for j, rec in enumerate(rollups):
        try:
            err = check_rollup(j, rec)
        except Exception as exc:  # noqa: BLE001 - malformed content is a FAIL
            err = "rollup %d could not be checked (%s)" % (j, type(exc).__name__)
        if err:
            fail(err)

    return _finish(result, failed)


def _finish(result: Dict[str, Any], failed: List[str]) -> Dict[str, Any]:
    if failed:
        result["state"] = STATE_FAIL
    elif result["state"] is None:
        receipts_short = result["receipts_checked"] - result["signed_verified"]
        rollups_short = (result["rollups_checked"]
                         - result["rollup_signatures"][SIG_SIGNED_VERIFIED])
        if receipts_short == 0 and rollups_short == 0:
            result["state"] = STATE_VERIFIED
        else:
            result["state"] = (STATE_UNAUTHENTICATED
                               if result["authentication_required"]
                               else STATE_INTEGRITY_ONLY)
            result["details"].append(
                "%s: integrity verified, but %d receipt(s) and %d rollup(s) "
                "are not signed-verified (%d unsigned-honest, %d UNCAPPED, "
                "%d SIGNATURE-UNCHECKED receipts)%s"
                % (result["state"], receipts_short, rollups_short,
                   result["unsigned_honest"], result["uncapped"],
                   result["signature_unchecked"],
                   "; a public key was supplied, so authentication is required"
                   if result["authentication_required"] else "")
            )
    result["summary"] = (
        "%d receipts checked (%d signed-verified, %d unsigned-honest, "
        "%d UNCAPPED, %d SIGNATURE-UNCHECKED), %d rollups checked "
        "(%d signed-verified) -> %s"
        % (result["receipts_checked"], result["signed_verified"],
           result["unsigned_honest"], result["uncapped"],
           result["signature_unchecked"], result["rollups_checked"],
           result["rollup_signatures"][SIG_SIGNED_VERIFIED], result["state"])
    )
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Offline verifier for "
                                 "szl-energy-attest per-inference receipts")
    ap.add_argument("store_dir")
    ap.add_argument("--pubkey", default=None,
                    help="PEM public key for signed receipts (optional; "
                    "supplying it requires every record to authenticate)")
    args = ap.parse_args(argv)
    pub = None
    if args.pubkey:
        with open(args.pubkey, "rb") as fh:
            pub = fh.read()
    res = verify_store(args.store_dir, pub)
    print(json.dumps(res, indent=2, sort_keys=True))
    return EXIT_CODES.get(res["state"], 1)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
