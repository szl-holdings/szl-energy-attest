# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Carbon-intensity placeholder for per-inference receipts.

Honest contract: a receipt's ``carbon`` block is UNAVAILABLE unless a grid-API
key is provided via environment. There is NO default carbon model here — the
repo's grid-average keyless UK signal lives in the parent package
(``szl_energy_attest.fetch_grid_context``); this module adds the key-gated
providers so a paying operator can pin a real marginal-intensity feed.

Environment:

    SZL_GRID_PROVIDER      — "electricity_maps" | "watttime" (default: none)
    SZL_GRID_API_KEY       — the provider API key/token
    SZL_GRID_ZONE          — grid zone / balancing authority (e.g. "US-NY")

Without a key the block is honest UNAVAILABLE with reason recorded. A carbon
number is pass-through provenance; it NEVER becomes a joule.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

LABEL_REPORTED = "REPORTED"
LABEL_UNAVAILABLE = "UNAVAILABLE"

_TIMEOUT_S = 2.5


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unavailable_block(reason: str) -> Dict[str, Any]:
    return {
        "label": LABEL_UNAVAILABLE,
        "carbon_intensity_gco2_per_kwh": None,
        "carbon_intensity_kind": None,
        "provider": os.environ.get("SZL_GRID_PROVIDER") or None,
        "zone": os.environ.get("SZL_GRID_ZONE") or None,
        "fetched_at": _utcnow(),
        "reason": reason,
    }


def fetch_carbon_context(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Fetch a pass-through carbon-intensity signal, or honestly UNAVAILABLE.

    Key-gated by design: without ``SZL_GRID_API_KEY`` (and a provider name)
    every receipt carries UNAVAILABLE. Network/parse failure also degrades to
    UNAVAILABLE with the failure recorded — silent defaults are forbidden.
    """
    env = dict(os.environ if env is None else env)
    provider = (env.get("SZL_GRID_PROVIDER") or "").strip().lower()
    key = (env.get("SZL_GRID_API_KEY") or "").strip()
    zone = (env.get("SZL_GRID_ZONE") or "").strip()

    if not provider and not key:
        return unavailable_block("no grid-API key configured (SZL_GRID_API_KEY unset)")
    if provider and not key:
        return unavailable_block("provider %r set but SZL_GRID_API_KEY missing" % provider)
    if key and not provider:
        return unavailable_block("SZL_GRID_API_KEY set but SZL_GRID_PROVIDER missing")

    if provider == "electricity_maps":
        if not zone:
            return unavailable_block("electricity_maps requires SZL_GRID_ZONE")
        url = "https://api.electricitymaps.com/v3/carbon-intensity/latest?zone=%s" % zone
        headers = {"auth-token": key}
        kind = "grid_average"
    elif provider == "watttime":
        if not zone:
            return unavailable_block("watttime requires SZL_GRID_ZONE (balancing authority)")
        url = "https://api.watttime.org/v3/signal-index?ba=%s" % zone
        headers = {"Authorization": "Bearer %s" % key}
        kind = "marginal"
    else:
        return unavailable_block("unknown provider %r (supported: electricity_maps, watttime)" % provider)

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - degrade honestly, never raise
        return unavailable_block("grid signal fetch failed: %s: %s" % (type(exc).__name__, exc))

    value: Optional[float] = None
    if provider == "electricity_maps":
        raw = data.get("carbonIntensity")
        value = float(raw) if isinstance(raw, (int, float)) else None
    elif provider == "watttime":
        raw = data.get("data", {}).get("moer")
        value = float(raw) if isinstance(raw, (int, float)) else None

    if value is None:
        return unavailable_block("provider response carried no usable intensity value")

    return {
        "label": LABEL_REPORTED,
        "carbon_intensity_gco2_per_kwh": value,
        "carbon_intensity_kind": kind,
        "provider": provider,
        "zone": zone,
        "source": url.split("?")[0],
        "fetched_at": _utcnow(),
        "reason": None,
        "note": "REPORTED pass-through from provider; NOT a MEASURED joule and "
        "never converts UNAVAILABLE energy into MEASURED.",
    }
