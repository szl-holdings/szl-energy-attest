# Leaders Study - szl-energy-attest (spaces pass, docs-only)

Lap: OUROBOROS spaces batch-2 audit #2, target `szl-holdings/szl-governed`-class successor **szl-energy-attest** (the deprecated governed-inference-meter line now lives here). This document positions the repository against the four measured-energy domain leaders scanned and verified 2026-11-24. Nothing in this document is approved, implemented, benchmarked, or claimed; every absorb item below is an **unapproved candidate** and every open item is an **open question**. This lap adds documentation only.

## What this repository is

- MEASURED-NVML joules per inference, reported with an honest UNAVAILABLE null when no measurement is possible; never fabricates a joule.
- Hash-chained, signable per-inference energy receipts (the receipt spine, in-toto attestations, signing hardening tests).
- Cheapest-watt placement context, overclaim-guard CI, and scoped agentic-efficiency comparisons that leave energy_savings_proven, production_qualified, and automatic_routing_authorized always false.

## Leaders studied (web-verified 2026-11-24)

1. **AI Energy Score leaderboard (Hugging Face + Salesforce)** - fixed functional unit (GPU energy Wh per 1k queries), task-class taxonomy, consumer-facing star scores, downloadable dataset, public methodology caveats.
2. **Kepler (CNCF sustainable-computing)** - per-process and per-pod attribution: NVML instantaneous power scaled by per-process SM utilization (GPU), RAPL deltas apportioned by CPU-time ratio (CPU); active/idle power split with a disclosed idle-calibration limitation and manual override.
3. **MLPerf Power (MLCommons)** - external certified power analyzer (SPEC PTDaemon class) with director/SUT protocol; a measurement tier above on-device counters, with its own assumptions.
4. **ISO/IEC 21031:2024 (Software Carbon Intensity)** - software boundary, functional unit, operational + embodied components, measurement and calculation methods, baseline-comparison procedure, explicit exclusions.

## Gap analysis

The repository measures whole-device NVML joules per inference with honest nulls, but currently has: no normalized functional unit (per-1k queries), no idle-baseline calibration policy, no per-process attribution, and no consumer-facing score. The leaders above have all four. Conversely, none of the four leaders ship signature-bound per-inference energy receipts; that receipt moat stands.

## Absorb candidates (UNAPPROVED - candidates only, nothing approved or implemented)

- **A1 Functional unit.** Normalize reporting to a fixed functional unit (energy per 1k queries at the AI Energy Score) alongside per-inference joules. Study doc before any schema change.
- **A2 Idle-baseline calibration policy.** A written policy for idle-power measurement, calibration frequency, disclosed caveats, and manual override, Kepler-style; must preserve the honest-null doctrine.
- **A3 Per-process attribution study.** Assess whether SM-utilization / CPU-time-ratio attribution could be added as a clearly labeled derived estimate, distinct from measured whole-device joules, with no re-labelling of estimates as measurements.
- **A4 Consumer-facing scorecard doc.** A documentation-only scorecard explaining how a consumer would read our receipts and compare offerings, borrowing the leaderboard's disclosure style; no star scoring or claims implied.

## Open questions (OPEN - unresolved, not adopted)

- **A5 External-analyzer measurement tier.** Should a certified external analyzer tier (MLPerf Power / SPEC PTDaemon class) ever be supported, and under what owner gate? Cost, hardware, and audit implications are unstudied.
- **A6 SCI-shaped summary.** Should an optional ISO/IEC 21031-shaped summary (boundary + functional unit + operational + embodied) be offered as a derived report? Embodied-carbon accounting is outside current scope and would need its own evidence chain.

## Non-goals

- No claim of energy savings, production qualification, benchmark results, or routing authorization anywhere in this study.
- No modification of the receipt schema, meters, CI, workflows, or release gates in this lap.
- No anchoring, cosigning, or third-party integration decided here.
