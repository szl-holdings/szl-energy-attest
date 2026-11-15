# COMPEL / Watershed alignment for the szl_energy_attest receipt

Status: proposal (receipt@2 extension, additive, non-breaking). No claim of
certification or compliance is made here; this document maps our measured
fields onto the COMPEL three-layer model and the Watershed location-based
carbon accounting methodology so the estate's receipts stay directly
expressible against GHG Protocol Scope 2 / CSRD-style reporting when the
owner elects to report.

## 1. Where receipt@1 already aligns

COMPEL frames AI energy measurement as three layers — methodology
(attribution), instrumentation (telemetry source), reporting standard.
receipt@1 is already honest on the parts that matter:

- **Bottom-up attribution, on-device instrumentation**: measured_joules is
  a fresh NVML/exporter delta attributed to the work (bottom-up,
  per-process telemetry), never a top-down facility allocation.
- **Measured-or-null doctrine**: every field is a MEASURED fact or an
  explicit null (label UNAVAILABLE / SAMPLE governs reuse). COMPEL's first
  rule - a first-week estimate must not masquerade as a production
  measurement - is enforced structurally by the schema.
- **Tamper-evidence**: hash-chained payloads make the measurement record
  auditable (chain digest math in SPEC.md section 2).

## 2. Gaps vs COMPEL / Watershed (proposed receipt@2 fields)

| Gap | COMPEL/Watershed requirement | Proposed additive field |
| --- | --- | --- |
| No disclosure of WHICH instrumentation produced the telemetry | instrumentation layer must be named (software sampler / cloud API / PDU probe) | `instrument`: "nvml" | "exporter" | "cloud_api" | "pdu" (required, non-null) |
| Methodology not declared per receipt | attribution must be stated (top-down / bottom-up / hybrid) | `attribution`: "bottom_up" (fixed for this path; future hybrid requires schema rev) |
| No measurement window | an energy delta is meaningless without its window | `window_start_s`, `window_end_s` (unix seconds, required when label == MEASURED) |
| No workload identity | what was measured (model/hardware) | `model`, `hardware` (string identifiers; null only with explicit note) |
| No measurement boundary / PUE disclosure | boundary (device vs node vs datacenter) and PUE treatment must be explicit | `boundary`: "device" | "node" | "datacenter"; `pue`: number | null (never defaulted) |
| gCO2 lacks its provenance | Watershed: emissions = kWh x grid carbon intensity, location-based, with source + timestamp | `grid_intensity_gco2_per_kwh`: number | null; `grid_intensity_source` + `grid_intensity_method`: "location_based" | "market_based" (required when gCO2 non-null) |
| kWh convenience absent | reporting standards report kWh | `measured_kwh` (DERIVED from measured_joules / 3.6e6, labeled derived, never independently asserted) |

All new fields follow the same doctrine: measured-or-null, canonical-hash
covered (schema id bumps to `szl_energy_attest/receipt@2`), and the note
field must state why any required-when-non-null field is null.

## 3. Reporting-standard expressibility (no compliance claim)

receipt@2 is DESIGNED to be expressible against GHG Protocol Scope 2
(location-based via grid_intensity_method), CSRD-style disclosure
(boundary + PUE explicit), and the HF AI Energy Score leaderboard shape
(workload + hardware + energy). Expressible does not mean compliant or
certified: certification is owner-gated and out of scope of this document.

## 4. Watershed methodology mapping

- Operational electricity emissions = kWh x grid carbon intensity. Our
  gCO2 already equals this product; receipt@2 adds the intensity, source,
  timestamp and method so the product is re-derivable and auditable.
- Location-based vs market-based: receipt@2 separates the two; market-based
  figures additionally require instrument/contract provenance (future
  field; do not fabricate).
- Hourly matching: window_start_s enables time-matched intensity; the
  source field must say whether the intensity series is hourly or annual-
  average. Annual-average must be labeled as such in note.

## 5. Implementation plan

1. Extend the energy core receipt builder with the receipt@2 fields
   (additive; v1 remains verifiable, v2 readers reject v1 and vice versa
   per schema id).
2. Update SPEC.md with the @2 field table mirroring this document.
3. Chain compatibility: genesis and chaining math unchanged; a v2 chain is
   a NEW chain (no cross-version linking - mixed-version chains refuse
   fail-closed).

## References

- COMPEL Framework, "Measuring AI Energy Use: Methodologies, Tools, and
  Reporting Standards" (Certification Body of Knowledge Module 1.9,
  Article 2): https://www.compelframework.org/articles/measuring-ai-energy-use
- Watershed methodology for electricity emissions (location-based grid
  carbon intensity accounting): https://www.watershed.com
- GHG Protocol Scope 2 Guidance.
- EU AI Act Article 95 (voluntary codes of conduct) - referenced as a
  reporting standard option only.
