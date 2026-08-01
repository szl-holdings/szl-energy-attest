---
license: apache-2.0
tags:
  - energy
  - governance
  - provenance
  - software
  - measurement
  - receipts
language:
  - en
pretty_name: Attestable Energy Receipts for Governed Compute
---

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
| `UNAVAILABLE` | No supported device, driver, permission, binding, or fresh reading; energy-dependent fields remain null. |
| `SAMPLE` | Documentation payloads and example commands until an evaluator runs them. |
| Limits | A hash establishes internal integrity, not authorship; optional signing does not establish that a measurement is accurate; policy remains host-enforced. |

**Investor value.** The package turns an otherwise ephemeral hardware reading
into portable evidence with explicit missing-data semantics, reducing the risk
that estimated or absent energy data is presented as measured fact.

**Developer/evaluator path.** Install the package, call `capability_report()`
before metering, run one known workload, and verify the resulting chain offline.
Keep `UNAVAILABLE` as the terminal result when the environment cannot measure.

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
ecosystem-wide novelty claim.## What is MEASURED vs UNAVAILABLE

This is the most important section. Read it before trusting any field.

- **MEASURED** — `measured_joules` is a real number **only** when a real, fresh
  NVML / exporter joule delta produced it. The label is decided by the energy
  core's joule-truth path, never by a convenience flag. Requires a GPU and a live
  metering exporter on the node that did the work.
- **UNAVAILABLE** — there is no GPU and/or no fresh NVML delta on this box (e.g. a
  CPU-only laptop, CI runner, or this Space). `measured_joules` is `null` and the
  label says so. The receipt chain still verifies — the *provenance* is real even
  when the *joules* cannot be.
- **SAMPLE** — real work ran (so token/wall counts are honest) but its energy is
  **not** a billable MEASURED joule, so we report `null`, never a guess.

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

A receipt body (`SAMPLE`, on a CPU-only box):

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
[`hf-kernels/governed-inference-meter`](hf-kernels/governed-inference-meter/README.md).*Signed-off-by: Stephen Lutar <stephenlutar2@gmail.com>*
