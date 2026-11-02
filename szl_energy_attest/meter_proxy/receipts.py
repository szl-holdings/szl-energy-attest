# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Per-inference receipt issuance: hash chain + DSSE/ECDSA + durable store.

Each inference through the proxy emits ONE receipt:

  * a deterministic body (``SPEC_VERSION``, ``PREDICATE_TYPE``) carrying model
    id, token counts, MEASURED/UNAVAILABLE joules, wall-clock latency, the
    carbon-intensity placeholder, policy decision, and ``prev`` chain link;
  * a SHA-256 digest over the canonical body (tamper-evidence);
  * a DSSE envelope over the exact canonical body bytes, ECDSA-P256 signed via
    the shared ``szl-receipt`` library when a key is present, UNSIGNED-honest
    (``signed=False``) without one, and honestly *absent* with an explanatory
    note when ``szl-receipt`` is not installed;
  * logically append-only JSONL snapshots with a stable ``flock`` + atomic
    replacement + ``fsync`` before ACK
    (Flight Recorder law: LOCAL durability acknowledged; remote is a separate,
    visibly PENDING_SYNC concern — this package only ever claims local).

The digest is integrity, not authorship (Law: signature != truth). The DSSE
signature adds authenticity when a key exists. Both are checked offline by
``verifier.py``.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from . import GENESIS_PREV, PREDICATE_TYPE, SPEC_VERSION
from ._store import locked_store, read_records, validate_chain, write_records

_ORGAN = "szl-energy-attest-proxy"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_json(body: Dict[str, Any]) -> str:
    """Deterministic JSON used for hashing AND as the DSSE payload basis."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest_body(body: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _token_count(value: Any) -> Optional[int]:
    """Keep only genuine non-negative integer counts; never coerce evidence."""
    return value if type(value) is int and value >= 0 else None


def _sign_envelope(body: Dict[str, Any], private_key_pem: Optional[Union[str, bytes]]):
    """DSSE envelope via shared szl-receipt, with honest fallbacks.

      * key present     -> signed ECDSA-P256 DSSE envelope (cosign-compatible)
      * no key          -> UNSIGNED-honest envelope (signed=False, never faked)
      * szl-receipt absent -> None; the caller records the absence in prose
    """
    try:
        from szl_receipt import Receipt, sign_receipt
    except Exception:  # noqa: BLE001 - signing layer optional, absence is honest
        return None
    env = sign_receipt(Receipt(kind="energy-inference", body=body),
                       private_key_pem, organ=_ORGAN)
    return env


class ReceiptIssuer:
    """Issues chained, signed per-inference receipts and persists them."""

    def __init__(
        self,
        store_dir: str,
        private_key_pem: Optional[Union[str, bytes]] = None,
        receipts_file: str = "receipts.jsonl",
    ) -> None:
        self._lock = threading.RLock()
        self.store_dir = store_dir
        os.makedirs(store_dir, exist_ok=True)
        self._path = os.path.join(store_dir, receipts_file)
        self._priv = private_key_pem
        self._signing_importable = _sign_envelope({"probe": True}, None) is not None
        with locked_store(self._path):
            self._records = self._load()

    def _load(self):
        records = read_records(self._path)
        validate_chain(records, link="prev", genesis=GENESIS_PREV,
                       digest=digest_body, sequence=True)
        return records

    @property
    def records(self) -> List[Dict[str, Any]]:
        with self._lock, locked_store(self._path):
            self._records = self._load()
            return deepcopy(self._records)

    def issue(
        self,
        *,
        model: str,
        tokens_in: Optional[int],
        tokens_out: Optional[int],
        energy: Dict[str, Any],
        carbon: Dict[str, Any],
        latency_seconds: float,
        policy_decision: str = "allow",
        policy_reason: str = "metering proxy admits all inferences; metering is "
        "evidence-gathering, not enforcement (advisory, fail-open for traffic, "
        "fail-CLOSED for attestation claims)",
        requester: Optional[str] = None,
        synthetic: bool = False,
        provenance: str = "live",
    ) -> Dict[str, Any]:
        """Build, chain, sign, durably persist, and return one receipt."""
        tokens_in = _token_count(tokens_in)
        tokens_out = _token_count(tokens_out)
        with self._lock, locked_store(self._path):
            self._records = self._load()
            prev = self._records[-1]["digest"] if self._records else GENESIS_PREV
            seq = len(self._records)
            body: Dict[str, Any] = {
                "spec_version": SPEC_VERSION,
                "predicate_type": PREDICATE_TYPE,
                "receipt_id": str(uuid.uuid4()),
                "seq": seq,
                "issued_at": _utcnow(),
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "token_label": ("MEASURED" if tokens_in is not None
                                 and tokens_out is not None
                                 else "UNAVAILABLE"),
                "energy": deepcopy(energy),          # state MEASURED/UNAVAILABLE(+demo ESTIMATED)
                "latency_seconds": round(float(latency_seconds), 6),
                "latency_label": "MEASURED-WALLCLOCK-PROXY-SIDE",
                "carbon": deepcopy(carbon),          # REPORTED pass-through or UNAVAILABLE
                "policy_decision": policy_decision,
                "policy_reason": policy_reason,
                "requester": requester or "anonymous",
                "synthetic": bool(synthetic),
                "provenance": provenance,
                "prev": prev,
            }
            record: Dict[str, Any] = {"body": body, "digest": digest_body(body)}
            env = _sign_envelope(body, self._priv)
            if env is None:
                record["signature"] = None
                record["signature_present"] = False
                record["signature_note"] = (
                    "szl-receipt not importable in this environment; hash chain "
                    "alone carries tamper-evidence (honest UNCAPPED-import state)"
                )
            else:
                record["signature"] = env
                record["signature_present"] = True
                record["signature_note"] = None if env.get("signed") else (
                    "UNSIGNED-honest: no signing key configured"
                )
            write_records(self._path, [*self._records, record])
            self._records.append(record)
            return deepcopy(record)

    def rollup_source_range(self) -> List[Dict[str, Any]]:
        """A validated durable snapshot in chain order (rollup input)."""
        return self.records
