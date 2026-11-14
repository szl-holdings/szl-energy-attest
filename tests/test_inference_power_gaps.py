# SPDX-License-Identifier: Apache-2.0
"""Synthetic NVML fault controls, not evidence of measured hardware energy."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'szl_energy_attest' / 'inference_meter' / '_energy.py'
spec = importlib.util.spec_from_file_location('sampling_energy_under_test', SOURCE)
energy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(energy)


class PowerNVML:
    def __init__(self, readings):
        self.readings = iter([1000, *readings])
    def nvmlInit(self):
        pass
    def nvmlDeviceGetCount(self):
        return 1
    def nvmlDeviceGetHandleByIndex(self, index):
        return object()
    def nvmlDeviceGetTotalEnergyConsumption(self, handle):
        raise RuntimeError('synthetic counter unavailable')
    def nvmlDeviceGetPowerUsage(self, handle):
        value = next(self.readings)
        if isinstance(value, Exception):
            raise value
        return value


class CounterNVML(PowerNVML):
    def __init__(self, before, after):
        self.counter = iter([0, before, after])
    def nvmlDeviceGetTotalEnergyConsumption(self, handle):
        value = next(self.counter)
        if isinstance(value, Exception):
            raise value
        return value
    def nvmlDeviceGetPowerUsage(self, handle):
        raise RuntimeError('synthetic power unavailable')


class SamplingIntegrity(unittest.TestCase):
    def power_result(self, readings):
        with patch.object(energy, '_pynvml', PowerNVML(readings)):
            meter = energy.EnergyMeter()
            meter.start()
            for _ in readings[1:-1]:
                meter.sample()
            return meter.stop()
    def assert_unmeasured(self, result):
        self.assertEqual(result['mode'], energy.MODE_UNMEASURED)
        self.assertIsNone(result['joules'])
    def test_start_read_failure_cannot_be_bridged(self):
        self.assert_unmeasured(self.power_result([RuntimeError('start'), 1000, 1000]))
    def test_middle_read_failure_cannot_be_bridged(self):
        self.assert_unmeasured(self.power_result([1000, RuntimeError('middle'), 1000]))
    def test_stop_read_failure_cannot_be_bridged(self):
        self.assert_unmeasured(self.power_result([1000, 1000, RuntimeError('stop')]))
    def test_none_read_cannot_be_bridged(self):
        self.assert_unmeasured(self.power_result([1000, None, 1000]))
    def test_nonfinite_power_cannot_be_bridged(self):
        for value in [float('nan'), float('inf'), float('-inf')]:
            with self.subTest(value=value):
                self.assert_unmeasured(self.power_result([1000, value, 1000]))
    def test_no_successful_samples(self):
        result = self.power_result([RuntimeError('start'), RuntimeError('stop')])
        self.assert_unmeasured(result)
        self.assertEqual(result['n_power_samples'], 0)
    def test_successful_samples_are_not_counted_as_failures(self):
        result = self.power_result([1000, RuntimeError('middle'), 1000])
        self.assert_unmeasured(result)
        self.assertEqual(result['n_power_samples'], 2)
    def test_zero_power_is_valid(self):
        with patch.object(energy, '_pynvml', PowerNVML([0, 0])), patch.object(energy.time, 'perf_counter', side_effect=[0., 0., 1., 1.]):
            meter = energy.EnergyMeter(); meter.start(); result = meter.stop()
        self.assertEqual(result['mode'], energy.MODE_POWER_INTEGRAL)
        self.assertEqual(result['joules'], 0.)
    def test_valid_power_integral_preserved(self):
        with patch.object(energy, '_pynvml', PowerNVML([1000, 3000])), patch.object(energy.time, 'perf_counter', side_effect=[0., 0., 2., 2.]):
            meter = energy.EnergyMeter(); meter.start(); result = meter.stop()
        self.assertEqual(result['mode'], energy.MODE_POWER_INTEGRAL)
        self.assertEqual(result['joules'], 4.)
    def test_negative_power_still_rejected(self):
        self.assert_unmeasured(self.power_result([1000, -1, 1000]))
    def test_clean_interval_recovers(self):
        with patch.object(energy, '_pynvml', PowerNVML([1000, RuntimeError('fault'), 1000, 1000])):
            meter = energy.EnergyMeter(); meter.start(); self.assert_unmeasured(meter.stop())
            meter.start(); result = meter.stop()
        self.assertEqual(result['mode'], energy.MODE_POWER_INTEGRAL)
        self.assertEqual(result['n_power_samples'], 2)
    def test_counter_success_preserved(self):
        with patch.object(energy, '_pynvml', CounterNVML(1000, 2500)):
            meter = energy.EnergyMeter(); meter.start(); result = meter.stop()
        self.assertEqual(result['mode'], energy.MODE_ENERGY_COUNTER)
        self.assertEqual(result['joules'], 1.5)
    def test_zero_counter_delta_preserved(self):
        with patch.object(energy, '_pynvml', CounterNVML(1000, 1000)):
            meter = energy.EnergyMeter(); meter.start(); result = meter.stop()
        self.assertEqual(result['mode'], energy.MODE_ENERGY_COUNTER)
        self.assertEqual(result['joules'], 0.)
    def test_counter_reset_preserved(self):
        with patch.object(energy, '_pynvml', CounterNVML(1000, 500)):
            meter = energy.EnergyMeter(); meter.start(); self.assert_unmeasured(meter.stop())
    def test_no_nvml_remains_unmeasured(self):
        with patch.object(energy, '_pynvml', None):
            meter = energy.EnergyMeter(); meter.start(); self.assert_unmeasured(meter.stop())

if __name__ == '__main__':
    unittest.main(verbosity=2)
