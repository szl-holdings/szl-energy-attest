---
license: apache-2.0
tags:
  - szl
  - governed-inference
  - energy-attestation
  - receipts
  - source-pointer
  - no-implementation-here
---

# szl-energy-attest

> **SOURCE POINTER · HUB MIRROR EMPTY · NOT AN INSTALLABLE IMPLEMENTATION**
>
> This Hugging Face repository is a public pointer to the canonical `szl-energy-attest` source. The canonical source's `HUB_MIRROR_STATUS.json` records this Hub artifact as `MIRROR_EMPTY` on 2026-09-04. Do not infer that package files, tests, a Kernel Hub loader, or a runnable implementation are published here.

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

Apache-2.0.