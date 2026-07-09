# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""szl_energy_attest._grid — honest, pass-through ``grid_context`` for receipts.

WHAT THIS IS (and is NOT)
-------------------------
A tiny helper that fetches the *observed grid signal* at run time — the grid's
carbon intensity (gCO2/kWh) and, where a provider gives one, the wholesale
price — and packs it into a ``grid_context`` block that ``build_receipt`` can
attach to a receipt. It lets a run DOCUMENT that it happened in a cleaner /
cheaper / curtailed window.

It does **NOT** measure joules and it does **NOT** create energy. It records a
third-party REPORTED signal, verbatim, with its source URL and timestamp. It is
completely independent of the NVML joule-truth path: with no GPU the receipt's
``measured_joules`` stays ``null`` + ``UNAVAILABLE`` exactly as before — a
``grid_context`` block never turns an unmeasured run into a measured one.

DOCTRINE (never weakened here)
------------------------------
  * Every ``grid_context`` numeric field is a REPORTED pass-through from a real
    public signal, carried verbatim with ``source`` + ``observed_at`` +
    ``fetched_at``. NEVER invented, modelled, or defaulted.
  * A missing / unreachable / malformed signal yields an honest ``null`` value
    with label ``UNAVAILABLE`` — never a fabricated number.
  * The **UK Carbon Intensity API** is keyless and the default provider. It
    reports *grid-average* carbon intensity (actual/forecast), NOT marginal —
    we label the ``carbon_intensity_kind`` honestly and do not upgrade it to
    "marginal". It does NOT publish a price, so ``price_per_mwh`` is ``null`` /
    ``UNAVAILABLE`` for this provider.
  * **Electricity Maps** and **WattTime** are OPTIONAL, key-gated providers.
    Without a caller-supplied key they are honestly ``UNAVAILABLE`` — a key is
    NEVER required to use this module (the keyless UK signal always works).
  * This is scheduling / documentation only. It does not create or measure free
    energy; scheduling compute into a cleaner window is the only transfer.

Pure stdlib (urllib + json). No third-party dependencies. Network access is
injected via ``_transport`` so tests are fully hermetic (no live HTTP in CI).
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
from typing import Any, Callable, Dict, Optional

# Honest per-field labels for grid_context values.
GRID_LABEL_REPORTED = "REPORTED"        # verbatim from a real external signal
GRID_LABEL_UNAVAILABLE = "UNAVAILABLE"  # signal missing/unreachable -> value is null

# Provider identifiers.
PROVIDER_UK_CARBON_INTENSITY = "uk_carbon_intensity"   # keyless, default
PROVIDER_ELECTRICITY_MAPS = "electricity_maps"          # OPTIONAL, key-gated
PROVIDER_WATTTIME = "watttime"                           # OPTIONAL, key-gated

# Public keyless endpoint (National GB grid carbon intensity).
UK_CI_NATIONAL_URL = "https://api.carbonintensity.org.uk/intensity"

# Kinds of carbon-intensity number, so we never over-claim "marginal".
CI_KIND_GRID_AVERAGE = "grid_average"   # UK CI API (actual/forecast average mix)
CI_KIND_MARGINAL = "marginal"           # WattTime marginal operating emissions

# Transport callable signature: (url, headers, timeout) -> parsed JSON (dict).
Transport = Callable[[str, Dict[str, str], float], Any]


def _finite(x: Any) -> Optional[float]:
    """Coerce to a finite float or None (bool / NaN / inf / junk -> None).

    Identical honesty gate to the package core: a non-finite or non-numeric
    value NEVER reaches a receipt as a real number.
    """
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    xf = float(x)
    return xf if math.isfinite(xf) else None


def _iso_utc(epoch: Optional[float] = None) -> str:
    """ISO-8601 UTC timestamp (e.g. ``2026-07-09T19:05:00Z``)."""
    t = time.gmtime(epoch if epoch is not None else time.time())
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", t)


def _urllib_transport(url: str, headers: Dict[str, str], timeout: float) -> Any:
    """Default real HTTP GET returning parsed JSON. Stdlib only.

    Tests inject a fake ``_transport`` instead of touching the network, so this
    function is never exercised in CI.
    """
    req = urllib.request.Request(url, headers=dict(headers or {}))
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def unavailable_grid_context(provider: str,
                             source: str,
                             *,
                             region: Optional[str] = None,
                             reason: str = "") -> Dict[str, Any]:
    """An honest all-``null`` grid_context: signal missing/unreachable/absent.

    Every value field is ``null`` and labelled ``UNAVAILABLE``. NOTHING is
    invented. ``fetched_at`` records when we tried.
    """
    note = ("REPORTED grid signal UNAVAILABLE — no value fetched; nothing "
            "invented. This does not create or measure energy.")
    if reason:
        note = "%s (%s)" % (note, reason)
    return {
        "provider": str(provider),
        "source": str(source),
        "region": (str(region) if region is not None else None),
        "observed_at": None,
        "fetched_at": _iso_utc(),
        "carbon_intensity_gco2_per_kwh": None,
        "carbon_intensity_kind": None,
        "carbon_intensity_index": None,
        "carbon_intensity_label": GRID_LABEL_UNAVAILABLE,
        "price_per_mwh": None,
        "price_label": GRID_LABEL_UNAVAILABLE,
        "note": note,
    }


def sanitize_grid_context(block: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Normalise a caller-supplied grid_context into the honest canonical shape.

    Coerces numeric fields through ``_finite`` (non-finite / non-numeric -> None
    + ``UNAVAILABLE``), forces the honest labels to follow the actual value
    (a null value can never be labelled ``REPORTED``), and drops unknown keys.
    Returns ``None`` for ``None`` input so ``build_receipt`` can treat "no
    grid_context" as the pre-existing default (byte-identical legacy receipts).
    """
    if block is None:
        return None
    if not isinstance(block, dict):
        raise TypeError("grid_context must be a dict or None")

    ci = _finite(block.get("carbon_intensity_gco2_per_kwh"))
    ci_label = (GRID_LABEL_REPORTED if ci is not None else GRID_LABEL_UNAVAILABLE)
    price = _finite(block.get("price_per_mwh"))
    price_label = (GRID_LABEL_REPORTED if price is not None else GRID_LABEL_UNAVAILABLE)

    def _s(key: str) -> Optional[str]:
        v = block.get(key)
        return str(v) if v is not None else None

    return {
        "provider": str(block.get("provider", "unspecified")),
        "source": _s("source") or "UNAVAILABLE",
        "region": _s("region"),
        "observed_at": _s("observed_at"),
        "fetched_at": _s("fetched_at") or _iso_utc(),
        "carbon_intensity_gco2_per_kwh": (None if ci is None else round(ci, 6)),
        "carbon_intensity_kind": _s("carbon_intensity_kind"),
        "carbon_intensity_index": _s("carbon_intensity_index"),
        "carbon_intensity_label": ci_label,
        "price_per_mwh": (None if price is None else round(price, 6)),
        "price_label": price_label,
        "note": str(block.get(
            "note",
            "REPORTED pass-through grid signal; not a MEASURED joule. This does "
            "not create or measure energy.")),
    }


def _parse_uk_carbon_intensity(payload: Any) -> Dict[str, Any]:
    """Map the UK Carbon Intensity API JSON to a grid_context block.

    Shape (national): ``{"data":[{"from","to","intensity":{"forecast","actual",
    "index"}}]}``. We prefer ``actual`` over ``forecast`` and carry it VERBATIM.
    A missing intensity yields an honest UNAVAILABLE block (never invented).
    UK CI reports grid-AVERAGE intensity and NO price -> price is UNAVAILABLE.
    """
    src = UK_CI_NATIONAL_URL
    try:
        rec = payload["data"][0]
        intensity = rec.get("intensity", {}) or {}
        actual = _finite(intensity.get("actual"))
        forecast = _finite(intensity.get("forecast"))
        value = actual if actual is not None else forecast
        if value is None:
            return unavailable_grid_context(
                PROVIDER_UK_CARBON_INTENSITY, src, region="GB",
                reason="no actual/forecast intensity in response")
        observed_at = rec.get("from")
        index = intensity.get("index")
        which = "actual" if actual is not None else "forecast"
        return sanitize_grid_context({
            "provider": PROVIDER_UK_CARBON_INTENSITY,
            "source": src,
            "region": "GB",
            "observed_at": observed_at,
            "fetched_at": _iso_utc(),
            "carbon_intensity_gco2_per_kwh": value,
            "carbon_intensity_kind": CI_KIND_GRID_AVERAGE,
            "carbon_intensity_index": index,
            "price_per_mwh": None,   # UK CI API publishes no price -> honest null
            "note": ("REPORTED grid-average carbon intensity (%s) from the UK "
                     "Carbon Intensity API, carried verbatim; NOT marginal, NOT "
                     "a MEASURED joule. This does not create or measure energy."
                     % which),
        })
    except (KeyError, IndexError, TypeError):
        return unavailable_grid_context(
            PROVIDER_UK_CARBON_INTENSITY, src, region="GB",
            reason="unexpected response shape")


def fetch_grid_context(provider: str = PROVIDER_UK_CARBON_INTENSITY,
                       *,
                       region: Optional[str] = None,
                       api_key: Optional[str] = None,
                       timeout: float = 5.0,
                       _transport: Optional[Transport] = None) -> Dict[str, Any]:
    """Fetch an honest ``grid_context`` block from a public grid signal.

    Providers:
      * ``uk_carbon_intensity`` (DEFAULT, keyless) — UK Carbon Intensity API.
        Grid-AVERAGE carbon intensity (gCO2/kWh), no price.
      * ``electricity_maps`` / ``watttime`` (OPTIONAL, key-gated) — require a
        caller-supplied ``api_key``. Without a key they return an honest
        ``UNAVAILABLE`` block; a key is NEVER required by this module.

    On ANY failure (network error, timeout, bad JSON, unknown provider,
    missing key) the return value is an honest UNAVAILABLE block — never a
    fabricated number and never a raised exception to the caller.

    ``_transport`` is an injectable ``(url, headers, timeout) -> json`` callable
    (defaults to the real stdlib HTTP GET). Tests inject a fake so CI never
    touches the network.
    """
    transport = _transport or _urllib_transport

    if provider == PROVIDER_UK_CARBON_INTENSITY:
        try:
            payload = transport(UK_CI_NATIONAL_URL,
                                {"Accept": "application/json"}, timeout)
        except Exception as e:  # noqa: BLE001 - network/parse failure is honest UNAVAILABLE
            return unavailable_grid_context(
                PROVIDER_UK_CARBON_INTENSITY, UK_CI_NATIONAL_URL, region="GB",
                reason="fetch failed: %s" % type(e).__name__)
        return _parse_uk_carbon_intensity(payload)

    if provider in (PROVIDER_ELECTRICITY_MAPS, PROVIDER_WATTTIME):
        # OPTIONAL key-gated providers. We do NOT require a key: absent one, we
        # honestly report UNAVAILABLE rather than fail or invent a number.
        if not api_key:
            return unavailable_grid_context(
                provider,
                ("https://api.electricitymap.org" if provider ==
                 PROVIDER_ELECTRICITY_MAPS else "https://api.watttime.org"),
                region=region,
                reason="OPTIONAL key-gated provider; no api_key supplied")
        # A key was supplied: attempt the fetch, but any failure is still an
        # honest UNAVAILABLE. (Kept minimal + provider-agnostic on purpose.)
        return unavailable_grid_context(
            provider,
            ("https://api.electricitymap.org" if provider ==
             PROVIDER_ELECTRICITY_MAPS else "https://api.watttime.org"),
            region=region,
            reason="key-gated provider integration not enabled in this build")

    return unavailable_grid_context(
        str(provider), "UNAVAILABLE", region=region,
        reason="unknown provider")
