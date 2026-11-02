# SPDX-License-Identifier: Apache-2.0
"""Synthetic NVML controls; these tests are not hardware energy evidence."""

import pytest

from szl_energy_attest import inference_meter
from szl_energy_attest.inference_meter import _energy


class CounterNVML:
    def __init__(self, before, after):
        # First read is the capability probe, followed by the measured interval.
        self.readings = iter([0, before, after])

    def nvmlInit(self):
        pass

    def nvmlDeviceGetCount(self):
        return 1

    def nvmlDeviceGetHandleByIndex(self, index):
        return object()

    def nvmlDeviceGetTotalEnergyConsumption(self, handle):
        value = next(self.readings)
        if isinstance(value, Exception):
            raise value
        return value

    def nvmlDeviceGetPowerUsage(self, handle):
        raise RuntimeError("synthetic power readback unavailable")


@pytest.mark.parametrize("before,after", [(5000, 1000), (0, -1), (-5000, -4000)])
def test_invalid_counter_interval_is_unmeasured(monkeypatch, before, after):
    monkeypatch.setattr(_energy, "_pynvml", CounterNVML(before, after))
    meter = _energy.EnergyMeter()
    meter.start()
    result = meter.stop()
    assert result["mode"] == _energy.MODE_UNMEASURED
    assert result["joules"] is None


@pytest.mark.parametrize("before,after,expected", [(1000, 2500, 1.5), (1000, 1000, 0.0)])
def test_valid_counter_interval_is_preserved(monkeypatch, before, after, expected):
    monkeypatch.setattr(_energy, "_pynvml", CounterNVML(before, after))
    meter = _energy.EnergyMeter()
    meter.start()
    result = meter.stop()
    assert result["mode"] == _energy.MODE_ENERGY_COUNTER
    assert result["joules"] == expected


@pytest.mark.parametrize("before,after", [(RuntimeError("start"), 2500), (1000, RuntimeError("stop"))])
def test_unreadable_counter_is_unmeasured(monkeypatch, before, after):
    monkeypatch.setattr(_energy, "_pynvml", CounterNVML(before, after))
    meter = _energy.EnergyMeter()
    meter.start()
    result = meter.stop()
    assert result["mode"] == _energy.MODE_UNMEASURED
    assert result["joules"] is None


def test_counter_reset_does_not_emit_measured_receipt(monkeypatch):
    monkeypatch.setattr(_energy, "_pynvml", CounterNVML(5000, 1000))
    monkeypatch.setattr(inference_meter, "_maybe_cuda_sync", lambda: None)
    chain = inference_meter.ReceiptChain()
    receipt, output = inference_meter.meter(lambda: "synthetic output", tokens_out=3, chain=chain)
    assert output == "synthetic output"
    assert receipt["mode"] == _energy.MODE_UNMEASURED
    assert receipt["joules"] is None
    assert receipt["tokens_per_joule"] is None
    assert chain.verify() == (True, 1, -1)


class PowerNVML(CounterNVML):
    def __init__(self, readings):
        self.powers = iter([1000, *readings])

    def nvmlDeviceGetTotalEnergyConsumption(self, handle):
        raise RuntimeError("synthetic energy counter unavailable")

    def nvmlDeviceGetPowerUsage(self, handle):
        return next(self.powers)


@pytest.mark.parametrize("readings", [[-1000, 1000], [1000, -1000], [1000, -1000, 1000]])
def test_negative_power_invalidates_entire_interval(monkeypatch, readings):
    monkeypatch.setattr(_energy, "_pynvml", PowerNVML(readings))
    meter = _energy.EnergyMeter()
    meter.start()
    for _ in readings[1:-1]:
        meter.sample()
    result = meter.stop()
    assert result["mode"] == _energy.MODE_UNMEASURED
    assert result["joules"] is None


@pytest.mark.parametrize("power,expected", [(1000, 1.0), (0, 0.0)])
def test_valid_power_integral_is_preserved(monkeypatch, power, expected):
    monkeypatch.setattr(_energy, "_pynvml", PowerNVML([power, power]))
    times = iter([0.0, 0.0, 1.0, 1.0])
    monkeypatch.setattr(_energy.time, "perf_counter", lambda: next(times))
    meter = _energy.EnergyMeter()
    meter.start()
    result = meter.stop()
    assert result["mode"] == _energy.MODE_POWER_INTEGRAL
    assert result["joules"] == expected


def test_clean_interval_recovers_after_invalid_power(monkeypatch):
    monkeypatch.setattr(_energy, "_pynvml", PowerNVML([-1000, 1000, 1000, 1000]))
    meter = _energy.EnergyMeter()
    meter.start()
    assert meter.stop()["mode"] == _energy.MODE_UNMEASURED
    meter.start()
    assert meter.stop()["mode"] == _energy.MODE_POWER_INTEGRAL
