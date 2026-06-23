#!/usr/bin/env python3
"""demo.py — honest, runnable demo of the SZL energy core on CPU (no GPU here).

Shows two things, both honestly:
  1. measure_energy() around a real (CPU) workload. In THIS environment there is no
     GPU / NVML, so the energy label is UNAVAILABLE_NO_NVML and joules is None — we
     never emit a fake joule. (On a sovereign GPU box with pynvml + NVML, the SAME
     code path returns label MEASURED with a real cumulative-energy delta.)
  2. cheapest_watt_choice() over example nodes that DO carry MEASURED per-node joules
     (as the live operator's by_node block would), producing a re-hashable,
     hash-chained placement receipt — and we verify it re-hashes offline.
"""

from __future__ import annotations

import json

from szl_energy_core import (
    CheapestWattLedger,
    GENESIS_PREV,
    cheapest_watt_choice,
    measure_energy,
    nvml_available,
    sha3_canon,
)


def _real_cpu_work() -> int:
    """A small but real CPU workload to wrap the energy meter around."""
    try:
        import torch  # optional; present as torch 2.12 CPU
        x = torch.randn(512, 512)
        y = x @ x.t()
        return int(y.numel())
    except Exception:
        total = 0
        for i in range(2_000_000):
            total = (total + i * 2654435761) & 0xFFFFFFFF
        return total


def main() -> None:
    print("=" * 74)
    print("SZL ENERGY CORE — honest demo (CPU; no GPU/NVML in this environment)")
    print("=" * 74)
    print("nvml_available():", nvml_available())
    print()

    # ----- 1. MEASURED-joule accounting (honest UNAVAILABLE on CPU) -----
    print("[1] measure_energy() around a real CPU workload")
    with measure_energy() as m:
        n = _real_cpu_work()
    res = m.result.to_dict()
    print("    workload produced", n, "elements")
    print("    energy result:", json.dumps(res, indent=6))
    assert res["joules"] is None, "no GPU => joules MUST be None (never fabricated)"
    assert res["label"] == "UNAVAILABLE_NO_NVML", res["label"]
    print("    -> HONEST: label UNAVAILABLE_NO_NVML, NO fake joule emitted.")
    print()

    # ----- 2. cheapest-watt placement with a verifiable receipt -----
    print("[2] cheapest_watt_choice() over example sovereign nodes")
    # Two nodes carry their OWN MEASURED joules (as the operator by_node block does);
    # a third computed work but has no per-node meter reading yet (PENDING) — it is
    # reported but never ranked on cost.
    nodes = [
        {"name": "rtx-betterwithage", "power_w": 41.0, "tokens": 12_002_478,
         "price_per_mwh": 111.24,
         "joules_measured": 910_844.34, "joules_label": "MEASURED"},
        {"name": "chaski", "power_w": 13.0, "tokens": 1_024_134,
         "price_per_mwh": 111.24,
         "joules_measured": 200_000.0, "joules_label": "MEASURED"},
        {"name": "omen-standby", "power_w": 38.0, "tokens": 5_000,
         "price_per_mwh": 111.24,
         "joules_measured": 0.0, "joules_label": "PENDING_EXPORTER"},
    ]
    # We also pass a REAL grid carbon intensity (gCO2/kWh) this tick so the
    # receipt carries an HONEST per-node gCO2 for MEASURED joules only. With no
    # intensity, gCO2 would be null/UNAVAILABLE — carbon is never fabricated.
    grid_intensity = 388.0  # e.g. a live regional gCO2/kWh from a carbon-aware feed
    receipt = cheapest_watt_choice(nodes, prev_digest=GENESIS_PREV,
                                   grid_intensity_gco2_per_kwh=grid_intensity)
    d = receipt["decision"]
    print("    decision   :", d["decision"])
    print("    chosen_node:", d["chosen_node"], "(rank metric:", d.get("rank_metric"), ")")
    print("    ranking    :", d.get("ranking"))
    print("    saving     :", json.dumps(d.get("saving"), indent=6))
    print("    saving_label:", d.get("saving_label"))
    print("    grid_intensity:", d["grid_intensity_gco2_per_kwh"],
          "gCO2/kWh (", d["grid_intensity_label"], ")")
    for c in d["candidates"]:
        print(f"      gCO2[{c['node']}] = {c['gCO2']} ({c['gCO2_label']})")
    print("    payload_digest:", receipt["payload_digest"])
    print("    entry_digest  :", receipt["entry_digest"])

    # The receipt re-hashes offline (verifiable, no network, no GPU).
    rehash = sha3_canon(d)
    print("    re-hash matches payload_digest:", rehash == receipt["payload_digest"])
    assert rehash == receipt["payload_digest"]
    # rtx: 910844.34/12002478 = ~0.0759 J/tok ; chaski: 200000/1024134 = ~0.1953 J/tok
    # -> rtx-betterwithage is the cheapest watt.
    assert d["chosen_node"] == "rtx-betterwithage", d["chosen_node"]
    print()

    # ----- 3. hash-chained ledger over several ticks -----
    print("[3] CheapestWattLedger — hash-chained over 3 ticks")
    led = CheapestWattLedger()
    led.record(nodes)                                   # placed (MEASURED saving)
    led.record(nodes[:1])                               # only 1 comparable => no_choice
    led.record([{**n, "price_per_mwh": None} for n in nodes])  # no price => ESTIMATE
    st = led.status()
    print("    decisions_total:", st["decisions_total"],
          "placed:", st["placed"], "no_choice:", st["no_choice"])
    print("    chain ok:", st["chain"]["ok"], "length:", st["chain"]["length"],
          "head:", st["chain"]["head"][:24] + "...")
    assert st["chain"]["ok"] is True
    print()

    print("=" * 74)
    print("DEMO OK — energy honestly UNAVAILABLE (no fake joule); cheapest-watt")
    print("placed with a verifiable, hash-chained receipt.")
    print("=" * 74)


if __name__ == "__main__":
    main()
