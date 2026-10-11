---
license: apache-2.0
library_name: kernels
tags:
- kernel
- szl-holdings
szl:
  source_repo: szl-holdings/szl-energy-attest
  proof_url: https://github.com/szl-holdings/szl-energy-attest
---

<p><a href="https://huggingface.co/spaces/SZLHOLDINGS/szl-command-lab"><img src="https://raw.githubusercontent.com/szl-holdings/szl-brand/27d12e77fc0f9f1a0e5fae8b34adf2380d51d070/kit/logos/orbit-v2/suite/szl-icon-32.svg" alt="SZL Holdings" width="40" height="40" /></a></p>

# Governed Inference Meter

Inspect inference metering through the retained kernel and its active Energy Attest source package.

**Artifact:** Inference-metering software kernel · **Stage:** Retained compatibility contract

[Explore in Command Lab](https://huggingface.co/spaces/SZLHOLDINGS/szl-command-lab) · [Build](https://github.com/szl-holdings/szl-energy-attest) · [Evidence](https://github.com/szl-holdings/szl-energy-attest/blob/1520b4b50ef957e58628a64a205edb46cdc6348e/hf-kernels/governed-inference-meter/contract.json)

## Before you use it

- Use the exact Kernel Hub revision in the retained contract below. A card update does not change that code pin.
- Loading the kernel executes repository code and requires explicit trust. Inspect the immutable revision before enabling `trust_remote_code=True`.
- Existing builds and qualification evidence stay unchanged; this presentation adds no runtime, energy or performance measurement.

<details>
<summary>Technical details and original loading contract</summary>

The complete original source card follows. Its immutable loading pin and explicit trust requirement remain in force.

<!-- SZL-PRESERVED-TECHNICAL-BODY:START -->
# Governed inference meter — immutable loading contract

This card is the canonical loading contract for the retained Hugging Face
compatibility kernel. The implementation is maintained in
`szl_energy_attest.inference_meter`.

## Quickstart

```python
from kernels import get_kernel

gim = get_kernel(
    "SZLHOLDINGS/governed-inference-meter",
    revision="6d546bfc6591b44ae5eb57d1209678454e52a3f5",
    trust_remote_code=True,
)

print(gim.selfcheck())
```

The full commit pin makes the loaded code immutable. The explicit trust flag is
required because loading a remote organization kernel executes repository code.
Advance the pin only after a new Kernel Hub revision is published and verified.

<!-- SZL-PRESERVED-TECHNICAL-BODY:END -->

</details>


Artwork: SZL Orbit · © 2026 SZL Holdings / Stephen Lutar · [CC BY 4.0](https://github.com/szl-holdings/szl-brand/blob/27d12e77fc0f9f1a0e5fae8b34adf2380d51d070/kit/LICENSE).
