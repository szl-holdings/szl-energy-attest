---
license: apache-2.0
tags:
  - szl
  - governed-inference
  - energy-attestation
  - receipts
  - source-pointer
  - no-implementation-here
szl:
  source_repo: szl-holdings/szl-energy-attest
  proof_url: https://github.com/szl-holdings/szl-energy-attest/blob/2cc3866d2bbc303b06822151f13926bac5a0ca76/HUB_MIRROR_STATUS.json
  artifact_class: SOURCE_POINTER
  lifecycle: INFORMATIONAL_METADATA_ONLY
---

<p><a href="https://huggingface.co/spaces/SZLHOLDINGS/szl-command-lab"><img src="https://raw.githubusercontent.com/szl-holdings/szl-brand/27d12e77fc0f9f1a0e5fae8b34adf2380d51d070/kit/logos/orbit-v2/suite/szl-icon-32.svg" alt="SZL Holdings" width="40" height="40" /></a></p>

# SZL Energy Attest

Find the maintained source, migration records, and use boundaries for energy-aware inference receipts.

**Artifact:** Source pointer · **Stage:** Informational metadata only

[Explore in Command Lab](https://huggingface.co/spaces/SZLHOLDINGS/szl-command-lab) · [Build from source](https://github.com/szl-holdings/szl-energy-attest) · [Mirror evidence](https://github.com/szl-holdings/szl-energy-attest/blob/2cc3866d2bbc303b06822151f13926bac5a0ca76/HUB_MIRROR_STATUS.json)

## Before you use it

> **SOURCE POINTER · HUB MIRROR EMPTY · NOT AN INSTALLABLE IMPLEMENTATION**
>
> This Hugging Face repository is a public pointer to the canonical `szl-energy-attest` source. The canonical source's `HUB_MIRROR_STATUS.json` records this Hub artifact as `MIRROR_EMPTY` on 2026-09-04. Do not infer that package files, tests, a Kernel Hub loader, or a runnable implementation are published here.

## Choose the right artifact

| Your purpose | Where to go | Boundary |
| --- | --- | --- |
| Start an integration | [Canonical Energy Attest source](https://github.com/szl-holdings/szl-energy-attest) | Review source installation, tests, and hardware requirements. This Hub repository contains no installable implementation. |
| Maintain an existing kernel integration | [Retained native kernel contract](https://github.com/szl-holdings/szl-energy-attest/blob/2cc3866d2bbc303b06822151f13926bac5a0ca76/hf-kernels/governed-inference-meter/README.md) | Follow its exact Kernel Hub code pin and explicit trust requirement. The native kernel has its own revision history. |
| Trace the predecessor | [Migration evidence](https://github.com/szl-holdings/szl-energy-attest/blob/2cc3866d2bbc303b06822151f13926bac5a0ca76/MIGRATION_PROVENANCE.json) | The deprecated model-namespace mirror is historical; its examples are not new integration guidance. |

## Canonical implementation

The maintained implementation, test suite, examples, migration evidence, and package manifest are in the canonical GitHub repository:

https://github.com/szl-holdings/szl-energy-attest

The source repository contains `pyproject.toml`, `szl_energy_attest/`, `energy_core/`, `examples/`, `tests/`, `MIGRATION_PROVENANCE.json`, `SPEC.md`, and CI that installs pytest plus the pinned `szl-receipt` dependency before running `pytest -q`.

## What the canonical source provides

- NVML-backed energy attestation when a live meter is available.
- Honest null / unavailable energy fields when no meter is available.
- Tokens-per-joule only when joules are actually measured.
- Tamper-evident receipt-chain support.
- Optional signing and interop paths through `szl-receipt`.
- Migration evidence for the deprecated `governed-inference-meter` surface.

This Hub card does not itself establish that any of those interfaces are loadable from Hugging Face, currently tested, runnable in a particular environment, or producing measured energy on your hardware.

## Evidence boundary

```text
Hub repository      = source pointer / mirror-empty record
Canonical source    = GitHub repository named above
NVML joules         = measured only when a live compatible meter is available
No meter            = UNAVAILABLE / null; never fabricated
Λ aggregation       = Conjecture 1; advisory, never a theorem
Unsigned receipt    = UNSIGNED; never represented as signed
```

## Legacy relationship

`governed-inference-meter` is deprecated. It remains a historical tombstone and must not be used as new integration guidance. The canonical successor source is `szl-energy-attest`; consult its migration evidence before changing an existing integration.

## Use boundary

Do not treat this Hub repository as a model, checkpoint, benchmark, deployment, current runtime-status assertion, or energy-performance claim. Follow the canonical source and its tests for installation, verification, and migration instructions.


Artwork: SZL Orbit · © 2026 SZL Holdings / Stephen Lutar · [CC BY 4.0](https://github.com/szl-holdings/szl-brand/blob/27d12e77fc0f9f1a0e5fae8b34adf2380d51d070/kit/LICENSE) · [Trademark notice](https://github.com/szl-holdings/szl-brand/blob/27d12e77fc0f9f1a0e5fae8b34adf2380d51d070/NOTICE).

Apache-2.0.
