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
