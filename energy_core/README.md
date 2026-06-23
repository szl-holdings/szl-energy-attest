# szl_energy_core

The **real** energy core of SZL Holdings, extracted clean and honest from the live
[`szl-holdings/a11oy`](https://github.com/szl-holdings/a11oy) codebase
(`szl_energy_operator.py`, `szl_joules_truth.py`, `szl_cheapest_watt.py`).

Two genuine capabilities, ported faithfully — **without fabricating any measurement**:

## 1. Measured-joule accounting — `measure_energy()`

A context manager / decorator that measures REAL GPU energy across a job's wall window:

```python
from szl_energy_core import measure_energy

with measure_energy() as m:
    do_work()
print(m.result.to_dict())
```

- Joules = `nvmlDeviceGetTotalEnergyConsumption` **AFTER − BEFORE** (mJ→J), labeled
  `MEASURED` **only** when both NVML readings are real and fresh (`< 30 s`) — the exact
  delta pattern the live operator's `_run_real_job` uses.
- **No GPU / no `pynvml`?** Returns `{"joules": None, "label": "UNAVAILABLE_NO_NVML"}`.
  We **never** emit a fake joule.
- NVML present but reading stale/unreadable ⇒ `SAMPLE`, joules `None`, excluded from billable.

## 2. Cheapest-watt placement — `cheapest_watt_choice(nodes)`

Given per-node `{name, power_w, tokens, price_per_mwh, joules_measured, joules_label}`,
it computes MEASURED energy-intensity (J/token), converts to cost-per-token via the live
grid price, picks the node minimizing cost (or J/token when no price), and returns a
**re-hashable, hash-chained decision receipt** (SHA3-256 over the canonical decision body).

```python
from szl_energy_core import cheapest_watt_choice, sha3_canon
receipt = cheapest_watt_choice(nodes)
assert sha3_canon(receipt["decision"]) == receipt["payload_digest"]  # verifiable offline
```

Honesty gates: a node only has an intensity when its own measured joules **and** tokens
are both `> 0`; otherwise UNKNOWN and never ranked on cost. With `< 2` comparable MEASURED
nodes ⇒ `decision = "no_choice"` (never invent an alternative). Savings are `MEASURED`
only when both legs are MEASURED **and** a live price exists; else `ESTIMATE` or omitted.

`CheapestWattLedger` keeps a thread-safe hash-chain of receipts with offline `verify()`.

## Run

```bash
python3 demo.py
python3 -m pytest tests/ -q
```

## What is MEASURED vs UNAVAILABLE here

In this CPU sandbox there is **no GPU and no `pynvml`**, so `measure_energy()` honestly
reports `UNAVAILABLE_NO_NVML` with `joules = None` — no joule is ever fabricated. The
cheapest-watt placement logic is fully MEASURED and verifiable here because it operates
on per-node measured-joule inputs and re-hashable receipts, both of which work offline.

Doctrine: Λ = Conjecture 1 (advisory); sovereign = false on accounting paths; trust never 100%.
