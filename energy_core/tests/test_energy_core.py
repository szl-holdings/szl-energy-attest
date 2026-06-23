"""Tests for szl_energy_core — all pass on CPU (no GPU/NVML), honestly.

They verify the three doctrine-critical invariants:
  * NO fabricated joule when NVML is absent (UNAVAILABLE_NO_NVML, joules None).
  * cheapest_watt picks the truly-cheapest node, and receipts re-hash offline.
  * the placement-receipt hash-chain verifies (and breaks detectably if tampered).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from szl_energy_core import (  # noqa: E402
    CheapestWattLedger,
    GENESIS_PREV,
    cheapest_watt_choice,
    measure_energy,
    nvml_available,
    sha3_canon,
)


# --------------------------------------------------------------------------
# 1. NO fabricated joule when NVML/GPU absent.
# --------------------------------------------------------------------------
def test_no_nvml_no_fake_joule():
    """On this CPU env (no pynvml/GPU), measure_energy MUST yield joules=None
    with the honest UNAVAILABLE label — never a fabricated number."""
    assert nvml_available() is False
    with measure_energy() as m:
        total = sum(i * i for i in range(50_000))  # real CPU work
        assert total > 0
    res = m.result
    assert res.joules is None, "joules must be None when NVML is unavailable"
    assert res.label == "UNAVAILABLE_NO_NVML"
    assert res.evidence == {}
    assert res.wall_s >= 0.0
    d = res.to_dict()
    assert d["joules"] is None and d["label"] == "UNAVAILABLE_NO_NVML"


def test_measure_energy_as_decorator_no_fake_joule():
    """The decorator form also never fabricates a joule with no NVML."""
    meter = measure_energy()

    @meter
    def job():
        return sum(range(10_000))

    out = job()
    assert out == sum(range(10_000))
    assert meter.result.joules is None
    assert meter.result.label == "UNAVAILABLE_NO_NVML"


def test_measure_energy_does_not_suppress_exceptions():
    """The context manager must not swallow errors (honest control flow)."""
    with pytest.raises(ValueError):
        with measure_energy() as m:
            raise ValueError("boom")
    # result still recorded, still no fake joule
    assert m.result.joules is None
    assert m.result.label == "UNAVAILABLE_NO_NVML"


# --------------------------------------------------------------------------
# 2. cheapest_watt picks the truly-cheapest node + receipt re-hashes.
# --------------------------------------------------------------------------
def _two_measured_nodes(price=111.24):
    # rtx J/tok = 910844.34/12002478 ~= 0.07589 ; chaski = 200000/1024134 ~= 0.19529
    return [
        {"name": "rtx-betterwithage", "power_w": 41.0, "tokens": 12_002_478,
         "price_per_mwh": price, "joules_measured": 910_844.34,
         "joules_label": "MEASURED"},
        {"name": "chaski", "power_w": 13.0, "tokens": 1_024_134,
         "price_per_mwh": price, "joules_measured": 200_000.0,
         "joules_label": "MEASURED"},
    ]


def test_cheapest_watt_picks_truly_cheapest():
    """Lower J/token (and thus lower cost/token at the same price) must win."""
    receipt = cheapest_watt_choice(_two_measured_nodes())
    d = receipt["decision"]
    assert d["decision"] == "placed"
    assert d["chosen_node"] == "rtx-betterwithage"
    assert d["rank_metric"] == "cost_per_token"
    assert d["ranking"][0] == "rtx-betterwithage"
    assert d["ranking"][-1] == "chaski"
    assert d["saving_label"] == "MEASURED"
    assert d["saving"]["delta_cost_per_token"] > 0
    assert d["saving"]["baseline_node"] == "chaski"


def test_cheapest_watt_chosen_has_minimum_metric():
    """Independently recompute J/token and confirm the chosen node is the minimum."""
    nodes = _two_measured_nodes()
    receipt = cheapest_watt_choice(nodes)
    d = receipt["decision"]
    intensities = {}
    for c in d["candidates"]:
        if c["joules_per_token"] is not None:
            intensities[c["node"]] = c["joules_per_token"]
    true_min = min(intensities, key=intensities.get)
    assert d["chosen_node"] == true_min


def test_receipt_rehashes_offline():
    """The decision body must re-hash (SHA3-256) to payload_digest, offline."""
    receipt = cheapest_watt_choice(_two_measured_nodes())
    assert sha3_canon(receipt["decision"]) == receipt["payload_digest"]
    assert receipt["payload_digest"].startswith("sha3-256:")
    # entry digest binds prev + payload
    assert sha3_canon({"prev_digest": receipt["prev_digest"],
                       "payload_digest": receipt["payload_digest"]}) \
        == receipt["entry_digest"]


def test_no_choice_when_fewer_than_two_measured():
    """One measured + one pending => no real placement choice; no saving claimed."""
    nodes = [
        {"name": "rtx-betterwithage", "power_w": 41.0, "tokens": 12_002_478,
         "price_per_mwh": 111.24, "joules_measured": 910_844.34,
         "joules_label": "MEASURED"},
        {"name": "chaski", "power_w": 13.0, "tokens": 1_024_134,
         "price_per_mwh": 111.24, "joules_measured": 0.0,
         "joules_label": "PENDING_EXPORTER"},
    ]
    d = cheapest_watt_choice(nodes)["decision"]
    assert d["decision"] == "no_choice"
    assert d["chosen_node"] is None
    assert d["saving"] is None
    assert d["reason"] == "no placement choice this tick"


def test_no_price_yields_estimate_no_fabricated_cost():
    """Two measured nodes but NO grid price => energy-only ranking, ESTIMATE saving,
    and NO fabricated monetary figure."""
    nodes = [{**n, "price_per_mwh": None} for n in _two_measured_nodes()]
    d = cheapest_watt_choice(nodes)["decision"]
    assert d["decision"] == "placed"
    assert d["rank_metric"] == "joules_per_token"
    assert d["saving_label"] == "ESTIMATE"
    assert "delta_cost_per_token" not in (d["saving"] or {})
    assert d["chosen_node"] == "rtx-betterwithage"
    # cost_per_token must be None for every candidate (no price => never assumed)
    for c in d["candidates"]:
        assert c["cost_per_token"] is None


def test_pending_node_never_ranked_on_cost():
    """A node with no per-node measured joules is reported but never chosen."""
    nodes = _two_measured_nodes() + [
        {"name": "ghost", "power_w": 5.0, "tokens": 99, "price_per_mwh": 111.24,
         "joules_measured": 0.0, "joules_label": "PENDING_EXPORTER"},
    ]
    d = cheapest_watt_choice(nodes)["decision"]
    assert "ghost" not in d["ranking"]
    ghost = [c for c in d["candidates"] if c["node"] == "ghost"][0]
    assert ghost["intensity_label"] == "UNKNOWN"
    assert ghost["joules_per_token"] is None


# --------------------------------------------------------------------------
# 3. Hash-chain verification (and tamper detection).
# --------------------------------------------------------------------------
def test_ledger_chain_verifies():
    led = CheapestWattLedger()
    led.record(_two_measured_nodes())
    led.record(_two_measured_nodes()[:1])              # no_choice
    led.record([{**n, "price_per_mwh": None} for n in _two_measured_nodes()])
    st = led.status()
    assert st["decisions_total"] == 3
    assert st["placed"] == 2
    assert st["no_choice"] == 1
    assert st["chain"]["ok"] is True
    assert st["chain"]["length"] == 3
    ok, length, brk = led.verify()
    assert ok is True and length == 3 and brk == -1


def test_ledger_links_prev_to_entry():
    """Each receipt's prev_digest must equal the previous entry_digest (genesis first)."""
    led = CheapestWattLedger()
    r1 = led.record(_two_measured_nodes())
    r2 = led.record(_two_measured_nodes())
    assert r1["prev_digest"] == GENESIS_PREV
    assert r2["prev_digest"] == r1["entry_digest"]


def test_ledger_tamper_is_detected():
    """Mutating a recorded decision body must break offline chain verification."""
    led = CheapestWattLedger()
    led.record(_two_measured_nodes())
    led.record(_two_measured_nodes())
    # tamper: flip the chosen node in the stored decision
    led._records[0]["decision"]["chosen_node"] = "chaski"
    ok, length, brk = led.verify()
    assert ok is False
    assert brk == 0


def test_no_fabricated_joule_anywhere_in_receipt():
    """When a node carries joules_measured=0 / PENDING, the receipt must not invent
    a joules_per_token for it."""
    nodes = [
        {"name": "a", "power_w": 10.0, "tokens": 1000, "price_per_mwh": 100.0,
         "joules_measured": 0.0, "joules_label": "PENDING_EXPORTER"},
        {"name": "b", "power_w": 20.0, "tokens": 0, "price_per_mwh": 100.0},
    ]
    d = cheapest_watt_choice(nodes)["decision"]
    for c in d["candidates"]:
        assert c["joules_per_token"] is None
        assert c["intensity_label"] == "UNKNOWN"
    assert d["decision"] == "no_choice"
