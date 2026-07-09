# SPEC — szl_energy_attest receipt schema & verification

Schema id: `szl_energy_attest/receipt@1`. Apache-2.0. © 2026 SZL Holdings.

A **receipt** is a canonical JSON object recording one unit of governed compute and
its energy provenance. Every field is either a MEASURED fact or an explicit, truthful
`null`. Receipts form a hash chain: each links to the previous via `prev` → `digest`.

## 1. Receipt body fields

The **body** is the set of fields that are hashed into `payload_digest`. Field order
does not matter — hashing is canonical (sorted keys, tight separators).

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | string | Always `"szl_energy_attest/receipt@1"`. |
| `measured_joules` | number \| **null** | Real joules **only** when `label == "MEASURED"` (a fresh NVML/exporter delta). Otherwise `null`. Never fabricated. |
| `label` | string | One of `MEASURED`, `UNAVAILABLE`, `SAMPLE`. Decided by the energy core's joule-truth path, not a convenience flag. |
| `tokens` | integer | MEASURED tokens produced/consumed by the work. |
| `node` | string | The node that computed the work (its exporter label). |
| `price_per_mwh` | number \| **null** | Live grid price (€/MWh) passed through verbatim, or `null`. Never assumed. |
| `gCO2` | number \| **null** | Grams CO₂ for the work when known from a real source, or `null`. Never modeled-as-fact. |
| `decision` | string | Placement decision: e.g. `placed` (a cheapest-watt choice was made) or `no_choice` (fewer than two comparable MEASURED nodes this tick). |
| `note` | string | Free-text honesty note (e.g. why energy is null). |
| `lambda` | string | `"Conjecture 1 (advisory; trust never 100%)"`. Λ is advisory, never asserted as proven. |
| `sovereign` | boolean | Always `false` on this accounting path. |

## 2. Chain / provenance fields

These bind the body into the chain. They are **not** part of the body hash.

| Field | Type | Meaning |
| --- | --- | --- |
| `prev` | string | `digest` of the previous receipt; genesis = 64 ASCII zeros. |
| `payload_digest` | string | `sha256_canon(body)` — re-hashable offline. |
| `digest` | string | `sha256_canon({"prev": prev, "payload_digest": payload_digest})`. The next receipt sets `prev = digest`. |

The canonical hash is supplied by the runnable SZL energy core when importable, so
receipts share one hash math across the platform:

- `szl_energy_core` present -> **SHA3-256**: `"sha3-256:" + sha3_256(json.dumps(obj, sort_keys=True, separators=(",",":")))` (digests prefixed `sha3-256:`).
- `szl_cheapest_watt` present -> SHA-256, prefixed `sha256:`.
- neither present -> byte-identical local SHA-256 fallback, prefixed `sha256:`.

`canon_source()` reports which is active. Within a single chain the hash function is
fixed, so receipts minted and re-verified by the same source reproduce identical
digests. Verification is **algorithm-agnostic**: the verifier recomputes each
receipt under the algorithm that receipt declares in its own `digest` prefix
(`sha3-256:` or `sha256:`), NOT under whatever canon source happens to be active on
the verifying box. Because the canonical JSON is identical for both algorithms
(sorted keys, tight separators, `allow_nan=False`), a chain minted under SHA3-256 on
a metering node re-verifies on a CPU-only auditor box with no core (and vice-versa).
An unknown/forged algorithm prefix fails closed. This holds for both
`verify_chain` and `verify_receipt_offline`.

## 3. Label semantics (the honesty contract)

- `MEASURED` — `measured_joules` is a real number from a fresh NVML delta. Requires a
  GPU + live exporter on the computing node.
- `UNAVAILABLE` — no GPU / no fresh NVML delta on this box. `measured_joules` is
  `null`. The chain still verifies; the provenance is real even if the joules are not.
- `SAMPLE` — real work ran (token/wall counts honest) but its energy is **not** a
  billable MEASURED joule, so `measured_joules` is `null`.

**Invariant:** if `label != "MEASURED"` then `measured_joules == null`. `build_receipt`
enforces this; `verify_chain` will reject any receipt whose digests do not match the
declared body, so a hand-edited joule number breaks the chain.

## 3a. Optional `grid_context` block (REPORTED pass-through)

A receipt MAY carry an **optional** `grid_context` object recording the *observed grid
signal* at run time (carbon intensity + price), fetched from a public API. It documents
that a run happened in a cleaner/cheaper/curtailed window. It is **REPORTED pass-through
provenance, never a MEASURED joule** — it is independent of the NVML joule-truth path and
never alters `measured_joules` / `label`. **This does not create or measure free energy;
scheduling compute into cleaner windows is the only transfer.**

`grid_context` is part of the hashed body **only when present**, so it is tamper-evident,
while receipts without it re-hash byte-identically to the pre-`grid_context` schema
(back-compat, exactly like the `gCO2_label` field). `sanitize_grid_context` coerces every
numeric field through the finite-or-null gate and forces each `*_label` to follow the
actual value (a `null` value can never be labelled `REPORTED`).

| Field | Type | Meaning |
| --- | --- | --- |
| `provider` | string | Signal provider id: `uk_carbon_intensity` (keyless default), `electricity_maps` / `watttime` (OPTIONAL, key-gated). |
| `source` | string | The signal's source URL. |
| `region` | string \| **null** | Grid region (e.g. `GB`), or `null`. |
| `observed_at` | string \| **null** | ISO-8601 timestamp the reading applies to (from the signal), or `null`. |
| `fetched_at` | string \| **null** | ISO-8601 timestamp when we fetched it. |
| `carbon_intensity_gco2_per_kwh` | number \| **null** | Observed grid carbon intensity, carried verbatim, or `null`. |
| `carbon_intensity_kind` | string \| **null** | `grid_average` (UK CI API) or `marginal` — never over-claimed. |
| `carbon_intensity_index` | string \| **null** | Provider's own index text (e.g. `moderate`), pass-through. |
| `carbon_intensity_label` | string | `REPORTED` (real value present) or `UNAVAILABLE` (value is `null`). |
| `price_per_mwh` | number \| **null** | Wholesale price where the provider gives one, verbatim, else `null`. |
| `price_label` | string | `REPORTED` or `UNAVAILABLE`. |
| `note` | string | Honesty note. |

**Honest-null rule:** a missing/unreachable/malformed signal, an unknown provider, or a
key-gated provider with no key ALL yield an all-`null` block with `UNAVAILABLE` labels.
`fetch_grid_context` never raises to the caller and never invents a number. The UK Carbon
Intensity API publishes carbon intensity but **no price**, so `price_per_mwh` is always
`null`/`UNAVAILABLE` for that provider — honestly.

## 4. Verification procedure (offline, by anyone)

Given a list of receipts `[r0, r1, …]`:

1. Set `prev = "0"*64` (genesis).
2. For each receipt `r` in order:
   a. Recompute `body` from the 11 body fields above and `pd = sha256_canon(body)`.
   b. Recompute `dg = sha256_canon({"prev": r.prev, "payload_digest": pd})`.
   c. Assert `pd == r.payload_digest`, `dg == r.digest`, and `r.prev == prev`.
   d. Set `prev = r.digest`.
3. If every assertion holds, the chain is **valid**. The first failing index
   identifies the tampered or misordered receipt.

Reference implementation: `szl_energy_attest.verify_chain(receipts)` →
`(ok: bool, length: int, first_break_index: int)`. A `first_break_index` of `-1`
means no break.

## 5. Signing (optional)

DSSE signing is layered on by the caller when a real cosign key is present. Absent a
key, a receipt is **honest-but-unsigned** — the hash chain still proves integrity and
ordering. A receipt is never marked signed without a real signature.
