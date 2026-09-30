# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Per-inference signed joule receipts for OpenAI-compatible inference.

The category-defining vertical for ``szl-energy-attest``: a FastAPI proxy that
wraps ANY OpenAI-compatible endpoint (``/v1/chat/completions``) and emits ONE
signed, hash-chained, offline-verifiable joule receipt PER INFERENCE, plus a
bulk daily-rollup receipt chained to the per-inference ones.

Honesty doctrine (identical to the parent package):

  * ``energy.state == "MEASURED"`` only when a real, fresh NVML joule delta
    (energy counter, or power-integral fallback) produced the number.
  * ``energy.state == "UNAVAILABLE"`` on CPU-only / sandboxed hosts:
    ``measured_joules`` is ``null`` — never a fabricated joule.
  * ``energy.state == "ESTIMATED"`` is a numerically SEPARATE field
    (``estimated_joules``), emitted ONLY by the clearly-labelled SYNTHETIC
    demo trace generator. Estimation never blends into ``measured_joules``.
  * Carbon intensity is a pass-through placeholder: ``UNAVAILABLE`` unless a
    grid-API key is provided via environment; never default-modelled.
  * Signatures are DSSE / ECDSA-P256 via the shared ``szl-receipt`` library.
    Keyless => UNSIGNED-honest envelope (``signed=False``). No fake signature,
    ever. If ``szl-receipt`` is not importable, the honest fallback records
    ``signature_present: false, signature_note: UNCAPPED-import`` and the hash
    chain alone carries tamper-evidence.

Layout:

    meter.py     — NVML measurement adapter (honest capability states)
    grid.py      — key-gated carbon-intensity provider (UNAVAILABLE without key)
    receipts.py  — per-inference receipt issuance, hashing, DSSE signing, store
    rollup.py    — daily bulk-rollup receipts chained to per-inference receipts
    proxy.py     — FastAPI OpenAI-compatible proxy emitting one receipt/call
    verifier.py  — offline verifier CLI: chain + signatures + rollup linkage
    demo.py      — clearly-labelled SYNTHETIC demo trace generator + live proof
"""

SPEC_VERSION = "szl-energy-proxy/1.0"
PREDICATE_TYPE = "https://a-11-oy.com/attest/energy-inference/v1"
GENESIS_PREV = "0" * 64

__version__ = "1.0.0"

from .meter import EnergyState, measure_inference_energy  # noqa: F401
from .receipts import ReceiptIssuer, canonical_json, digest_body  # noqa: F401
from .rollup import build_daily_rollup  # noqa: F401
