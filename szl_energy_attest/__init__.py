# SPDX-License-Identifier: Apache-2.0
# © 2026 Lutar, Stephen P. — SZL Holdings · ORCID 0009-0001-0110-4173
"""szl_energy_attest — attestable energy receipts for governed compute.

WHAT THIS IS (and is NOT)
-------------------------
This is the *packaging surface* for one genuinely-real capability: turning a unit
of governed compute into an **attestable energy receipt** — a small, canonical,
hash-chained JSON record that says, honestly, how much energy the work MEASURED
(real NVML joules) or, when no GPU/exporter is present, that the energy is
``UNAVAILABLE`` (never a fabricated number). The receipt is re-hashable offline by
anyone and links to the previous receipt (``prev`` -> ``digest``), so a tampered
field or a reordered entry breaks the chain.

It does NOT execute inference and it does NOT invent joules. It WRAPS the real
SZL energy core (``szl_energy_core`` / ``szl_cheapest_watt``) when that is
importable, and otherwise falls back to a byte-identical, pure-stdlib canonical
hash so the receipt chain still verifies on a CPU-only box — with the energy
fields correctly ``null`` and labeled ``UNAVAILABLE``.

DOCTRINE (never weakened here)
------------------------------
  * MEASURED joules only. ``measured_joules`` is a real number ONLY when a real,
    fresh NVML/exporter delta produced it (decided by the core's joule-truth, not
    by a flag). With no GPU it is ``None`` and ``label == "UNAVAILABLE"``.
  * Never fabricate a joule, a price, a carbon figure, or a receipt.
  * Λ = Conjecture 1 — advisory only. The receipt records a *decision* and its
    evidence; it never claims certainty or "sovereign=true".
  * Honest BLOCKED beats fake green: a receipt with ``UNAVAILABLE`` energy that
    still hash-verifies is the correct, shippable artifact on hardware that cannot
    measure — we publish that, not a green number we cannot stand behind.

Pure stdlib for the fallback path (hashlib + json). See ``SPEC.md`` for the schema.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

__version__ = "0.3.0"

GENESIS_PREV = "0" * 64

LABEL_MEASURED = "MEASURED"
LABEL_UNAVAILABLE = "UNAVAILABLE"   # no GPU / no fresh exporter delta on this box
LABEL_SAMPLE = "SAMPLE"             # real CPU work ran, but energy is NOT billable/MEASURED
LABEL_UNAVAILABLE_GCO2 = "UNAVAILABLE_NO_GRID_INTENSITY"

# Joules per kWh — for the HONEST gCO2 = energy_kWh * grid_intensity computation.
JOULES_PER_KWH = 3_600_000.0

# The exact ordered set of body fields that are hashed into payload_digest. Kept
# as a single source of truth so build_receipt, verify_chain, and the standalone
# verify_receipt_offline can never drift apart.
_BODY_FIELDS = (
    "schema", "measured_joules", "label", "tokens", "node",
    "price_per_mwh", "gCO2", "gCO2_label", "decision", "note",
    "lambda", "sovereign",
)


_ORGAN = "szl-energy-attest"


def _maybe_sign(body: Dict[str, Any],
                sign_key: Optional[Any],
                organ: str) -> Optional[Dict[str, Any]]:
    """ADDITIVE szl-receipt DSSE/ECDSA-P256 signature over the receipt *body*.

    Returns a signature envelope from ``szl_receipt.sign_receipt`` covering the
    exact body that feeds ``payload_digest``, or ``None`` when szl-receipt is
    not installed (the package then behaves exactly as before — stdlib-only).
    Doctrine: with no *sign_key* the envelope is UNSIGNED-honest
    (``signed=False``); a signature is NEVER fabricated. This per-receipt
    ECDSA-P256 signature is additive and independent of the hash chain and of
    the existing chain-level HMAC ``sign_chain`` hook.
    """
    try:
        from szl_receipt import Receipt, sign_receipt
    except Exception:  # noqa: BLE001 - signing is optional; absence is honest
        return None
    return sign_receipt(Receipt(kind="energy-attest", body=body),
                        sign_key, organ=organ)


def _finite(x: Any) -> Optional[float]:
    """Return x as a finite float, or None.

    Honesty gate for every numeric input: bool / non-number / NaN / +/-inf /
    non-coercible -> None (absent), NEVER a fabricated or garbage number. NaN and
    inf are floats, so a bare isinstance check is insufficient and dangerous: a
    NaN would both masquerade as a real reading AND make the receipt unparseable
    by a strict (allow_nan=False) third-party verifier, breaking attestability.
    """
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    xf = float(x)
    return xf if math.isfinite(xf) else None

# ---------------------------------------------------------------------------
# Wiring to the real SZL energy core. We IMPORT/WRAP — never duplicate.
#   1. Prefer szl_energy_core (Dev2's runnable core) and use ITS canonical hash
#      (SHA3-256) so receipts share the platform hash math + measure_energy().
#   2. Else prefer szl_cheapest_watt (the real placement+receipt module, sha256).
#   3. Else fall back to a byte-identical local canonical sha256 so the package
#      is self-contained and verifies offline on a CPU-only box.
# Within a single chain the hash function is fixed, so receipts minted and
# re-verified by the SAME source always reproduce identical digests.
# ---------------------------------------------------------------------------
_CANON_SOURCE = "local-fallback"
_CORE = None  # the szl_energy_core module, when importable


def _local_canon(obj: Dict[str, Any]) -> str:
    # allow_nan=False is REQUIRED for attestability: default json emits the
    # non-standard NaN/Infinity tokens that a strict third-party verifier cannot
    # parse. A non-finite float must never reach the hasher (screened upstream).
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode()
    ).hexdigest()


def _resolve_canon():
    global _CORE
    # Make sibling source dirs importable when running from the repo tree.
    for p in ("/home/user/workspace/szl_energy_core",
              "/home/user/workspace/szl_source"):
        if p not in sys.path:
            sys.path.append(p)
    # 1. runnable core (Dev2): wrap its canonical hash + measure_energy.
    try:
        import szl_energy_core as _core  # type: ignore
        fn = getattr(_core, "sha3_canon", None) or getattr(_core, "sha256_canon", None)
        if callable(fn):
            _CORE = _core
            return fn, "szl_energy_core"
    except Exception:
        pass
    # 2. real cheapest-watt receipt module
    try:
        import szl_cheapest_watt as _cw  # type: ignore
        fn = getattr(_cw, "sha256_canon", None)
        if callable(fn):
            return fn, "szl_cheapest_watt"
    except Exception:
        pass
    # 3. byte-identical local fallback
    return _local_canon, "local-fallback"


sha256_canon, _CANON_SOURCE = _resolve_canon()


def canon_source() -> str:
    """Which real module (if any) is providing the canonical hash for receipts."""
    return _CANON_SOURCE


# ---------------------------------------------------------------------------
# Energy measurement. MEASURED only from a REAL NVML reading. On a CPU-only box
# pynvml is absent -> we return (None, UNAVAILABLE), honestly. We NEVER synthesize
# a joule. If the core/operator exposes a measured per-job joule reading, a caller
# passes it in via measure_joules(reading=...) — we only label it MEASURED.
# ---------------------------------------------------------------------------
def nvml_available() -> bool:
    """True iff a real NVML library AND a GPU are present on THIS box.
    Delegates to the runnable core when present, else probes pynvml directly."""
    if _CORE is not None and hasattr(_CORE, "nvml_available"):
        try:
            return bool(_CORE.nvml_available())
        except Exception:
            return False
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        n = pynvml.nvmlDeviceGetCount()
        pynvml.nvmlShutdown()
        return n > 0
    except Exception:
        return False


def measure_block(device_index: int = 0):
    """Context manager that MEASURES the energy of the enclosed block via the
    runnable core's real NVML delta path (``szl_energy_core.measure_energy``),
    when the core is importable. On a CPU-only box the core honestly yields
    joules=None / label=UNAVAILABLE. Returns the core's context manager; its
    ``.result`` carries ``.joules`` and ``.label`` after the block exits.

    Falls back to a no-op measurement (None/UNAVAILABLE) when the core is absent,
    so callers can always use the same pattern without fabricating a joule.
    """
    if _CORE is not None and hasattr(_CORE, "measure_energy"):
        return _CORE.measure_energy(device_index=device_index)

    class _NoopMeasure:
        def __enter__(self):
            self.result = type("M", (), {"joules": None, "label": LABEL_UNAVAILABLE})()
            return self
        def __exit__(self, *a):
            return False
    return _NoopMeasure()


def measure_joules(reading: Optional[float] = None,
                   label: Optional[str] = None) -> Tuple[Optional[float], str]:
    """Return (measured_joules, label).

    * If ``reading`` is a real MEASURED joule delta handed in by the core's
      joule-truth path AND label is MEASURED -> (float(reading), "MEASURED").
    * If NVML is unavailable on this box -> (None, "UNAVAILABLE").
    * Otherwise -> (None, "SAMPLE"): real work may have run, but its energy is
      NOT a billable MEASURED joule, so we never report a number.

    This function NEVER fabricates a joule. No GPU => no number.
    """
    if reading is not None and label == LABEL_MEASURED:
        return float(reading), LABEL_MEASURED
    # Prefer the runnable core's real measurement path when available.
    if _CORE is not None and hasattr(_CORE, "measure_energy"):
        try:
            with _CORE.measure_energy() as m:
                pass  # no synthetic work; this reflects this box's real NVML state
            res = getattr(m, "result", None)
            j = getattr(res, "joules", None)
            lab = getattr(res, "label", None)
            if lab == LABEL_MEASURED and j is not None:
                return float(j), LABEL_MEASURED
            if lab in (LABEL_SAMPLE, LABEL_MEASURED, LABEL_UNAVAILABLE) and lab:
                return None, lab
        except Exception:
            pass
    if not nvml_available():
        return None, LABEL_UNAVAILABLE
    return None, LABEL_SAMPLE


# ---------------------------------------------------------------------------
# The receipt. A minimal, honest, re-hashable, hash-chained record. Schema is
# documented in SPEC.md. Every field is either a MEASURED fact or an explicit
# null with a truthful label.
# ---------------------------------------------------------------------------
def compute_gco2(measured_joules: Optional[float],
                 label: str,
                 grid_intensity_gco2_per_kwh: Optional[float]
                 ) -> Tuple[Optional[float], str]:
    """HONEST grams-CO2: gCO2 = energy_kWh * grid_intensity (gCO2/kWh).

    Same formula as Zeus / CodeCarbon / GSF Carbon-Aware SDK, but a carbon number
    is returned ONLY when BOTH (a) joules are genuinely MEASURED (label==MEASURED,
    finite, > 0) AND (b) a real, finite grid intensity is supplied. Otherwise
    (None, label) — carbon is NEVER fabricated or assumed from a default grid mix.
    """
    j = _finite(measured_joules)
    gi = _finite(grid_intensity_gco2_per_kwh)
    if label != LABEL_MEASURED or j is None or j <= 0:
        return None, LABEL_UNAVAILABLE
    if gi is None or gi < 0:
        return None, LABEL_UNAVAILABLE_GCO2
    return (j / JOULES_PER_KWH) * gi, LABEL_MEASURED


def build_receipt(*,
                  tokens: int,
                  node: str,
                  measured_joules: Optional[float] = None,
                  label: str = LABEL_UNAVAILABLE,
                  price_per_mwh: Optional[float] = None,
                  gco2: Optional[float] = None,
                  gco2_label: Optional[str] = None,
                  grid_intensity_gco2_per_kwh: Optional[float] = None,
                  decision: str = "no_choice",
                  prev: str = GENESIS_PREV,
                  note: str = "",
                  sign_key: Optional[Any] = None,
                  organ: str = _ORGAN) -> Dict[str, Any]:
    """Mint one attestable energy receipt.

    measured_joules is a real number ONLY when label == MEASURED *and* it is a
    finite, positive value. price_per_mwh is passed through verbatim from a live
    meter or left None — never assumed, never NaN/inf.

    Carbon (gCO2): if ``grid_intensity_gco2_per_kwh`` is supplied it is computed
    HONESTLY via compute_gco2() (only for MEASURED joules); else an explicit
    ``gco2`` may be passed through verbatim from a real source. A non-finite gco2
    is dropped to None. With no MEASURED joules or no real intensity, gCO2 is None
    with a truthful gCO2_label.

    The returned dict carries its own ``digest`` (canonical hash of the receipt
    body bound to ``prev``), so the next receipt sets prev = this digest.
    """
    # 1. Joules: finite + MEASURED-only. A non-MEASURED label or non-finite value
    #    can NEVER carry a joule number.
    mj = _finite(measured_joules)
    if label != LABEL_MEASURED or mj is None or mj <= 0:
        mj = None

    # 2. Carbon: prefer honest computation from a supplied grid intensity; else a
    #    verbatim real gco2; else null. Never fabricated.
    if grid_intensity_gco2_per_kwh is not None:
        g, g_label = compute_gco2(mj, label, grid_intensity_gco2_per_kwh)
    elif gco2 is not None:
        gv = _finite(gco2)
        if gv is not None and mj is not None and label == LABEL_MEASURED:
            g, g_label = gv, LABEL_MEASURED
        else:
            g, g_label = None, (gco2_label or LABEL_UNAVAILABLE_GCO2)
    else:
        g, g_label = None, (gco2_label or LABEL_UNAVAILABLE_GCO2)

    body = {
        "schema": "szl_energy_attest/receipt@1",
        "measured_joules": (None if mj is None else round(mj, 6)),
        "label": label,
        "tokens": int(tokens) if isinstance(tokens, int) and not isinstance(tokens, bool)
        else (int(_finite(tokens)) if _finite(tokens) is not None else 0),
        "node": str(node),
        "price_per_mwh": _finite(price_per_mwh),
        "gCO2": (None if g is None else round(g, 6)),
        "gCO2_label": g_label,
        "decision": decision,
        "note": note,
        "lambda": "Conjecture 1 (advisory; trust never 100%)",
        "sovereign": False,
    }
    payload_digest = sha256_canon(body)
    digest = sha256_canon({"prev": prev, "payload_digest": payload_digest})
    receipt = dict(body)
    receipt["prev"] = prev
    receipt["payload_digest"] = payload_digest
    receipt["digest"] = digest
    # ADDITIVE szl-receipt signature over the body. Does not touch the body /
    # payload_digest / digest, so verify_chain + verify_receipt_offline (which
    # only read _BODY_FIELDS) are unaffected. Keyless => UNSIGNED-honest.
    sig = _maybe_sign(body, sign_key, organ)
    if sig is not None:
        receipt["signature"] = sig
    return receipt


def verify_chain(receipts: List[Dict[str, Any]]) -> Tuple[bool, int, int]:
    """Re-walk a chain offline. Returns (ok, length, first_break_index).

    Each receipt must (a) re-hash its body to payload_digest, (b) bind
    (prev, payload_digest) to digest, and (c) have prev == previous digest
    (genesis = 64 zeros). Any mismatch — INCLUDING a malformed/missing-field or
    non-finite-number receipt — returns ok=False at the first break, never a crash.
    """
    prev = GENESIS_PREV
    for i, r in enumerate(receipts):
        try:
            if not isinstance(r, dict):
                return (False, len(receipts), i)
            # Missing any body/chain field, or a non-finite number in the body,
            # is a hard break (sha256_canon uses allow_nan=False). We catch it as
            # a graceful failure so a third party can never crash our verifier.
            body = {k: r[k] for k in _BODY_FIELDS}
            pd = sha256_canon(body)
            dg = sha256_canon({"prev": r["prev"], "payload_digest": pd})
            if (pd != r["payload_digest"] or dg != r["digest"]
                    or r["prev"] != prev):
                return (False, len(receipts), i)
            prev = r["digest"]
        except (KeyError, TypeError, ValueError):
            return (False, len(receipts), i)
    return (True, len(receipts), -1)


# ===========================================================================
# UPGRADE 2 — standalone, ZERO-dependency offline verifier.
# A third party can copy THIS ONE FUNCTION (plus stdlib) and verify any SZL
# attestable receipt chain with NO szl_* imports and NO torch. This is the whole
# point of "attestable": integrity is checkable by anyone, anywhere, forever.
# It re-implements the canonical hash locally and auto-detects sha3-256/sha256
# from each receipt's own digest prefix, so it works regardless of which canon
# source minted the chain.
# ===========================================================================
def verify_receipt_offline(receipt_json) -> dict:
    """Verify a single receipt OR a chain, using ONLY the Python stdlib.

    SELF-CONTAINED: this function imports its own stdlib (hashlib/json/math) and
    uses only built-in types, so an auditor can copy it verbatim into any file
    with ZERO szl_* / torch / third-party dependencies and verify a chain.

    Accepts a JSON string, a dict (one receipt), or a list of dicts (a chain).
    Returns a plain dict::

        {"ok": bool, "length": int, "first_break_index": int,
         "reason": str, "honesty_ok": bool}

    No szl_energy_* import, no torch, no network. Copy-pasteable by an auditor.
    Also re-checks the honesty invariant: any receipt whose label != MEASURED but
    whose measured_joules is non-null fails honesty (and is reported), and any
    non-finite number anywhere is a hard fail.
    """
    import hashlib as _hl
    import json as _json
    import math as _math

    GEN = "0" * 64
    BODY = ("schema", "measured_joules", "label", "tokens", "node",
            "price_per_mwh", "gCO2", "gCO2_label", "decision", "note",
            "lambda", "sovereign")
    # Back-compat: receipts minted before gCO2_label existed omit that field.
    BODY_LEGACY = tuple(f for f in BODY if f != "gCO2_label")

    def _has_nonfinite(o) -> bool:
        if isinstance(o, bool):
            return False
        if isinstance(o, float):
            return not _math.isfinite(o)
        if isinstance(o, dict):
            return any(_has_nonfinite(v) for v in o.values())
        if isinstance(o, (list, tuple)):
            return any(_has_nonfinite(v) for v in o)
        return False

    def _canon(prefix, obj):
        blob = _json.dumps(obj, sort_keys=True, separators=(",", ":"),
                           allow_nan=False).encode()
        algo = _hl.sha3_256 if prefix == "sha3-256" else _hl.sha256
        return prefix + ":" + algo(blob).hexdigest()

    if isinstance(receipt_json, str):
        try:
            data = _json.loads(receipt_json)
        except Exception as e:
            return {"ok": False, "length": 0, "first_break_index": 0,
                    "reason": "unparseable JSON: %s" % e, "honesty_ok": False}
    else:
        data = receipt_json
    # Allow the CLI envelope {"receipts": [...]} as well as a bare list/dict.
    if isinstance(data, dict) and "receipts" in data and "digest" not in data:
        data = data["receipts"]
    receipts = data if isinstance(data, list) else [data]

    prev = GEN
    honesty_ok = True
    for i, r in enumerate(receipts):
        try:
            if not isinstance(r, dict):
                return {"ok": False, "length": len(receipts),
                        "first_break_index": i, "reason": "receipt is not an object",
                        "honesty_ok": honesty_ok}
            fields = BODY if "gCO2_label" in r else BODY_LEGACY
            body = {k: r[k] for k in fields}
            if _has_nonfinite(body) or _has_nonfinite(r.get("prev")):
                return {"ok": False, "length": len(receipts),
                        "first_break_index": i,
                        "reason": "non-finite number in receipt (un-attestable)",
                        "honesty_ok": False}
            # Honesty invariant: non-MEASURED label may not carry a joule.
            if r.get("label") != "MEASURED" and r.get("measured_joules") is not None:
                honesty_ok = False
            prefix = str(r.get("digest", "sha256:")).split(":", 1)[0]
            pd = _canon(prefix, body)
            dg = _canon(prefix, {"prev": r["prev"], "payload_digest": pd})
            if (pd != r["payload_digest"] or dg != r["digest"]
                    or r["prev"] != prev):
                return {"ok": False, "length": len(receipts),
                        "first_break_index": i,
                        "reason": "hash/link mismatch at index %d" % i,
                        "honesty_ok": honesty_ok}
            prev = r["digest"]
        except (KeyError, TypeError, ValueError) as e:
            return {"ok": False, "length": len(receipts),
                    "first_break_index": i,
                    "reason": "malformed receipt: %s" % e,
                    "honesty_ok": honesty_ok}
    return {"ok": True, "length": len(receipts), "first_break_index": -1,
            "reason": "chain verifies; every receipt re-hashes and links cleanly",
            "honesty_ok": honesty_ok}


# ===========================================================================
# UPGRADE 3 — optional cosign/DSSE-style DETACHED signature hook.
# Absent a real key, a receipt chain is HONEST-BUT-UNSIGNED — the hash chain
# already proves integrity + ordering. We NEVER fabricate a signature. When a
# real key is present (env SZL_ATTEST_HMAC_KEY for the built-in stdlib HMAC
# backend, or a caller-supplied signer), we emit a DSSE-shaped detached envelope.
# (HMAC is a real, verifiable MAC using stdlib only; a cosign/sigstore backend
# can be plugged in via the `signer` callable without changing the envelope.)
# ===========================================================================
LABEL_UNSIGNED = "UNSIGNED"
LABEL_SIGNED = "SIGNED"
_DSSE_PAYLOAD_TYPE = "application/vnd.szl.energy-attest.chain+json"


def sign_chain(receipts: List[Dict[str, Any]],
               key: Optional[bytes] = None,
               signer=None,
               key_id: str = "") -> Dict[str, Any]:
    """Produce a DSSE-style DETACHED signature envelope over a receipt chain.

    Honest contract:
      * No key and no signer (and no SZL_ATTEST_HMAC_KEY env) -> the envelope is
        clearly labeled ``"signature_label": "UNSIGNED"`` with ``signatures: []``.
        We NEVER emit a fake signature; the hash chain still proves integrity.
      * key (bytes) or SZL_ATTEST_HMAC_KEY env present -> a real HMAC-SHA256 over
        the canonical chain head digest, labeled ``SIGNED`` (backend ``hmac-sha256``).
      * signer callable present -> called as signer(pae_bytes) -> (sig_b64, key_id,
        backend); use this to plug in cosign/sigstore without changing the shape.

    The signature is DETACHED: it does not mutate the receipts, so the chain still
    re-hashes identically. ``verify_signature`` checks it.
    """
    import base64
    # The thing we sign: the chain's terminal digest (binds the whole chain) plus
    # length. DSSE PAE (pre-auth encoding) over a canonical payload.
    head = receipts[-1]["digest"] if receipts else GENESIS_PREV
    payload_obj = {"head": head, "length": len(receipts),
                   "payload_type": _DSSE_PAYLOAD_TYPE}
    payload = json.dumps(payload_obj, sort_keys=True, separators=(",", ":")).encode()
    pae = b"DSSEv1 %d %b %d %b" % (len(_DSSE_PAYLOAD_TYPE),
                                   _DSSE_PAYLOAD_TYPE.encode(),
                                   len(payload), payload)

    env: Dict[str, Any] = {
        "payloadType": _DSSE_PAYLOAD_TYPE,
        "payload_b64": base64.b64encode(payload).decode(),
        "signatures": [],
        "signature_label": LABEL_UNSIGNED,
        "note": ("HONEST-BUT-UNSIGNED: no signing key present; the hash chain "
                 "alone proves integrity and ordering. No signature is fabricated."),
    }

    if signer is not None:
        sig_b64, kid, backend = signer(pae)
        env["signatures"] = [{"sig": sig_b64, "keyid": kid, "backend": backend}]
        env["signature_label"] = LABEL_SIGNED
        env["note"] = "SIGNED via caller-supplied signer over DSSE PAE."
        return env

    if key is None:
        env_key = os.environ.get("SZL_ATTEST_HMAC_KEY")
        key = env_key.encode() if env_key else None
    if key:
        mac = hmac.new(key, pae, hashlib.sha256).hexdigest()
        env["signatures"] = [{"sig": mac, "keyid": key_id or "hmac-default",
                              "backend": "hmac-sha256"}]
        env["signature_label"] = LABEL_SIGNED
        env["note"] = ("SIGNED with a real HMAC-SHA256 over the DSSE PAE of the "
                       "chain head digest (stdlib MAC backend).")
    return env


def verify_signature(receipts: List[Dict[str, Any]],
                     envelope: Dict[str, Any],
                     key: Optional[bytes] = None) -> Dict[str, Any]:
    """Verify a DSSE-style detached envelope produced by sign_chain.

    Returns {"signed": bool, "valid": bool, "reason": str}. An UNSIGNED envelope
    is reported as signed=False, valid=True (honest: nothing to forge, chain still
    stands on its hash). A SIGNED HMAC envelope is checked against the key (arg or
    SZL_ATTEST_HMAC_KEY). Non-HMAC backends report signed=True, valid=None-style
    'backend not verifiable here' rather than a false PASS.
    """
    import base64
    if not envelope or envelope.get("signature_label") == LABEL_UNSIGNED \
            or not envelope.get("signatures"):
        return {"signed": False, "valid": True,
                "reason": "honest-but-unsigned; integrity rests on the hash chain"}
    try:
        payload = base64.b64decode(envelope["payload_b64"])
        ptype = envelope["payloadType"]
        pae = b"DSSEv1 %d %b %d %b" % (len(ptype), ptype.encode(),
                                       len(payload), payload)
        sig0 = envelope["signatures"][0]
        backend = sig0.get("backend")
        if backend != "hmac-sha256":
            return {"signed": True, "valid": False,
                    "reason": "backend %r not verifiable by this stdlib hook"
                    % backend}
        if key is None:
            env_key = os.environ.get("SZL_ATTEST_HMAC_KEY")
            key = env_key.encode() if env_key else None
        if not key:
            return {"signed": True, "valid": False,
                    "reason": "no key available to verify HMAC signature"}
        expect = hmac.new(key, pae, hashlib.sha256).hexdigest()
        ok = hmac.compare_digest(expect, sig0["sig"])
        return {"signed": True, "valid": ok,
                "reason": "HMAC %s" % ("matches" if ok else "MISMATCH")}
    except Exception as e:
        return {"signed": True, "valid": False, "reason": "verify error: %s" % e}


# ADDITIVE standards-interop layer (in-toto / SLSA-shaped statement + regulator
# mapping). The Statement/predicate/catalogue SHAPES are DELEGATED to the shared
# szl_receipt.attest lib; _attest.py only maps this package's receipt schema to
# it. Imported at the bottom so the names above (_BODY_FIELDS, sha256_canon) are
# already defined when the adapter binds to them. The szl_receipt import inside
# is lazy, so importing this package stays zero-hard-dependency (stdlib-only).
from ._attest import (  # noqa: E402
    attest,
    to_intoto_statement,
    compliance_evidence,
    verify_statement,
    to_json,
    IN_TOTO_STATEMENT_TYPE,
    SZL_PREDICATE_TYPE,
    ATTEST_DOCTRINE,
)

__all__ = [
    "__version__", "GENESIS_PREV",
    "LABEL_MEASURED", "LABEL_UNAVAILABLE", "LABEL_SAMPLE",
    "LABEL_UNAVAILABLE_GCO2", "LABEL_UNSIGNED", "LABEL_SIGNED",
    "JOULES_PER_KWH",
    "sha256_canon", "canon_source",
    "nvml_available", "measure_joules", "measure_block",
    "compute_gco2", "build_receipt", "verify_chain",
    "verify_receipt_offline", "sign_chain", "verify_signature",
    # standards-interop (delegated to szl_receipt.attest)
    "attest", "to_intoto_statement", "compliance_evidence",
    "verify_statement", "to_json",
    "IN_TOTO_STATEMENT_TYPE", "SZL_PREDICATE_TYPE", "ATTEST_DOCTRINE",
]
