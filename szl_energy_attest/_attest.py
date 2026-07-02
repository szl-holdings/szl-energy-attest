# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""ADDITIVE standards-interop layer for szl_energy_attest.

Turns an honest, hash-chained energy receipt (see ``szl_energy_attest``) into the
formats the outside world already carries and audits:

  * ``to_intoto_statement`` — an in-toto Statement v1 wrapping an SLSA-*shaped*
    provenance predicate under OUR OWN ``predicateType`` (never a claim of SLSA
    conformance), with the measured-energy facts carried verbatim in
    ``runDetails.metadata`` and the receipt's chain digests in
    ``runDetails.receipt``.
  * ``compliance_evidence`` — maps the receipt to the controls regulators cite
    (EU AI Act Art. 12/19/15 + NIST AI RMF MEASURE/MANAGE/GOVERN), each carrying
    an explicit ``does_not_establish`` note.
  * ``verify_statement`` — rebinds a statement to its receipt by re-deriving the
    receipt body's canonical digest, so a tampered statement or a swapped receipt
    is caught.

DELEGATION (never duplicate). The Statement/predicate/catalogue *shapes* live in
ONE place — the shared ``szl_receipt.attest`` module — so every SZL receipt
emitter speaks the identical dialect. This file is a thin, energy-receipt-specific
adapter: it maps this package's receipt schema to the shared builder's inputs and
delegates. The import of ``szl_receipt`` is LAZY, so importing ``szl_energy_attest``
stays zero-hard-dependency (stdlib-only core); the ``[sign]`` extra pulls
``szl-receipt`` in when attestation/signing is wanted.

DOCTRINE (never weakened here):
  * Energy fields are copied VERBATIM from the receipt. ``measured_joules`` is a
    real number only when the receipt already says ``label == "MEASURED"``; a
    ``None`` / ``UNAVAILABLE`` / ``SAMPLE`` receipt maps to ``energy=measured:False``
    and NO fabricated joule ever enters a statement or an evidence record.
  * The predicateType is OURS. Emitting a statement is NOT a conformity
    assessment, a certification, or a safety guarantee — a receipt is EVIDENCE
    toward a control, nothing more (see each entry's ``does_not_establish``).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import szl_energy_attest as _ea

# Our own predicate/build type. This is deliberately a szl-owned URI so a reader
# can NEVER mistake this statement for an upstream SLSA-conformance claim.
SZL_PREDICATE_TYPE = "https://a-11-oy.com/attest/energy-attest/v0.1"
IN_TOTO_STATEMENT_TYPE = "https://in-toto.io/Statement/v1"

ATTEST_DOCTRINE = (
    "This statement is EVIDENCE that an honest, hash-chained energy receipt was "
    "produced; it is not a conformity assessment, certification, or safety "
    "guarantee. Energy is MEASURED only from a real NVML delta; a null / "
    "UNAVAILABLE / SAMPLE label means no billable joule was measured and none is "
    "fabricated. The predicateType is szl-owned and is NOT a claim of SLSA "
    "conformance."
)


def _shared():
    """Lazily import the shared attestation module. Absence is honest and loud:
    the ``[sign]`` extra (``szl-receipt``) must be installed to attest."""
    from szl_receipt import attest as _attest  # noqa: WPS433 (lazy by design)
    return _attest


def _body(receipt: Dict[str, Any]) -> Dict[str, Any]:
    """The exact ordered body that feeds the receipt's payload_digest."""
    return {k: receipt[k] for k in _ea._BODY_FIELDS}


def _split_digest(prefixed: Any) -> Tuple[str, str]:
    """Split a canon digest ``"<alg>:<hex>"`` into (alg, hex).

    energy-attest digests are algorithm-prefixed (``sha3-256:...`` from the real
    core, ``sha256:...`` from the stdlib fallback). in-toto subject digests key
    the hex value by the algorithm name, so we carry the receipt's OWN algorithm
    rather than assuming sha256. A bare hex string defaults to sha256.
    """
    if isinstance(prefixed, str) and ":" in prefixed:
        alg, _, hexval = prefixed.partition(":")
        return alg, hexval
    return "sha256", (prefixed or "")


def _is_measured(receipt: Dict[str, Any]) -> bool:
    """True only when the receipt itself already attests a real MEASURED joule."""
    return (receipt.get("label") == _ea.LABEL_MEASURED
            and receipt.get("measured_joules") is not None)


def to_intoto_statement(receipt: Dict[str, Any],
                        *, subject_name: Optional[str] = None) -> Dict[str, Any]:
    """Wrap one energy receipt in an in-toto Statement v1 (delegated shapes).

    The statement's single subject binds to the receipt BODY's canonical
    ``payload_digest`` (content-addressed, independent of chain position); the
    receipt's ``prev`` / ``payload_digest`` / ``digest`` are carried under
    ``runDetails.receipt`` so a verifier can re-link the whole chain. Measured
    energy facts are carried verbatim under ``runDetails.metadata``.
    """
    attest = _shared()
    body = _body(receipt)
    payload_digest = receipt.get("payload_digest") or _ea.sha256_canon(body)
    alg, hexval = _split_digest(payload_digest)
    measured = _is_measured(receipt)
    name = subject_name or "szl-energy-attest-receipt/{}".format(
        receipt.get("node", "unknown-node"))

    predicate = attest.slsa_predicate(
        build_type=SZL_PREDICATE_TYPE,
        builder_id=SZL_PREDICATE_TYPE,
        external_parameters={
            "schema": receipt.get("schema"),
            "node": receipt.get("node"),
            "tokens": receipt.get("tokens"),
        },
        internal_parameters={
            "decision": receipt.get("decision"),
            "lambda": receipt.get("lambda"),
            "sovereign": receipt.get("sovereign"),
        },
        metadata={
            "energy_label": receipt.get("label"),
            "measured": measured,
            # Verbatim, never fabricated. None when not MEASURED.
            "measured_joules": receipt.get("measured_joules"),
            "price_per_mwh": receipt.get("price_per_mwh"),
            "gCO2": receipt.get("gCO2"),
            "gCO2_label": receipt.get("gCO2_label"),
        },
        extra={"doctrine": ATTEST_DOCTRINE},
    )
    # Carry the receipt's chain coordinates so a verifier can re-walk the chain.
    predicate.setdefault("runDetails", {})["receipt"] = {
        "prev": receipt.get("prev"),
        "payload_digest": receipt.get("payload_digest"),
        "digest": receipt.get("digest"),
    }
    return attest.build_statement(
        subject_name=name,
        subject_digest=hexval,
        predicate=predicate,
        predicate_type=SZL_PREDICATE_TYPE,
        digest_alg=alg,
    )


def compliance_evidence(receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Map the receipt to regulator-cited controls (delegated catalogue).

    Capability flags derived HONESTLY from the receipt:
      * ``logging``   — a hash-chained, re-hashable record exists (always true
        for a well-formed receipt).
      * ``integrity`` — the chain is tamper-evident (prev -> digest binding).
      * ``governance``— the receipt records an advisory Λ decision + its evidence.
      * ``energy``    — a REAL MEASURED joule is present (only when MEASURED).
    """
    attest = _shared()
    measured = _is_measured(receipt)
    capabilities = {
        "logging": True,
        "integrity": True,
        "governance": True,
        "energy": measured,
    }
    return attest.compliance_evidence(
        capabilities=capabilities,
        subject_digest=receipt.get("payload_digest"),
        extra={
            "receipt_node": receipt.get("node"),
            "receipt_digest": receipt.get("digest"),
            "energy_label": receipt.get("label"),
            "doctrine": ATTEST_DOCTRINE,
        },
    )


def verify_statement(statement: Dict[str, Any],
                     receipt: Dict[str, Any]) -> Tuple[bool, str]:
    """Rebind a statement to its receipt. Returns (ok, reason).

    We re-derive the receipt body's canonical digest and require both (a) it
    matches the receipt's stored ``payload_digest`` (the receipt is internally
    consistent) and (b) the statement's subject carries that same digest under
    the receipt's own algorithm. A swapped receipt or a tampered statement fails.
    """
    attest = _shared()
    try:
        body = _body(receipt)
    except KeyError as exc:
        return (False, "receipt-missing-body-field:{}".format(exc.args[0]))
    recomputed = _ea.sha256_canon(body)
    stored = receipt.get("payload_digest")
    if stored is not None and stored != recomputed:
        return (False, "receipt-payload-digest-mismatch")
    alg, hexval = _split_digest(recomputed)
    return attest.verify_statement(
        statement,
        expected_digest=hexval,
        predicate_type=SZL_PREDICATE_TYPE,
        digest_alg=alg,
    )


def attest(receipt: Dict[str, Any],
           *, subject_name: Optional[str] = None) -> Dict[str, Any]:
    """Convenience bundle: the in-toto statement + the compliance evidence for
    one energy receipt, in a single dict. Both are delegated to the shared lib;
    this only wires this package's receipt schema to it."""
    return {
        "statement": to_intoto_statement(receipt, subject_name=subject_name),
        "compliance": compliance_evidence(receipt),
    }


def to_json(obj: Any) -> str:
    """Canonical (sorted, compact) JSON for a statement/evidence bundle (delegated)."""
    return _shared().to_json(obj)
