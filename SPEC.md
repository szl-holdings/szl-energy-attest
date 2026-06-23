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
digests. The verifier recomputes whatever `payload_digest`/`digest` the receipts
declare using the active canonical hash.

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
