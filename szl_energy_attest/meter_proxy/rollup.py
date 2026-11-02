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
import math
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Union

from . import GENESIS_PREV, SPEC_VERSION
from .receipts import _sign_envelope, digest_body
from ._store import locked_store, read_records, validate_chain, write_records

_ROLLUP_PREDICATE = "https://a-11-oy.com/attest/energy-daily-rollup/v1"


def _receipt_utc_day(record: Dict[str, Any]) -> str:
    """Read a timezone-aware issuance timestamp as a UTC calendar day."""
    issued_at = record["body"].get("issued_at")
    if not isinstance(issued_at, str):
        raise ValueError("member issuance timestamp must be a string")
    try:
        # Python 3.9/3.10 do not accept Z in fromisoformat.
        parsed = datetime.fromisoformat(issued_at[:-1] + "+00:00"
                                       if issued_at.endswith("Z") else issued_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc).date().isoformat()
    except (ValueError, OverflowError) as exc:
        raise ValueError("member issuance timestamp must identify a UTC day") from exc


def _member_accounting(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive billing fields from the declared members, refusing invalid energy.

    This checks internal accounting consistency, not the truth of a meter's
    claim or completeness of a day's input snapshot.
    """
    counts = {"measured": 0, "estimated": 0, "unavailable": 0}
    values = {"MEASURED": [], "ESTIMATED": []}
    for record in members:
        energy = record["body"].get("energy")
        if not isinstance(energy, dict) or energy.get("state") not in (
            "MEASURED", "ESTIMATED", "UNAVAILABLE"
        ):
            raise ValueError("rollup member has invalid energy state")
        state = energy["state"]
        counts[state.lower()] += 1
        if state == "UNAVAILABLE":
            continue
        value = energy.get(state.lower() + "_joules")
        try:
            valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("rollup member energy must be finite and non-negative")
        values[state].append(value)
    # Preserve the pre-existing built-in sum semantics. Python 3.12+ uses
    # compensated float summation here; repeated += changes historical hashes.
    totals = {state: sum(items) for state, items in values.items()}
    for total in totals.values():
        try:
            finite_total = math.isfinite(total)
        except OverflowError:
            finite_total = False
        if not finite_total:
            raise ValueError("rollup energy sum must be finite")
    measured_sum = totals["MEASURED"] if counts["measured"] else None
    estimated_sum = totals["ESTIMATED"] if counts["estimated"] else None
    digests = [r["digest"] for r in members]
    return {
        "receipt_count": len(members),
        "counts": counts,
        "measured_joules_sum": measured_sum,
        "measured_joules_label": ("MEASURED-SUM-OVER-MEASURED-MEMBERS"
                                  if counts["measured"] else "UNAVAILABLE-NO-MEASURED-MEMBERS"),
        "estimated_joules_sum": estimated_sum,
        "estimated_joules_label": ("ESTIMATED-SUM-SEPARATE-SYNTHETIC-NEVER-BILLED-AS-MEASURED"
                                   if counts["estimated"] else None),
        "measured_kwh_sum": (measured_sum / 3_600_000.0 if measured_sum is not None else None),
        "member_digests": digests,
        "first_member_digest": digests[0] if digests else None,
        "last_member_digest": digests[-1] if digests else None,
    }


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
        if _receipt_utc_day(r) == day
    ]
    accounting = _member_accounting(members)

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
            **accounting,
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
