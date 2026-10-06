[![PyPI](https://img.shields.io/pypi/v/szl-energy-attest)](https://pypi.org/project/szl-energy-attest/) [![Python](https://img.shields.io/pypi/pyversions/szl-energy-attest)](https://pypi.org/project/szl-energy-attest/) [![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/szl-holdings/szl-energy-attest/badge)](https://scorecard.dev/viewer/?uri=github.com/szl-holdings/szl-energy-attest)

> **SZL Holdings** · Doctrine v11 · Λ = Conjecture 1 (advisory, never "green"/theorem) · canonical [a-11-oy.com](https://a-11-oy.com)

# szl_energy_attest — attestable energy receipts for governed compute

> **Canonical source.** This GitHub repository is the source of truth for the energy-attestation artifact and vendors the runnable energy core under [`energy_core/`](energy_core/), co-located with the wrapped measurement path. It is real, tested, and downloadable for direct consumption. **Note on the flagship:** the a11oy governed substrate at [a-11-oy.com](https://a-11-oy.com) currently serves its *own* inline energy implementation (`szl_joules_truth.py` / `szl_energy_operator.py`) under `/api/a11oy/v1/energy/*`; this package is the canonical kernel available for direct use — it is **not yet** the flagship's served code path.

> **📦 Canonical energy package (Wave D consolidation).** This repo is the **canonical SZL energy package**. The former `szl-holdings/governed-inference-meter` has been **folded in** here: its *live inference metering* code — the NVML `EnergyMeter` (hardware energy counter **+ power-integral / trapezoidal fallback**), an advisory policy gate, and the `meter()` / `metered()` inference wrappers that emit tokens-per-joule hash-chained receipts — now lives under [`szl_energy_attest.inference_meter`](./szl_energy_attest/inference_meter). The meter-specific attestation, receipt-chain hardening, and PCGI adapters are also retained there for import continuity; the root package's energy receipt is a **different schema**, so parity is not invented. File-level source and destination hashes are recorded in [`MIGRATION_PROVENANCE.json`](./MIGRATION_PROVENANCE.json). `governed-inference-meter` is **DEPRECATED**, not deleted, and archiving remains a later owner decision. Λ = **Conjecture 1** (advisory) is preserved verbatim; no conjecture is upgraded to proven.

**Turn the energy a unit of compute spends into a receipt you can verify — offline, by anyone, with nothing but a hash function.**

This package turns one unit of governed compute into an **attestable energy
receipt**: a small, canonical, hash-chained JSON record that states — honestly —
how many joules the work *measured* (from real NVML), and links to the receipt
before it so any tampering or reordering breaks the chain. When no GPU is present,
the energy field is `null` and labeled `UNAVAILABLE` — never a fabricated number.

> **Doctrine.** MEASURED joules only, via real NVML. We never fabricate a joule, a
> price, or a receipt. Λ is **Conjecture 1** — advisory, trust never 100%. An
> honest `UNAVAILABLE` receipt that still hash-verifies beats a fake-green number.

---

## Artifact truth card

| Field | Truthful classification |
|---|---|
| Artifact | **Executable measurement and receipt software**, not trained weights and not a carbon model. |
| Primary evidence | Source, tests, migration hashes, canonical receipt serialization, and offline chain verification. |
| `MEASURED` | Only a fresh supported NVML counter delta or power-sample integral from the executing environment. |
| `UNAVAILABLE` | The selected root/core path did not establish usable measurement capability (for example, NVML initialization or device enumeration failed, or the core could not acquire a handle); energy-dependent fields remain null. |
| `SAMPLE` | The selected path initialized NVML and found at least one device, but produced no fresh supported counter delta; energy remains null and is not promoted to `MEASURED`. |
| Limits | A hash establishes internal integrity, not authorship; optional signing does not establish that a measurement is accurate; policy remains host-enforced. |

**Investor value.** The package turns an otherwise ephemeral hardware reading
into portable evidence with explicit missing-data semantics, reducing the risk
that estimated or absent energy data is presented as measured fact.

**Developer/evaluator path.** Install the package, import
`capability_report` from `szl_energy_attest.inference_meter`, inspect it before
metering, run one known workload, and verify the resulting chain offline. On the
inference-meter path, missing hardware evidence terminates as
`mode="unmeasured"` with `joules: null`; the separate root receipt schema uses
the `UNAVAILABLE` label.

## The category: evidence, not estimation

The energy-tooling field splits into **estimators** and **aggregate
benchmarks** — nobody sells a **per-inference measured-joule receipt a buyer
can verify independently**. That empty slot is this vertical's category.

| Incumbent class | What it ships | Source |
| --- | --- | --- |
| Carbon **estimators** | model/attribute-driven CO₂ estimates from declared hardware (CodeCarbon, incl. its RAPL docs), or cloud-footprint assessment APIs (Boavizta) | [docs.codecarbon.io](https://docs.codecarbon.io/), [CodeCarbon RAPL](https://docs.codecarbon.io/latest/explanation/rapl/), [boavizta.org](https://boavizta.org/en/tools), [BoaviztAPI docs](https://doc.api.boavizta.org/Explanations/services/cloud/) |
| **Measurement benchmarks** | empirical joules-per-inference across model/hardware configs, in aggregate leaderboards (ML.ENERGY: 46 models / 1,858 configs on H100/B200) | [ml.energy/leaderboard](https://ml.energy/leaderboard/), [v3.0 blog](https://ml.energy/blog/measurement/energy/diagnosing-inference-energy-consumption-with-the-mlenergy-leaderboard-v30/), [NeurIPS paper](https://arxiv.org/html/2505.06371v2) |
| **Hardware primitives** | Intel RAPL CPU counters; NVIDIA NVML GPU power/energy | [CodeCarbon RAPL](https://docs.codecarbon.io/latest/explanation/rapl/), [arXiv 2401.15985](https://arxiv.org/html/2401.15985v2), [NVML API ref](https://docs.nvidia.com/deploy/nvml-api/latest/pdf/NVML_API_Reference_Guide.pdf), [NVML device queries](https://docs.nvidia.com/deploy/nvml-api/api/group__nvmlDeviceQueries.html) |
| **Energy-priced billing** | measured $/kWh inference billing — but **no signed, portable, per-request proof** (its portal shows billing, not verifiable receipts) | [Neuralwatt pricing](https://portal.neuralwatt.com/pricing), [launch post](https://www.linkedin.com/posts/neuralwatt_todaywerelaunchingneuralwattcloud-our-activity-7437858319295442944-vu2A), [portal](https://portal.neuralwatt.com/), [API docs](https://docs.neuralwatt.com/api/overview) |

The dominant UX is leaderboards, dashboards, and $/kWh billing — **not
per-request signed receipts**. Meanwhile inference now dominates lifecycle
energy (>90%, [TokenPowerBench, arXiv 2512.03024](https://arxiv.org/html/2512.03024v1))
and per-task energy varies by orders of magnitude by task and hardware
([arXiv 2601.22076](https://arxiv.org/html/2601.22076v1)), with energy-based
pricing and carbon-disclosure pressure growing ([Carbon Cost of Intelligence](https://assets.ctfassets.net/sejp9n42frnn/2y19H313jPKZFgRV0bYOOC/8565275be038c909a3994c2ceb1a14c7/whitepaper.pdf), [arXiv 2605.27309](https://arxiv.org/html/2605.27309)).

**This vertical creates the missing object**: one signed, hash-chained,
offline-verifiable joule receipt **per inference** (MEASURED via NVML where a
GPU metering path exists; honest `UNAVAILABLE` / separately-labelled
`ESTIMATED` where it does not — estimation never blends into measured), plus a
bulk **daily-rollup receipt** chained to the per-inference ones — the artifact
Neuralwatt-style $/kWh billing needs but no incumbent issues.

### The v1 proxy (`szl_energy_attest/meter_proxy/`)

A FastAPI proxy that wraps **any OpenAI-compatible endpoint**
(`/v1/chat/completions`) and emits one receipt per call:

```
SZL_UPSTREAM_BASE=http://upstream:9000 \
SZL_RECEIPT_DIR=/var/szl/receipts \
SZL_SIGNING_KEY_PATH=/run/secrets/key.pem \        # optional: absence = UNSIGNED-honest
uvicorn szl_energy_attest.meter_proxy.proxy:create_app --factory --port 8377
```

Each receipt carries: measured joules with an honest state machine
(`MEASURED` only from a real NVML delta — energy counter, else trapezoidal
power integral; `UNAVAILABLE` on CPU-only/sandboxed hosts; demo-only
`ESTIMATED` in a **separate numeric field**), upstream-provided token counts
(`UNAVAILABLE` label when the upstream omits `usage` — never invented), model
id, proxy-side wall-clock latency, a carbon-intensity placeholder
(`UNAVAILABLE` unless a grid-API key is configured via `SZL_GRID_PROVIDER` /
`SZL_GRID_API_KEY`, in which case the value is REPORTED pass-through), and a
**DSSE/ECDSA-P256 envelope** via the shared [szl-receipt](https://github.com/szl-holdings/szl-receipt)
library — with an UNSIGNED-honest fallback when no key is present and an
honest sig-note when the library is not installed at all. Receipts persist
append-only with `fcntl.flock` + `fsync` before ACK (LOCAL durability only;
remote durability is a separate, visibly pending concern).

```
# clearly-labelled SYNTHETIC demo (estimates only, never called measured):
python -m szl_energy_attest.meter_proxy.demo /tmp/szl-demo-store

# offline verification (no network):
python -m szl_energy_attest.meter_proxy.verifier /var/szl/receipts --pubkey pub.pem
# -> VERIFIED | FAIL on any tamper | INCOMPLETE (never PASS) on missing evidence
```

Honest fail-closed attestation rule (build directive 3 of the vertical
brief): when energy cannot be measured, the receipt says `UNAVAILABLE` with
verified provenance — it does **not** emit an estimate dressed as
measurement; that is the measurement discipline of
[ML.ENERGY's measurement ethos](https://ml.energy/blog/measurement/energy/diagnosing-inference-energy-consumption-with-the-mlenergy-leaderboard-v30/)
applied to billing.

---

## Product value without a novelty claim

Energy tools expose different layers: counters, estimates, dashboards, and
audit records. This package focuses narrowly on binding a supported hardware
observation, its availability state, and receipt provenance into one record.

| Common telemetry path | This package's bounded contribution |
| --- | --- |
| Measure watts and render a chart | Record supported joules in a signable, hash-chained receipt |
| Estimate carbon or cost | Bind only declared inputs; leave unknown values unavailable |
| Retain an application log | Export a canonical record an evaluator can re-hash offline |
| Fill missing values | Preserve explicit `UNAVAILABLE` / null fields |

The value is the explicit evidence boundary. This repository makes no
ecosystem-wide novelty claim.

## What is MEASURED vs UNAVAILABLE

This is the most important section. Read it before trusting any field.

- **MEASURED** — `measured_joules` is a real number **only** when a real, fresh
  NVML / exporter joule delta produced it. The label is decided by the energy
  core's joule-truth path, never by a convenience flag. Requires a GPU and a live
  metering exporter on the node that did the work.
- **UNAVAILABLE** — there is no reachable GPU/NVML measurement capability on this
  box (e.g. a CPU-only laptop, CI runner, or this Space). `measured_joules` is
  `null` and the label says so. The receipt chain still verifies — the
  *provenance* is real even when the *joules* cannot be.
- **SAMPLE** — the selected path initialized NVML and found at least one device,
  but produced no fresh supported counter delta. Energy is **not** a billable
  MEASURED joule, so we report `null`, never a guess. This label speaks only to
  measurement-path state; by itself it proves neither device-handle acquisition,
  workload execution, nor token provenance.

`price_per_mwh` and `gCO2` are **pass-through only**: a live grid meter value
verbatim, or `null`. They are never assumed, modeled-as-fact, or back-filled.

> On a CPU-only machine, the example below runs end-to-end with
> `measured_joules: null`, `label: "UNAVAILABLE"`, and a chain that verifies. That
> is the correct, shippable behavior — not a bug.

---

## `grid_context` — documenting *when/where* a run happened (REPORTED, optional)

A receipt can carry an **optional `grid_context` block**: the *observed grid
signal* at run time — the grid's carbon intensity (gCO₂/kWh) and, where a provider
publishes one, the wholesale price. It lets a run **document that it happened in a
cleaner / cheaper / curtailed window** — the software-scheduling discipline that is
the one honest transfer from demand-response operators.

**It is pass-through provenance, not measurement.** `grid_context` is completely
independent of the NVML joule-truth path: with no GPU, `measured_joules` stays
`null` + `UNAVAILABLE` exactly as before. **A `grid_context` block never turns an
unmeasured run into a measured one, and never becomes a joule.**

**This does not create or measure free energy; scheduling compute into cleaner
windows is the only transfer.** There is no free-energy, perpetual-motion, or
zero-cost-energy claim here — "curtailed / dumped" power is real waste energy that
still costs real money and hardware to capture. Λ remains **Conjecture 1** (open).

### Honest labels (every field)

- **REPORTED** — a value carried **verbatim** from a real public signal, together
  with its `source` URL and its `observed_at` / `fetched_at` timestamps.
- **UNAVAILABLE** — the signal was missing, unreachable, malformed, or the provider
  publishes no such value. The field is `null`. **Never invented, modelled, or
  defaulted.**

The carbon number is labelled by *kind* so it is never over-claimed:
`carbon_intensity_kind: "grid_average"` for the UK signal (an average mix, **not**
marginal) vs `"marginal"` only when a provider that actually reports marginal
operating emissions is used.

### Providers

- **`uk_carbon_intensity`** — the **default, keyless** provider (UK
  [Carbon Intensity API](https://api.carbonintensity.org.uk/intensity)). Reports
  grid-**average** carbon intensity (actual/forecast). It publishes **no price**, so
  `price_per_mwh` is `null` / `UNAVAILABLE` for this provider — honestly.
- **`electricity_maps`**, **`watttime`** — **OPTIONAL, key-gated** providers. Without
  a caller-supplied `api_key` they return an honest `UNAVAILABLE` block. **A key is
  never required** — the keyless UK signal always works.

```python
from szl_energy_attest import (
    build_receipt, fetch_grid_context, verify_chain, GENESIS_PREV,
)

# Keyless UK Carbon Intensity API. Network failure => honest UNAVAILABLE nulls.
gc = fetch_grid_context("uk_carbon_intensity")   # REPORTED pass-through block

r = build_receipt(tokens=128, node="node-a", prev=GENESIS_PREV, grid_context=gc)
# measured_joules stays null/UNAVAILABLE on a CPU box — grid_context adds context,
# not joules. The block is hashed into the receipt, so it is tamper-evident too.
assert verify_chain([r])[0]
```

A `grid_context` block (REPORTED, from the keyless UK signal):

```json
{
  "provider": "uk_carbon_intensity",
  "source": "https://api.carbonintensity.org.uk/intensity",
  "region": "GB",
  "observed_at": "2026-07-09T18:30Z",
  "fetched_at": "2026-07-09T19:05:00Z",
  "carbon_intensity_gco2_per_kwh": 121,
  "carbon_intensity_kind": "grid_average",
  "carbon_intensity_index": "moderate",
  "carbon_intensity_label": "REPORTED",
  "price_per_mwh": null,
  "price_label": "UNAVAILABLE",
  "note": "REPORTED grid-average carbon intensity (actual) …; NOT marginal, NOT a MEASURED joule."
}
```

`grid_context` is **hashed into the receipt body only when present**, so it is
tamper-evident (a forged intensity breaks the chain) while receipts *without* it
re-hash byte-identically to the pre-`grid_context` schema (full back-compat).

---

## Install / layout

This repository vendors two co-located packages:

- **`szl_energy_attest/`** — the publishable attestation surface (this package).
- **`energy_core/szl_energy_core/`** — the runnable SZL energy core (measured-joule
  accounting + cheapest-watt placement), folded in as a sibling so the wrapped
  measurement path ships alongside the attestation layer. See
  [`energy_core/README.md`](energy_core/README.md).

Pure-stdlib for the verification and fallback hashing path (`hashlib` + `json`); no
network. When the runnable SZL energy core (`szl_energy_core`) is importable, this
package **wraps** it: receipts use the core's canonical hash (SHA3-256) and real
`measure_energy()` NVML delta path, so digests are platform-consistent and the
energy numbers come from the same metering code the operator uses. It never
duplicates that code. With no core present it falls back to a byte-identical local
SHA-256 so the chain still verifies offline. `canon_source()` reports which is
active (here: `szl_energy_core`).

```
szl_energy_attest/
  szl_energy_attest/__init__.py   # build_receipt(), verify_chain(), measure_joules()
  szl_energy_attest/cli.py        # `emit` / `verify` sample receipt chains
  examples/sample_receipt.json    # a clearly-labeled SAMPLE chain (UNAVAILABLE energy)
  SPEC.md                         # receipt schema + verification procedure
  LICENSE                         # Apache-2.0
  CITATION.cff
```

## Quickstart

```bash
# Emit a clearly-labeled SAMPLE receipt chain to stdout (or --out file.json)
python -m szl_energy_attest.cli emit

# Emit + re-walk the hash chain, then prove tampering breaks it
python -m szl_energy_attest.cli verify
```

Programmatic use:

```python
from szl_energy_attest import build_receipt, verify_chain, measure_joules, GENESIS_PREV

# measure_joules() is honest: (None, "UNAVAILABLE") on a CPU-only box.
joules, label = measure_joules()

r0 = build_receipt(tokens=128, node="node-a",
                   measured_joules=joules, label=label, prev=GENESIS_PREV)
r1 = build_receipt(tokens=256, node="node-b",
                   measured_joules=joules, label=label, prev=r0["digest"])

ok, length, first_break = verify_chain([r0, r1])
assert ok  # re-hashes cleanly; energy is null/UNAVAILABLE but provenance is real
```

An example receipt body (`UNAVAILABLE`, from a CPU-only box):

```json
{
  "schema": "szl_energy_attest/receipt@1",
  "measured_joules": null,
  "label": "UNAVAILABLE",
  "tokens": 128,
  "node": "example-node-a",
  "price_per_mwh": null,
  "gCO2": null,
  "decision": "no_choice",
  "lambda": "Conjecture 1 (advisory; trust never 100%)",
  "sovereign": false,
  "prev": "0000000000000000000000000000000000000000000000000000000000000000",
  "payload_digest": "sha3-256:…",
  "digest": "sha3-256:…"
}
```

See **[SPEC.md](SPEC.md)** for the full field-by-field schema and the offline
verification procedure.

### Detached chain signature verification

`sign_chain(receipts)` re-walks the supplied list before constructing its detached
envelope; an invalid chain raises `ValueError` before any signer is called.
`verify_signature(receipts, envelope, key=...)` verifies that chain and requires
the envelope's canonical payload to match its terminal digest, length and payload
type. A valid envelope for another chain cannot authenticate these receipts.
Missing/malformed envelopes, contradictory signing states, noncanonical payloads
and unsupported signature backends return `valid=False`.

The emitted envelope format is unchanged. A coherent `UNSIGNED` envelope retains
`signed=False, valid=True` for **chain integrity only**; it does not authenticate
a signer. Callers requiring keyed authentication must require both `signed=True`
and `valid=True` under their configured key policy. HMAC validates possession of
that shared key, without proving a public signer identity or measurement accuracy.
An empty chain can verify against its genesis/zero-length envelope, which is no
evidence of execution or energy measurement.

---

## How the real capability fits together

`szl_energy_attest` is the *publishable surface* over a real, running stack:

- **MEASURED-NVML energy accounting.** Joules come from a real, fresh (<30s) NVML
  exporter delta on the node that computed the work; stale or absent samples are
  labeled and excluded — never fabricated.
- **Cheapest-watt placement.** When two or more nodes have a *comparable MEASURED*
  energy intensity (joules/token) and a live grid price is present, the policy
  records which node minimizes energy-cost-per-token. With fewer than two
  comparable measured nodes it records `no_choice` — it never invents an
  alternative to claim a saving against.
- **Hash-chained, signable receipts.** Every decision is re-hashable offline
  (`payload_digest`) and chained (`prev` → `digest`); DSSE signing is layered on by
  the caller when a real cosign key is present — absent a key, the receipt is
  honest-but-unsigned, never faked.

This is the energy lens of the **[a11oy](https://a-11-oy.com) governed-AI platform**
([SZL Holdings](https://a-11-oy.com/company)), which records governed decisions as
cryptographically signed, tamper-evident receipts verifiable offline by anyone with
a public key. It composes with:

- **lutar-lean** — Lean 4 formalization of Λ (**Conjecture 1**, uniqueness proof-deferred — NOT a theorem) plus the
  machine-checked Egyptian-exactness lemma (DOI [10.5281/zenodo.20434308](https://doi.org/10.5281/zenodo.20434308)).
- **vsp-otel** — the verifiable-span OpenTelemetry exporter that carries these
  receipts as spans (DOI [10.5281/zenodo.19944926](https://doi.org/10.5281/zenodo.19944926)).

---

## Honesty notes (what this is NOT)

- It does **not** execute inference and does **not** generate joules. It records
  and verifies what was measured elsewhere.
- There are **no benchmarks, no headline energy numbers, and no savings claims** in
  this README — those only exist on hardware that actually measured them, inside a
  receipt you can re-hash.
- Λ is a **conjecture**, used advisorily. Nothing here asserts certainty,
  sovereignty, or 100% trust.
- On a box that cannot measure, the correct output is `UNAVAILABLE`. We publish
  that honestly rather than a green number we cannot defend.

## Citation

See [CITATION.cff](CITATION.cff). Author: Stephen Lutar
([ORCID 0009-0001-0110-4173](https://orcid.org/0009-0001-0110-4173)), SZL Holdings.

## License

Apache-2.0. © 2026 SZL Holdings. See [LICENSE](LICENSE).

---

<sub>
<b>SZL Holdings</b> · attestable energy receipts · MEASURED joules or honest UNAVAILABLE · Λ = Conjecture 1 (advisory) ·
<a href="https://a-11-oy.com">a-11-oy.com</a> ·
<a href="https://github.com/szl-holdings/szl-energy-attest">github.com/szl-holdings/szl-energy-attest</a>
</sub>

---

## Hugging Face presentation boundary

The [GitHub repository](https://github.com/szl-holdings/szl-energy-attest) is the
canonical source for this package. Use the
[SZL Holdings Hugging Face organization](https://huggingface.co/SZLHOLDINGS) to
discover separately published compatibility artifacts or presentation Spaces.
Names, reachability, and runtime state may change and are not asserted here.
The deprecated meter's immutable loading contract remains under
[`hf-kernels/governed-inference-meter`](hf-kernels/governed-inference-meter/README.md).

*Signed-off-by: Stephen Lutar <stephenlutar2@gmail.com>*
