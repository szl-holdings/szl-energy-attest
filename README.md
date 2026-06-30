---
license: apache-2.0
tags:
  - energy
  - governance
  - provenance
language:
  - en
pretty_name: Attestable Energy Receipts for Governed Compute
---

# szl_energy_attest — attestable energy receipts for governed compute

> **Canonical source.** This GitHub repository is the source of truth for the energy-attestation artifact and vendors the runnable energy core under [`energy_core/`](energy_core/), co-located with the wrapped measurement path. The energy lens is served live as part of the a11oy governed substrate at [a-11-oy.com](https://a-11-oy.com) (see `/api/a11oy/v1/energy/*`).

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

## Category of one

Lots of tools *measure* power. Plenty *log* carbon. Dashboards estimate kWh and
cloud bills approximate cost. All of that is **telemetry** — numbers in a chart you
are asked to trust.

`szl_energy_attest` is a different category. It makes energy an **attestable,
verifiable receipt**:

| The usual thing | This thing |
| --- | --- |
| Measure watts → show a chart | Measure joules → **mint a signed, hash-chained receipt** |
| Log carbon to a dashboard | Bind carbon (when known) into a **re-hashable record** |
| "Trust our number" | **Re-hash it yourself, offline, and verify the chain** |
| Green by assertion | Honest `UNAVAILABLE` when we cannot measure |

Everyone measures energy or logs carbon. Nobody makes energy an **attestable
receipt** — a record whose every field is either a measured fact or an explicit,
truthful null, provable by anyone after the fact. That is the gap this fills.

---

## What is MEASURED vs UNAVAILABLE

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

- **lutar-lean** — Lean 4 machine-checked proofs of the Λ uniqueness theorem and
  the Egyptian-exactness lemma (DOI [10.5281/zenodo.20434308](https://doi.org/10.5281/zenodo.20434308)).
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

## HF cross-reference (alignment fix 2026-06-30)

**GitHub↔HF name mapping:** `szl-holdings/szl-energy-attest` (GitHub) ↔ [`SZLHOLDINGS/energy`](https://huggingface.co/spaces/SZLHOLDINGS/energy) (HF Space).

The live HF Space for this repo is [`SZLHOLDINGS/energy`](https://huggingface.co/spaces/SZLHOLDINGS/energy) — energy-metered inference receipts (tokens/joule, NVML when GPU present, honest `mode=unmeasured` on CPU).

> **Note:** Previously this section linked to `SZLHOLDINGS/energy-attest-holo` and `SZLHOLDINGS/szl-substrate` — both confirmed non-existent as of 2026-06-30 estate audit. These references have been removed and replaced with the correct live Space.

*Signed-off-by: Stephen Lutar <stephenlutar2@gmail.com>*
