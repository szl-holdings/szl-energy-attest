# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Hermetic tests for the honest grid_context receipt block.

Runs WITHOUT a GPU and WITHOUT network — the HTTP transport is INJECTED, so no
live call is ever made in CI. Asserts the honesty contract:
  * every grid_context value is a REPORTED pass-through carried verbatim with a
    source + timestamp, or an honest null + UNAVAILABLE — never invented;
  * a missing / unreachable / malformed signal degrades to UNAVAILABLE nulls;
  * the OPTIONAL key-gated providers (Electricity Maps / WattTime) never require
    a key — absent one they are honestly UNAVAILABLE;
  * a receipt carrying grid_context still hash-verifies (verify_chain AND the
    copy-pasteable verify_receipt_offline) and is tamper-evident;
  * a receipt WITHOUT grid_context hashes byte-identically to the legacy schema;
  * grid_context NEVER fabricates a joule — the NVML honest-null posture holds.

Run directly (no pytest needed):  python tests/test_grid_context.py
Or with pytest:                    pytest tests/
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from szl_energy_attest import (  # noqa: E402
    build_receipt, verify_chain, verify_receipt_offline, GENESIS_PREV,
    LABEL_UNAVAILABLE, fetch_grid_context, sanitize_grid_context,
    unavailable_grid_context, GRID_LABEL_REPORTED, GRID_LABEL_UNAVAILABLE,
    PROVIDER_UK_CARBON_INTENSITY, PROVIDER_ELECTRICITY_MAPS, PROVIDER_WATTTIME,
)
from szl_energy_attest._grid import UK_CI_NATIONAL_URL, CI_KIND_GRID_AVERAGE  # noqa: E402


# --- fake transports (no network) ------------------------------------------

def _uk_ok_transport(url, headers, timeout):
    assert url == UK_CI_NATIONAL_URL
    return {"data": [{
        "from": "2026-07-09T18:30Z", "to": "2026-07-09T19:00Z",
        "intensity": {"forecast": 133, "actual": 121, "index": "moderate"},
    }]}


def _uk_forecast_only_transport(url, headers, timeout):
    return {"data": [{
        "from": "2026-07-09T18:30Z", "to": "2026-07-09T19:00Z",
        "intensity": {"forecast": 90, "actual": None, "index": "low"},
    }]}


def _uk_empty_transport(url, headers, timeout):
    return {"data": [{"from": "x", "to": "y", "intensity": {}}]}


def _boom_transport(url, headers, timeout):
    raise OSError("network down")


# --- fetch_grid_context: REPORTED pass-through -----------------------------

def test_uk_fetch_reports_actual_verbatim():
    gc = fetch_grid_context(PROVIDER_UK_CARBON_INTENSITY,
                            _transport=_uk_ok_transport)
    assert gc["provider"] == PROVIDER_UK_CARBON_INTENSITY
    assert gc["source"] == UK_CI_NATIONAL_URL
    assert gc["region"] == "GB"
    # actual preferred over forecast, carried VERBATIM (not modelled).
    assert gc["carbon_intensity_gco2_per_kwh"] == 121
    assert gc["carbon_intensity_label"] == GRID_LABEL_REPORTED
    assert gc["carbon_intensity_kind"] == CI_KIND_GRID_AVERAGE  # NOT "marginal"
    assert gc["carbon_intensity_index"] == "moderate"
    assert gc["observed_at"] == "2026-07-09T18:30Z"
    assert gc["fetched_at"] and gc["fetched_at"].endswith("Z")
    # UK CI API publishes no price -> honest null / UNAVAILABLE (never invented).
    assert gc["price_per_mwh"] is None
    assert gc["price_label"] == GRID_LABEL_UNAVAILABLE


def test_uk_fetch_falls_back_to_forecast_honestly():
    gc = fetch_grid_context(PROVIDER_UK_CARBON_INTENSITY,
                            _transport=_uk_forecast_only_transport)
    assert gc["carbon_intensity_gco2_per_kwh"] == 90
    assert gc["carbon_intensity_label"] == GRID_LABEL_REPORTED
    assert "forecast" in gc["note"]


def test_uk_fetch_empty_intensity_is_unavailable_not_invented():
    gc = fetch_grid_context(PROVIDER_UK_CARBON_INTENSITY,
                            _transport=_uk_empty_transport)
    assert gc["carbon_intensity_gco2_per_kwh"] is None
    assert gc["carbon_intensity_label"] == GRID_LABEL_UNAVAILABLE


def test_network_failure_is_honest_unavailable_never_raises():
    gc = fetch_grid_context(PROVIDER_UK_CARBON_INTENSITY,
                            _transport=_boom_transport)
    assert gc["carbon_intensity_gco2_per_kwh"] is None
    assert gc["carbon_intensity_label"] == GRID_LABEL_UNAVAILABLE
    assert gc["price_per_mwh"] is None


def test_optional_providers_never_require_a_key():
    for prov in (PROVIDER_ELECTRICITY_MAPS, PROVIDER_WATTTIME):
        gc = fetch_grid_context(prov)  # no api_key, no transport
        assert gc["provider"] == prov
        assert gc["carbon_intensity_label"] == GRID_LABEL_UNAVAILABLE
        assert gc["carbon_intensity_gco2_per_kwh"] is None
        assert "key" in gc["note"].lower()


def test_unknown_provider_is_unavailable():
    gc = fetch_grid_context("not_a_provider")
    assert gc["carbon_intensity_label"] == GRID_LABEL_UNAVAILABLE


# --- sanitize_grid_context: honesty gate -----------------------------------

def test_sanitize_none_returns_none():
    assert sanitize_grid_context(None) is None


def test_sanitize_drops_nonfinite_and_forces_labels():
    dirty = {
        "provider": "uk_carbon_intensity", "source": "http://x",
        "carbon_intensity_gco2_per_kwh": float("nan"),  # must be dropped
        "carbon_intensity_label": "REPORTED",           # must be corrected
        "price_per_mwh": float("inf"),                   # must be dropped
        "price_label": "REPORTED",                       # must be corrected
    }
    gc = sanitize_grid_context(dirty)
    assert gc["carbon_intensity_gco2_per_kwh"] is None
    assert gc["carbon_intensity_label"] == GRID_LABEL_UNAVAILABLE
    assert gc["price_per_mwh"] is None
    assert gc["price_label"] == GRID_LABEL_UNAVAILABLE


def test_sanitize_passes_real_numbers_through():
    gc = sanitize_grid_context({
        "provider": "p", "source": "http://x",
        "carbon_intensity_gco2_per_kwh": 42.5, "price_per_mwh": 88.0,
    })
    assert gc["carbon_intensity_gco2_per_kwh"] == 42.5
    assert gc["carbon_intensity_label"] == GRID_LABEL_REPORTED
    assert gc["price_per_mwh"] == 88.0
    assert gc["price_label"] == GRID_LABEL_REPORTED


# --- receipts carrying grid_context ----------------------------------------

def test_receipt_with_grid_context_verifies_both_verifiers():
    gc = fetch_grid_context(PROVIDER_UK_CARBON_INTENSITY,
                            _transport=_uk_ok_transport)
    r = build_receipt(tokens=10, node="cpu-node", prev=GENESIS_PREV,
                      grid_context=gc)
    # grid_context is attached to the receipt body (tamper-evident).
    assert r["grid_context"]["carbon_intensity_gco2_per_kwh"] == 121
    # energy stays honest-null: grid_context NEVER fabricates a joule.
    assert r["measured_joules"] is None
    assert r["label"] == LABEL_UNAVAILABLE
    ok, length, brk = verify_chain([r])
    assert ok and length == 1 and brk == -1
    res = verify_receipt_offline([r])
    assert res["ok"] is True and res["honesty_ok"] is True


def test_grid_context_is_tamper_evident():
    gc = fetch_grid_context(PROVIDER_UK_CARBON_INTENSITY,
                            _transport=_uk_ok_transport)
    r = build_receipt(tokens=10, node="cpu-node", prev=GENESIS_PREV,
                      grid_context=gc)
    # Forge a cleaner-looking intensity: the hash must break.
    r["grid_context"]["carbon_intensity_gco2_per_kwh"] = 1.0
    ok, _, brk = verify_chain([r])
    assert (not ok) and brk == 0
    res = verify_receipt_offline([r])
    assert res["ok"] is False


def test_receipt_without_grid_context_is_byte_identical_legacy():
    # Back-compat: omitting grid_context must hash exactly as before (no field).
    a = build_receipt(tokens=10, node="cpu-node", prev=GENESIS_PREV)
    b = build_receipt(tokens=10, node="cpu-node", prev=GENESIS_PREV,
                      grid_context=None)
    assert "grid_context" not in a
    assert a["payload_digest"] == b["payload_digest"]
    assert a["digest"] == b["digest"]
    assert verify_chain([a])[0] is True


def test_chain_mixes_grid_and_legacy_receipts():
    gc = fetch_grid_context(PROVIDER_UK_CARBON_INTENSITY,
                            _transport=_uk_ok_transport)
    r0 = build_receipt(tokens=1, node="n", prev=GENESIS_PREV)  # legacy
    r1 = build_receipt(tokens=2, node="n", prev=r0["digest"],
                       grid_context=gc)                        # with grid_context
    r2 = build_receipt(tokens=3, node="n", prev=r1["digest"],
                       grid_context=unavailable_grid_context(
                           PROVIDER_UK_CARBON_INTENSITY, UK_CI_NATIONAL_URL))
    ok, length, brk = verify_chain([r0, r1, r2])
    assert ok and length == 3 and brk == -1
    assert verify_receipt_offline([r0, r1, r2])["ok"] is True


def test_grid_context_unavailable_block_verifies():
    gc = unavailable_grid_context(PROVIDER_UK_CARBON_INTENSITY, UK_CI_NATIONAL_URL)
    r = build_receipt(tokens=5, node="n", prev=GENESIS_PREV, grid_context=gc)
    assert r["grid_context"]["carbon_intensity_label"] == GRID_LABEL_UNAVAILABLE
    assert verify_chain([r])[0] is True


if __name__ == "__main__":
    failures = 0
    for name, obj in sorted(globals().items()):
        if name.startswith("test_") and callable(obj):
            try:
                obj()
                print("PASS", name)
            except AssertionError as e:  # noqa: PERF203
                failures += 1
                print("FAIL", name, e)
    print("\n%s" % ("ALL PASS" if failures == 0 else "%d FAILED" % failures))
    sys.exit(1 if failures else 0)
