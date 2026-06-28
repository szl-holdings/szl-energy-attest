#!/usr/bin/env python3
"""
SZL meter2 — sovereign NVML energy exporter (stdlib + pynvml only).

Serves Prometheus-style metrics on :9471 so the a11oy mesh can attest MEASURED
joules per governed turn. Honest by construction: if NVML is unavailable, it
reports the metric as UNAVAILABLE rather than fabricating joules.

Run on the LAPTOP (OMEN), PowerShell:
    pip install pynvml          # one time
    python szl_meter2_exporter.py
Then the cloudflared ingress hostname meter2.a-11-oy.com -> http://localhost:9471
will serve /metrics and /health.

Doctrine: data labeled LIVE/MEASURED/UNAVAILABLE; never fabricate energy.
Signed-off-by: Stephen Lutar <stephenlutar2@gmail.com>
"""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9471

try:
    import pynvml  # type: ignore
    pynvml.nvmlInit()
    _NVML = True
    _DEVS = pynvml.nvmlDeviceGetCount()
except Exception as _e:  # noqa: BLE001
    _NVML = False
    _DEVS = 0
    _NVML_ERR = repr(_e)


def _sample():
    """Return per-GPU power (W) + cumulative energy (J) when NVML is present."""
    out = {"nvml": _NVML, "ts": time.time(), "gpus": []}
    if not _NVML:
        out["label"] = "UNAVAILABLE"
        out["note"] = "pynvml not available; joules NOT fabricated"
        return out
    out["label"] = "MEASURED"
    for i in range(_DEVS):
        h = pynvml.nvmlDeviceGetHandleByIndex(i)
        try:
            name = pynvml.nvmlDeviceGetName(h)
            name = name.decode() if isinstance(name, bytes) else name
        except Exception:  # noqa: BLE001
            name = f"gpu{i}"
        power_w = None
        energy_j = None
        try:
            power_w = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0  # mW -> W
        except Exception:  # noqa: BLE001
            pass
        try:
            # Total energy consumption since last driver reload (mJ -> J)
            energy_j = pynvml.nvmlDeviceGetTotalEnergyConsumption(h) / 1000.0
        except Exception:  # noqa: BLE001
            pass
        out["gpus"].append(
            {"index": i, "name": name, "power_w": power_w, "energy_j": energy_j}
        )
    return out


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):  # quiet
        return

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, json.dumps({"ok": True, "nvml": _NVML, "gpus": _DEVS}),
                       "application/json")
            return
        if self.path.startswith("/json"):
            self._send(200, json.dumps(_sample()), "application/json")
            return
        # default: Prometheus-style /metrics
        s = _sample()
        lines = [
            "# HELP szl_meter_nvml 1 if NVML present (MEASURED), 0 if UNAVAILABLE",
            "# TYPE szl_meter_nvml gauge",
            f"szl_meter_nvml {1 if s['nvml'] else 0}",
        ]
        for g in s.get("gpus", []):
            lbl = f'gpu="{g["index"]}",name="{g["name"]}"'
            if g.get("power_w") is not None:
                lines += ["# TYPE szl_gpu_power_watts gauge",
                          f'szl_gpu_power_watts{{{lbl}}} {g["power_w"]}']
            if g.get("energy_j") is not None:
                lines += ["# TYPE szl_gpu_energy_joules counter",
                          f'szl_gpu_energy_joules{{{lbl}}} {g["energy_j"]}']
        self._send(200, "\n".join(lines) + "\n")


if __name__ == "__main__":
    mode = "MEASURED (NVML live)" if _NVML else "UNAVAILABLE (no NVML — honest, not fabricated)"
    print(f"[szl-meter2] serving on :{PORT}  mode={mode}  gpus={_DEVS}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
