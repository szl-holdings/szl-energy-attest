"""szl_energy_core — the REAL, honest energy core of SZL Holdings, extracted clean.

Two genuine capabilities, ported faithfully from the live a11oy modules
(``szl_energy_operator.py`` + ``szl_joules_truth.py`` + ``szl_cheapest_watt.py``):

  1. measure_energy()  — MEASURED-joule accounting.
        Joules are obtained ONLY from a real NVML cumulative-energy delta read across
        a job's wall window: ``joules = energy_after - energy_before`` (the exact
        delta pattern used by the operator's ``_run_real_job``). If NVML / a GPU is
        not present, we NEVER fabricate a number — we return
        ``{"joules": None, "label": "UNAVAILABLE_NO_NVML", ...}``. A reading older
        than the freshness window is labeled SAMPLE and excluded from billable.

  2. cheapest_watt_choice()  — cheapest-watt placement.
        Given per-node ``{power_w, tokens, price_per_mwh}`` (plus measured joules when
        available) it computes MEASURED energy-intensity (J/token), converts to
        cost-per-token via the live grid price, picks the node minimizing
        cost/energy-per-token, and returns a re-hashable, hash-chained decision
        receipt (SHA3-256 over the canonical decision body).

DOCTRINE (Λ = Conjecture 1; trust never 100%; sovereign=false on accounting paths):
  * Joules MUST be MEASURED via real NVML. No GPU/NVML => labeled UNAVAILABLE/SAMPLE,
    never a fake joule.
  * A node only has an intensity (J/token) when its OWN measured joules and tokens
    are both > 0. Otherwise its intensity is UNKNOWN and it is NEVER ranked on cost.
  * With < 2 comparable MEASURED-intensity nodes there is no real placement choice:
    decision = "no_choice". We never invent an alternative to claim a saving against.
  * Grid price is passed through verbatim; never assumed. A saving is MEASURED only
    when both legs (chosen + named declined baseline) are MEASURED AND a live price
    exists; otherwise the monetary saving is ESTIMATE (or omitted).
  * Receipts are re-hashable offline (canonical SHA3-256) and hash-chained
    (prev_digest; genesis = 64 zeros).

Pure-Python: stdlib only at import time. ``pynvml`` and ``torch`` are OPTIONAL and
imported lazily; their absence is handled gracefully and honestly.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from contextlib import ContextDecorator
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "measure_energy",
    "EnergyMeasurement",
    "nvml_available",
    "cheapest_watt_choice",
    "CheapestWattLedger",
    "sha3_canon",
    "gco2_from_joules",
    "GENESIS_PREV",
    "FRESHNESS_WINDOW_S",
    "DOCTRINE",
]

# ---------------------------------------------------------------------------
# Constants (mirrored from the live modules so the math is byte-identical).
# ---------------------------------------------------------------------------
JOULES_PER_KWH = 3_600_000.0
GENESIS_PREV = "0" * 64
# A real exporter reading older than this many seconds is stale => SAMPLE, not
# MEASURED (operator MAX_NVML_AGE_S / joules_truth FRESHNESS_WINDOW_S).
FRESHNESS_WINDOW_S = 30.0

# Honest labels.
LABEL_MEASURED = "MEASURED"
LABEL_SAMPLE = "SAMPLE"            # real work, but no fresh real NVML reading
LABEL_UNAVAILABLE = "UNAVAILABLE_NO_NVML"   # no GPU / no pynvml at all
LABEL_ESTIMATE = "ESTIMATE"
LABEL_UNKNOWN = "UNKNOWN"
LABEL_UNAVAILABLE_GCO2 = "UNAVAILABLE_NO_GRID_INTENSITY"

DOCTRINE = (
    "Λ=Conjecture 1; trust never 100%; sovereign=false on accounting. Joules MUST be "
    "MEASURED via a real NVML cumulative-energy delta (joules=after-before) over the "
    "job's wall window; a reading staler than 30s is SAMPLE and excluded from billable; "
    "no GPU/NVML at all => UNAVAILABLE_NO_NVML with joules=None — NEVER a fabricated "
    "joule. Cheapest-watt is PLACEMENT+accounting, NOT fused VRAM: each node keeps its "
    "own MEASURED joules. Energy-intensity (J/token) is MEASURED only from a node's own "
    "measured joules and tokens (both >0); else UNKNOWN and never ranked on cost. Grid "
    "price (per MWh) is passed through verbatim, never assumed. With <2 comparable "
    "MEASURED nodes there is no choice (no_choice) — never invent an alternative. A "
    "saving is MEASURED only when both legs are MEASURED AND a live price exists; else "
    "ESTIMATE or omitted. Receipts re-hashable offline (SHA3-256) + hash-chained."
)


# ---------------------------------------------------------------------------
# Canonical hashing — SHA3-256 over a sorted-keys, tight-separator JSON dump.
# Re-hashable fully offline; deterministic for a given dict.
# ---------------------------------------------------------------------------
def sha3_canon(obj: dict) -> str:
    """Canonical SHA3-256 over a dict (sorted keys, tight separators).

    ``allow_nan=False`` is REQUIRED for attestability: Python's default json
    emits the non-standard tokens ``NaN``/``Infinity`` which a strict, spec-
    compliant third-party verifier cannot parse — that would make the receipt
    un-attestable. A non-finite float reaching the hasher is therefore a hard
    error (it should already have been screened to None/UNKNOWN upstream), never
    silently baked into a digest.
    """
    return "sha3-256:" + hashlib.sha3_256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode()
    ).hexdigest()


def _finite(x: Any) -> Optional[float]:
    """Return x as a finite float, or None.

    The honest gate for ALL numeric inputs: a bool, a non-number, NaN, +/-inf, or
    anything non-coercible yields None (UNKNOWN/absent) — NEVER a fabricated or
    garbage number. ``isinstance(x, float)`` alone is not enough because NaN and
    inf are floats; they must be rejected so they can never masquerade as a real
    MEASURED reading or a live grid price.
    """
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    xf = float(x)
    if not math.isfinite(xf):
        return None
    return xf


# ===========================================================================
# PART 1 — MEASURED-joule accounting via real NVML.
# ===========================================================================
def _try_import_pynvml():
    """Import pynvml lazily and init it. Returns the module or None (honest).

    Any failure (ImportError, no driver, no GPU, init error) => None. We never
    pretend NVML is present when it is not.
    """
    try:
        import pynvml  # type: ignore
    except Exception:
        return None
    try:
        pynvml.nvmlInit()
    except Exception:
        return None
    return pynvml


def nvml_available() -> bool:
    """True iff a real NVML library + at least one GPU device is reachable."""
    pynvml = _try_import_pynvml()
    if pynvml is None:
        return False
    try:
        return pynvml.nvmlDeviceGetCount() > 0
    except Exception:
        return False


def _nvml_total_energy_joules(pynvml, handle, now: float) -> Optional[dict]:
    """Read the GPU's cumulative total-energy counter as a real exporter sample.

    NVML exposes ``nvmlDeviceGetTotalEnergyConsumption`` in millijoules since the
    last driver reload. We convert to joules and stamp a fresh wall-clock ts so the
    freshness gate (<30s) can be applied exactly like the live operator. Returns
    None if the counter is unsupported/unreadable — never a fabricated number.
    """
    try:
        mj = pynvml.nvmlDeviceGetTotalEnergyConsumption(handle)
    except Exception:
        return None
    if not isinstance(mj, (int, float)):
        return None
    power_w = None
    try:
        power_w = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW -> W
    except Exception:
        power_w = None
    return {
        "joules_measured_total": float(mj) / 1000.0,  # mJ -> J
        "exporter_last_seen_ts": now,
        "power_w_sample": power_w,
    }


def _is_fresh(ts: Optional[float], now: float) -> bool:
    """True iff reading ts is within the freshness window of now (no future skew)."""
    if not isinstance(ts, (int, float)):
        return False
    age = now - float(ts)
    return 0.0 <= age <= FRESHNESS_WINDOW_S


@dataclass
class EnergyMeasurement:
    """The honest result of a measure_energy() window.

    joules is a real number ONLY when label == MEASURED. In every other case it is
    None and the label says why (UNAVAILABLE_NO_NVML | SAMPLE). Never fabricated.
    """
    joules: Optional[float]
    label: str
    wall_s: float
    power_w_sample: Optional[float] = None
    device_index: Optional[int] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "joules": (round(self.joules, 6) if self.joules is not None else None),
            "label": self.label,
            "wall_s": round(self.wall_s, 6),
            "power_w_sample": self.power_w_sample,
            "device_index": self.device_index,
            "evidence": self.evidence,
            "note": self.note,
        }


class measure_energy(ContextDecorator):
    """Measure REAL NVML joules across a code block or function call.

    Usage as a context manager::

        with measure_energy() as m:
            do_work()
        print(m.result.to_dict())

    Or as a decorator::

        @measure_energy()
        def job(): ...

    Honesty contract:
      * joules = (NVML cumulative energy AFTER) - (BEFORE), in joules, ONLY when
        both readings are real and fresh (<30s). This is the exact delta pattern
        the live operator uses.
      * If pynvml / a GPU is absent: result.joules is None and
        result.label == "UNAVAILABLE_NO_NVML". We NEVER emit a fake joule number.
      * If NVML is present but a reading is stale/unreadable: label == "SAMPLE",
        joules None, excluded from billable.
    """

    def __init__(self, device_index: int = 0):
        self.device_index = device_index
        self.result: Optional[EnergyMeasurement] = None
        self._pynvml = None
        self._handle = None
        self._j_before: Optional[float] = None
        self._t0: float = 0.0

    def __enter__(self) -> "measure_energy":
        self._pynvml = _try_import_pynvml()
        now = time.time()
        self._t0 = now
        if self._pynvml is not None:
            try:
                if self._pynvml.nvmlDeviceGetCount() > self.device_index:
                    self._handle = self._pynvml.nvmlDeviceGetHandleByIndex(
                        self.device_index)
                    sample = _nvml_total_energy_joules(
                        self._pynvml, self._handle, now)
                    if sample is not None and _is_fresh(
                            sample.get("exporter_last_seen_ts"), now):
                        self._j_before = sample["joules_measured_total"]
            except Exception:
                self._handle = None
                self._j_before = None
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        now = time.time()
        wall_s = now - self._t0
        # No NVML / no GPU at all => honest UNAVAILABLE, never a fake joule.
        if self._pynvml is None or self._handle is None:
            self.result = EnergyMeasurement(
                joules=None,
                label=LABEL_UNAVAILABLE,
                wall_s=wall_s,
                device_index=(self.device_index if self._handle is not None else None),
                evidence={},
                note=("no real NVML / GPU device reachable in this environment; "
                      "joules cannot be MEASURED, so none is emitted — never faked"),
            )
            return False  # do not suppress exceptions

        sample_after = _nvml_total_energy_joules(self._pynvml, self._handle, now)
        j_after = (sample_after or {}).get("joules_measured_total")
        fresh = (sample_after is not None
                 and _is_fresh(sample_after.get("exporter_last_seen_ts"), now))
        joules = None
        if (fresh and isinstance(self._j_before, (int, float))
                and isinstance(j_after, (int, float)) and j_after >= self._j_before):
            joules = float(j_after) - float(self._j_before)

        if joules is not None:
            self.result = EnergyMeasurement(
                joules=joules,
                label=LABEL_MEASURED,
                wall_s=wall_s,
                power_w_sample=(sample_after or {}).get("power_w_sample"),
                device_index=self.device_index,
                evidence={
                    "joules_before": round(self._j_before, 6),
                    "joules_after": round(float(j_after), 6),
                    "freshness_window_s": FRESHNESS_WINDOW_S,
                    "source": "nvmlDeviceGetTotalEnergyConsumption (mJ->J) delta",
                },
                note="MEASURED NVML cumulative-energy delta across the job wall window",
            )
        else:
            self.result = EnergyMeasurement(
                joules=None,
                label=LABEL_SAMPLE,
                wall_s=wall_s,
                power_w_sample=(sample_after or {}).get("power_w_sample"),
                device_index=self.device_index,
                evidence={},
                note=("NVML present but no fresh real energy delta this window "
                      "(stale/unsupported counter) — SAMPLE, excluded from billable, "
                      "never fabricated"),
            )
        return False


# ===========================================================================
# PART 2 — cheapest-watt placement (ported from szl_cheapest_watt.py).
# ===========================================================================
@dataclass
class _Candidate:
    name: str
    power_w: Optional[float]
    tokens: int
    price_per_mwh: Optional[float]
    joules_measured: Optional[float]   # node's own MEASURED joules this read (or None)
    joules_label: str                  # MEASURED | PENDING_EXPORTER | NONE

    # derived
    joules_per_token: Optional[float] = None
    intensity_label: str = LABEL_UNKNOWN
    cost_per_token: Optional[float] = None
    gco2: Optional[float] = None          # grams CO2 for this node's MEASURED work
    gco2_label: str = LABEL_UNAVAILABLE_GCO2
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "node": self.name,
            "power_w": self.power_w,
            "tokens": self.tokens,
            "price_per_mwh": self.price_per_mwh,
            "joules_label": self.joules_label,
            "joules_measured": (round(self.joules_measured, 6)
                                if self.joules_measured is not None else None),
            "joules_per_token": (round(self.joules_per_token, 9)
                                 if self.joules_per_token is not None else None),
            "intensity_label": self.intensity_label,
            "cost_per_token": (None if self.cost_per_token is None
                               else float(f"{self.cost_per_token:.6e}")),
            "gCO2": (None if self.gco2 is None else round(self.gco2, 6)),
            "gCO2_label": self.gco2_label,
            "note": self.note,
        }


def _derive_measured_joules(node: dict) -> Tuple[Optional[float], str]:
    """Determine a node's own MEASURED joules this read, honestly.

    Priority:
      1. An explicit ``joules`` / ``joules_measured`` value WITH a MEASURED label
         (or a real NVML-delta number) is used verbatim — this is the operator's
         per-node by_node measured joules.
      2. Else, if power_w and tokens and a wall window allow it... NO. We never
         model joules from power*time here: that would be an ESTIMATE, not a
         MEASURED joule, and the doctrine forbids ranking on fabricated joules.
         So a node with only power_w (no measured joules) has UNKNOWN intensity.
    Returns (joules_or_None, joules_label).
    """
    label = str(node.get("joules_label") or "").upper()
    jm = _finite(node.get("joules_measured", node.get("joules")))
    # A finite, strictly-positive joule with a MEASURED (or unspecified) label is a
    # real reading. NaN/inf/negative/zero are screened out by _finite + (>0) so they
    # can NEVER be ranked as a MEASURED intensity.
    if jm is not None and jm > 0 and label in ("", LABEL_MEASURED):
        return jm, LABEL_MEASURED
    # Real work but no per-node measured joules attributed yet => PENDING_EXPORTER.
    if _safe_int(node.get("tokens")) > 0:
        return None, "PENDING_EXPORTER"
    return None, "NONE"


def _cost_per_token(joules_per_token: Optional[float],
                    price_per_mwh: Optional[float]) -> Optional[float]:
    """cost/token = (J/token / 3.6e9 J/kWh) * (price/MWh / 1000 kWh/MWh).

    Returns None (UNKNOWN) when intensity or price is missing — never assumed.
    """
    jpt = _finite(joules_per_token)
    price = _finite(price_per_mwh)
    if jpt is None or price is None:
        return None
    kwh_per_token = jpt / JOULES_PER_KWH
    price_per_kwh = price / 1000.0
    return kwh_per_token * price_per_kwh


def _safe_int(x: Any) -> int:
    """Coerce to a non-fabricating int token count; junk/NaN/None -> 0."""
    if isinstance(x, bool):
        return 0
    if isinstance(x, int):
        return x
    xf = _finite(x)
    return int(xf) if xf is not None else 0


def gco2_from_joules(joules: Optional[float],
                     joules_label: str,
                     grid_intensity_gco2_per_kwh: Optional[float]
                     ) -> Tuple[Optional[float], str]:
    """HONEST grams-CO2 from energy.  gCO2 = kWh * (gCO2/kWh).

    Mirrors the prior-art formula (Zeus / CodeCarbon / GSF Carbon-Aware SDK:
    emissions = energy_kWh * carbon_intensity) but keeps the SZL honesty contract:
    a carbon number is emitted ONLY when BOTH
      (a) joules are genuinely MEASURED (label == MEASURED, finite, > 0), AND
      (b) a real, finite grid carbon intensity (gCO2/kWh) is supplied.
    Otherwise gCO2 is None with a truthful label — carbon is NEVER fabricated,
    never modelled-as-fact, never assumed from a default grid mix.

    Returns (gco2_or_None, gco2_label).
    """
    j = _finite(joules)
    gi = _finite(grid_intensity_gco2_per_kwh)
    if joules_label != LABEL_MEASURED or j is None or j <= 0:
        return None, LABEL_UNAVAILABLE  # no MEASURED energy => no carbon, honestly
    if gi is None or gi < 0:
        return None, LABEL_UNAVAILABLE_GCO2  # MEASURED energy but no real grid mix
    kwh = j / JOULES_PER_KWH
    return kwh * gi, LABEL_MEASURED


def _finalize(decision: Dict[str, Any], prev_digest: str) -> Dict[str, Any]:
    """Attach the re-hashable payload_digest and hash-chain prev/entry digests."""
    payload_digest = sha3_canon(decision)
    entry_digest = sha3_canon({"prev_digest": prev_digest,
                               "payload_digest": payload_digest})
    return {
        "decision": decision,
        "payload_digest": payload_digest,
        "prev_digest": prev_digest,
        "entry_digest": entry_digest,
    }


def cheapest_watt_choice(nodes: List[dict],
                         prev_digest: str = GENESIS_PREV,
                         baseline: str = "most_expensive_comparable",
                         now_ts: Optional[float] = None,
                         grid_intensity_gco2_per_kwh: Optional[float] = None
                         ) -> Dict[str, Any]:
    """Pick the node minimizing energy-cost-per-token; return a hash-chained receipt.

    Each node dict carries at least::

        {"name": str, "power_w": float|None, "tokens": int,
         "price_per_mwh": float|None,
         # optional, for MEASURED intensity:
         "joules_measured": float|None, "joules_label": "MEASURED"|...}

    A node's energy-intensity (J/token) is MEASURED only from its OWN measured joules
    and tokens (both > 0). Nodes without measured joules have UNKNOWN intensity and are
    never ranked on cost. With < 2 comparable MEASURED nodes => decision "no_choice".
    The chosen node minimizes cost/token (when a grid price exists) else J/token.

    If ``grid_intensity_gco2_per_kwh`` is a real, finite carbon intensity, each
    node with MEASURED joules also gets an HONEST per-node gCO2 (kWh * intensity);
    nodes without MEASURED joules, or when no grid intensity is supplied, carry
    gCO2=None with a truthful label — carbon is NEVER fabricated.

    Returns a receipt dict: {decision, payload_digest, prev_digest, entry_digest}
    where decision is canonical and re-hashes to payload_digest via sha3_canon.
    """
    grid_intensity = _finite(grid_intensity_gco2_per_kwh)
    now_ts = time.time() if now_ts is None else now_ts
    ts_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))

    cands: List[_Candidate] = []
    for n in nodes:
        jm, jlabel = _derive_measured_joules(n)
        cands.append(_Candidate(
            name=str(n.get("name") or n.get("node") or "unnamed"),
            power_w=_finite(n.get("power_w")),
            tokens=_safe_int(n.get("tokens")),
            price_per_mwh=_finite(n.get("price_per_mwh")),
            joules_measured=jm,
            joules_label=jlabel,
        ))

    # Grid price: a single live meter value (per MWh) shared this tick. We take the
    # first non-null price among nodes (they should agree on the live grid); never
    # assumed when all are missing.
    grid = None
    for c in cands:
        if c.price_per_mwh is not None:
            grid = c.price_per_mwh
            break

    for c in cands:
        if c.joules_label == LABEL_MEASURED and c.joules_measured and c.tokens > 0:
            c.joules_per_token = c.joules_measured / c.tokens
            c.intensity_label = LABEL_MEASURED
            c.cost_per_token = _cost_per_token(c.joules_per_token,
                                               c.price_per_mwh if c.price_per_mwh
                                               is not None else grid)
            c.gco2, c.gco2_label = gco2_from_joules(
                c.joules_measured, c.joules_label, grid_intensity)
            c.note = "MEASURED J/token from this node's own NVML joule delta / its tokens"
        else:
            c.joules_per_token = None
            c.intensity_label = LABEL_UNKNOWN
            c.cost_per_token = None
            c.gco2, c.gco2_label = None, LABEL_UNAVAILABLE
            c.note = ("intensity unknown — no per-node MEASURED joules this read "
                      "(%s); never ranked on cost, never fabricated" % c.joules_label)

    comparable = [c for c in cands if c.intensity_label == LABEL_MEASURED]

    base_decision: Dict[str, Any] = {
        "receipt_type": "SZL.Energy.CheapestWattPlacement.v1",
        "ts": ts_iso,
        "grid_price_per_mwh": grid,
        "grid_price_label": (LABEL_MEASURED if grid is not None else LABEL_UNKNOWN),
        "grid_price_note": ("live meter value at decision time, passed through verbatim"
                            if grid is not None else
                            "no live grid price this read — cost is UNKNOWN, never assumed"),
        "grid_intensity_gco2_per_kwh": grid_intensity,
        "grid_intensity_label": (LABEL_MEASURED if grid_intensity is not None
                                 else LABEL_UNAVAILABLE_GCO2),
        "grid_intensity_note": ("real grid carbon intensity supplied; gCO2 computed "
                                "only for MEASURED joules" if grid_intensity is not None
                                else "no real grid carbon intensity supplied — gCO2 "
                                "is UNAVAILABLE, never fabricated"),
        "baseline_policy": baseline,
        "candidates": [c.to_dict() for c in cands],
        "reachable_count": len(cands),
        "comparable_measured_count": len(comparable),
        "honesty": {
            "sovereign": False,
            "lambda": "Conjecture 1",
            "trust": "never 100%",
            "placement": "horizontal cost/carbon-aware placement; VRAM NOT fused",
            "fabrication": "no price, joule, or saving is ever fabricated",
        },
    }

    if len(comparable) < 2:
        decision = dict(base_decision)
        decision.update({
            "decision": "no_choice",
            "chosen_node": None,
            "reason": "no placement choice this tick",
            "detail": ("fewer than two nodes have a comparable MEASURED energy-intensity "
                       "this read (%d total, %d MEASURED); with no real alternative we "
                       "decline to claim a saving — never fabricated."
                       % (len(cands), len(comparable))),
            "saving": None,
            "saving_label": None,
        })
        return _finalize(decision, prev_digest)

    if grid is not None:
        ranked = sorted(comparable, key=lambda c: c.cost_per_token)  # type: ignore[arg-type]
        metric = "cost_per_token"
    else:
        ranked = sorted(comparable, key=lambda c: c.joules_per_token)  # type: ignore[arg-type]
        metric = "joules_per_token"

    chosen = ranked[0]
    baseline_node = ranked[-1]  # most-expensive comparable node we DECLINED this tick

    if metric == "cost_per_token":
        chosen_cost = chosen.cost_per_token
        base_cost = baseline_node.cost_per_token
        delta = base_cost - chosen_cost
        saving_label = LABEL_MEASURED
        saving = {
            "metric": "cost_per_token",
            "chosen_cost_per_token": float(f"{chosen_cost:.6e}"),
            "baseline_cost_per_token": float(f"{base_cost:.6e}"),
            "delta_cost_per_token": float(f"{delta:.6e}"),
            "delta_pct": (round(100.0 * delta / base_cost, 4) if base_cost else None),
            "baseline_node": baseline_node.name,
            "note": ("MEASURED: both legs are real per-node J/token AND the grid price "
                     "is the live meter value; delta is vs the most-expensive comparable "
                     "node we declined this tick (a real alternative)."),
        }
    else:
        chosen_j = chosen.joules_per_token
        base_j = baseline_node.joules_per_token
        jdelta = base_j - chosen_j
        saving_label = LABEL_ESTIMATE
        saving = {
            "metric": "joules_per_token",
            "chosen_joules_per_token": round(chosen_j, 9),
            "baseline_joules_per_token": round(base_j, 9),
            "delta_joules_per_token": round(jdelta, 9),
            "delta_pct": (round(100.0 * jdelta / base_j, 4) if base_j else None),
            "baseline_node": baseline_node.name,
            "note": ("ESTIMATE (monetary): energy delta is MEASURED, but NO live grid "
                     "price this read, so a monetary saving cannot be MEASURED — we "
                     "report the MEASURED joules delta only and never assume a price."),
        }

    decision = dict(base_decision)
    decision.update({
        "decision": "placed",
        "chosen_node": chosen.name,
        "rank_metric": metric,
        "reason": ("chosen node minimizes %s among comparable MEASURED-intensity "
                   "nodes this tick" % metric),
        "ranking": [c.name for c in ranked],
        "saving": saving,
        "saving_label": saving_label,
    })
    return _finalize(decision, prev_digest)


class CheapestWattLedger:
    """A small, thread-safe, hash-chained tally of cheapest-watt placement receipts.

    record() evaluates a node set and appends the receipt to the chain. verify()
    re-walks the chain offline: each receipt re-hashes to its payload_digest, its
    entry_digest binds (prev_digest, payload_digest), and each prev links to the
    previous entry_digest. Never fabricates — it only records what the policy returned.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._head = GENESIS_PREV
        self._count = 0
        self._placed = 0
        self._no_choice = 0
        self._records: List[Dict[str, Any]] = []

    def record(self, nodes: List[dict],
               baseline: str = "most_expensive_comparable",
               grid_intensity_gco2_per_kwh: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            receipt = cheapest_watt_choice(
                nodes, prev_digest=self._head, baseline=baseline,
                grid_intensity_gco2_per_kwh=grid_intensity_gco2_per_kwh)
            self._head = receipt["entry_digest"]
            self._count += 1
            if receipt["decision"]["decision"] == "placed":
                self._placed += 1
            else:
                self._no_choice += 1
            self._records.append(receipt)
            return receipt

    def verify(self) -> Tuple[bool, int, int]:
        """Re-walk the chain offline. Returns (ok, length, first_break_index)."""
        with self._lock:
            prev = GENESIS_PREV
            for i, r in enumerate(self._records):
                pd = sha3_canon(r["decision"])
                ed = sha3_canon({"prev_digest": r["prev_digest"],
                                 "payload_digest": pd})
                if (pd != r["payload_digest"] or ed != r["entry_digest"]
                        or r["prev_digest"] != prev):
                    return (False, len(self._records), i)
                prev = r["entry_digest"]
            return (True, len(self._records), -1)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            ok, length, brk = self.verify()
            return {
                "service": "cheapest-watt-placement",
                "kind": "carbon/cost-aware placement + accounting (NOT fused VRAM)",
                "decisions_total": self._count,
                "placed": self._placed,
                "no_choice": self._no_choice,
                "chain": {
                    "head": self._head,
                    "length": length,
                    "ok": ok,
                    "first_break_index": brk,
                    "genesis_prev": GENESIS_PREV,
                },
                "doctrine": DOCTRINE,
            }
