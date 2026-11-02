# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Bulk daily-rollup receipts, chained to the per-inference receipts beneath.

One rollup per UTC day: it aggregates the day's per-inference receipts — with
HONEST split accounting (measured joules summed only over MEASURED receipts;
unmeasured/estimated counts reported separately and NEVER blended into the
measured sum) — binds the exact list of member receipt digests, and is itself
signed and chained (``prev`` links to the previous rollup's digest; genesis
for the first).

This is the billable artifact: an operator billing $/kWh (Neuralwatt-shaped)
hands the customer one signed rollup whose members the customer can verify
offline, one receipt at a time.
"""
from __future__ import annotations

from copy import deepcopy
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Union

from . import GENESIS_PREV, SPEC_VERSION
from .receipts import _sign_envelope, digest_body
from ._store import locked_store, read_records, validate_chain, write_records

_ROLLUP_PREDICATE = "https://a-11-oy.com/attest/energy-daily-rollup/v1"


def build_daily_rollup(
    records: List[Dict[str, Any]],
    *,
    store_dir: str,
    for_date: Optional[str] = None,  # YYYY-MM-DD, defaults to today (UTC)
    private_key_pem: Optional[Union[str, bytes]] = None,
    rollups_file: str = "rollups.jsonl",
) -> Dict[str, Any]:
    """Aggregate one UTC day's receipts into one signed, chained rollup."""
    day = for_date if for_date is not None else datetime.now(timezone.utc).date().isoformat()
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError("rollup date must be YYYY-MM-DD")
    records = deepcopy(records)
    validate_chain(records, link="prev", genesis=GENESIS_PREV,
                   digest=digest_body, sequence=True)
    members = [
        r for r in records
        if (r.get("body", {}).get("issued_at") or "").startswith(day)
    ]
    digests = [r["digest"] for r in members]

    measured = [r for r in members
                if r.get("body", {}).get("energy", {}).get("state") == "MEASURED"]
    estimated = [r for r in members
                 if r.get("body", {}).get("energy", {}).get("state") == "ESTIMATED"]
    unmeasured = [r for r in members
                  if r.get("body", {}).get("energy", {}).get("state") == "UNAVAILABLE"]

    # Honest split accounting: the measured sum covers ONLY measured receipts.
    measured_sum = sum(
        r["body"]["energy"]["measured_joules"]
        for r in measured
        if isinstance(r["body"]["energy"].get("measured_joules"), (int, float))
    ) if measured else None
    estimated_sum = sum(
        r["body"]["energy"]["estimated_joules"]
        for r in estimated
        if isinstance(r["body"]["energy"].get("estimated_joules"), (int, float))
    ) if estimated else None

    path = os.path.join(store_dir, rollups_file)
    os.makedirs(store_dir, exist_ok=True)
    with locked_store(path):
        prev_rollups = read_records(path)
        validate_chain(prev_rollups, link="prev_rollup", genesis=GENESIS_PREV,
                       digest=digest_body)
        existing = next((r for r in prev_rollups if r["body"]["date"] == day), None)
        prev_digest = (existing["body"]["prev_rollup"] if existing else
                       prev_rollups[-1]["digest"] if prev_rollups else GENESIS_PREV)

        body: Dict[str, Any] = {
            "spec_version": SPEC_VERSION,
            "predicate_type": _ROLLUP_PREDICATE,
            "kind": "energy-daily-rollup",
            "date": day,
            "receipt_count": len(members),
            "counts": {
                "measured": len(measured),
                "estimated": len(estimated),
                "unavailable": len(unmeasured),
            },
            "measured_joules_sum": measured_sum,
            "measured_joules_label": ("MEASURED-SUM-OVER-MEASURED-MEMBERS"
                                      if measured else "UNAVAILABLE-NO-MEASURED-MEMBERS"),
            "estimated_joules_sum": estimated_sum,
            "estimated_joules_label": ("ESTIMATED-SUM-SEPARATE-SYNTHETIC-NEVER-BILLED-AS-MEASURED"
                                       if estimated else None),
            "measured_kwh_sum": (measured_sum / 3_600_000.0 if measured_sum is not None else None),
            "member_digests": digests,
            "first_member_digest": digests[0] if digests else None,
            "last_member_digest": digests[-1] if digests else None,
            "prev_rollup": prev_digest,
            "doctrine": ("measured, estimated, and unavailable energy are accounted "
                         "SEPARATELY; an estimate is never promoted into the "
                         "measured sum"),
        }
        record: Dict[str, Any] = {"body": body, "digest": digest_body(body)}
        if existing is not None:
            if record["digest"] != existing["digest"]:
                raise ValueError("day already sealed with different members or accounting")
            return existing
        env = _sign_envelope(body, private_key_pem)
        if env is None:
            record["signature"] = None
            record["signature_present"] = False
            record["signature_note"] = ("szl-receipt not importable: hash chain "
                                        "alone carries tamper-evidence")
        else:
            record["signature"] = env
            record["signature_present"] = True
            record["signature_note"] = None if env.get("signed") else (
                "UNSIGNED-honest: no signing key configured"
            )

        write_records(path, [*prev_rollups, record])
        return record
