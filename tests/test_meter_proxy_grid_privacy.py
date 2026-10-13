# SPDX-License-Identifier: Apache-2.0
"""Offline regressions: grid-provider failure text never enters a receipt.

``meter_proxy.grid.fetch_carbon_context`` degrades every provider failure to an
honest UNAVAILABLE carbon block. The proxy embeds that block in each
per-inference receipt, appends it to the durable store and returns it verbatim
from ``GET /receipts/{seq}``. Its ``reason`` therefore records only the
exception type, never the exception text, which can echo provider URLs,
network detail or the outbound credential header.

Only inert strings are used and every network boundary is mocked or blocked.
"""
import http.client
import json
import urllib.error

import pytest

from szl_energy_attest.meter_proxy import grid
from szl_energy_attest.meter_proxy.receipts import ReceiptIssuer

_INERT = "INERT_GRID_DETAIL_KILO"
_KEY = "INERT_GRID_KEY_LIMA"
_PROVIDERS = ("electricity_maps", "watttime")
_ENERGY = {
    "state": "UNAVAILABLE",
    "measured_joules": None,
    "estimated_joules": None,
    "measurement_mode": None,
    "detail": "offline grid privacy regression; no hardware measurement",
}


def _failures():
    return (
        urllib.error.URLError("[Errno -2] Name or service not known " + _INERT),
        urllib.error.HTTPError("https://grid.invalid/" + _INERT, 401,
                               "Unauthorized " + _INERT, {}, None),
        ValueError("Invalid header value b'Bearer %s %s'" % (_KEY, _INERT)),
        TimeoutError("timed out " + _INERT),
        json.JSONDecodeError("Expecting value " + _INERT, "{}", 0),
    )


def _configure(monkeypatch, provider, key=_KEY):
    monkeypatch.setenv("SZL_GRID_PROVIDER", provider)
    monkeypatch.setenv("SZL_GRID_API_KEY", key)
    monkeypatch.setenv("SZL_GRID_ZONE", "OFFLINE-ZONE")


def _assert_type_only(block, exc_type, fragments):
    assert block["label"] == grid.LABEL_UNAVAILABLE
    assert block["carbon_intensity_gco2_per_kwh"] is None
    assert block["reason"] == "grid signal fetch failed: %s" % exc_type
    serialized = json.dumps(block, sort_keys=True)
    for fragment in fragments:
        assert fragment not in serialized


@pytest.mark.parametrize("provider", _PROVIDERS)
@pytest.mark.parametrize("index", range(len(_failures())))
def test_fetch_failure_reason_records_type_only(monkeypatch, provider, index):
    exc = _failures()[index]
    _configure(monkeypatch, provider)

    def failing_urlopen(*args, **kwargs):
        raise exc

    monkeypatch.setattr(grid.urllib.request, "urlopen", failing_urlopen)
    block = grid.fetch_carbon_context()
    _assert_type_only(block, type(exc).__name__, (_INERT, _KEY))


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_stdlib_header_error_never_echoes_grid_key(monkeypatch, provider):
    # A key with an embedded line break makes http.client reject the outbound
    # credential header before any connection, with the full header value in
    # the error text. Connections are blocked so the test stays offline.
    first, second = "INERT_GRID_KEY_MIKE", "INERT_GRID_KEY_NOVEMBER"
    _configure(monkeypatch, provider, key=first + "\n" + second)

    def no_network(self, *args, **kwargs):
        raise AssertionError("network connection attempted")

    monkeypatch.setattr(http.client.HTTPConnection, "connect", no_network)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", no_network)
    block = grid.fetch_carbon_context()
    _assert_type_only(block, "ValueError", (first, second))


def test_receipt_store_and_record_carry_no_grid_failure_text(monkeypatch, tmp_path):
    _configure(monkeypatch, "watttime")

    def failing_urlopen(*args, **kwargs):
        raise urllib.error.URLError("proxy refused %s %s" % (_KEY, _INERT))

    monkeypatch.setattr(grid.urllib.request, "urlopen", failing_urlopen)
    issuer = ReceiptIssuer(str(tmp_path))
    record = issuer.issue(model="offline-test-model", tokens_in=None, tokens_out=None,
                          energy=dict(_ENERGY), carbon=grid.fetch_carbon_context(),
                          latency_seconds=0.0)
    assert record["body"]["carbon"]["reason"] == "grid signal fetch failed: URLError"
    stored = (tmp_path / "receipts.jsonl").read_text(encoding="utf-8")
    for text in (json.dumps(record, sort_keys=True), stored):
        assert _INERT not in text
        assert _KEY not in text
