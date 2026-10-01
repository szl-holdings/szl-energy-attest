# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""FastAPI OpenAI-compatible proxy: one signed joule receipt per inference.

Wrap any upstream OpenAI-compatible endpoint:

    SZL_UPSTREAM_BASE=http://localhost:9000  # upstream OpenAI-compatible base
    SZL_RECEIPT_DIR=/var/szl/receipts        # durable receipt store
    SZL_SIGNING_KEY_PATH=/run/secrets/key.pem  # OPTIONAL ECDSA-P256 PEM
    uvicorn energy_meter_proxy.proxy:create_app --factory

Endpoints:

    POST /v1/chat/completions   — forwarded upstream; the caller receives the
                                  upstream response PLUS header
                                  ``x-szl-receipt-id`` and the receipt is in
                                  the durable store.
    GET  /receipts              — list receipts (seq, digest, states)
    GET  /receipts/{seq}        — one full receipt (body + digest + DSSE)
    POST /rollup                — emit today's daily-rollup receipt
    GET  /capability            — honest capability report (NVML state)

Energy measurement is done proxy-side around the upstream call (EnergyMeter
when NVML is live). Token counts are read from the upstream ``usage`` block;
absent usage => honest UNAVAILABLE token label, never invented counts.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .grid import fetch_carbon_context
from .meter import EnergyState, measure_inference_energy
from .receipts import ReceiptIssuer
from .rollup import build_daily_rollup

try:
    import httpx
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse

    _HAVE_WEB = True
except Exception:  # noqa: BLE001
    _HAVE_WEB = False


def _load_signing_key() -> Optional[bytes]:
    path = os.environ.get("SZL_SIGNING_KEY_PATH", "").strip()
    if not path:
        return None
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def create_app(
    upstream_base: Optional[str] = None,
    store_dir: Optional[str] = None,
    signing_key_pem: Optional[bytes] = None,
) -> "FastAPI":
    if not _HAVE_WEB:
        raise RuntimeError(
            "FastAPI/httpx are required for the proxy "
            "(pip install 'szl-energy-attest[proxy]')"
        )
    upstream = (upstream_base
                or os.environ.get("SZL_UPSTREAM_BASE", "")).rstrip("/")
    store = store_dir or os.environ.get("SZL_RECEIPT_DIR", "./szl-receipts")
    key = signing_key_pem if signing_key_pem is not None else _load_signing_key()

    energy_state = EnergyState()
    issuer = ReceiptIssuer(store, private_key_pem=key)
    client = httpx.Client(timeout=120.0)

    app = FastAPI(title="szl-energy-attest proxy",
                  version="1.0.0",
                  description="Per-inference signed joule receipts")

    @app.get("/capability")
    def capability() -> Dict[str, Any]:
        return {
            "energy_capability": energy_state.capability,
            "signing": {
                "key_configured": key is not None,
                "note": "UNSIGNED-honest fallback when no key",
            },
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        if not upstream:
            raise HTTPException(status_code=503,
                                detail="SZL_UPSTREAM_BASE not configured; "
                                       "refusing to fabricate an inference")
        payload = await request.json()
        requester = (request.headers.get("authorization") or "")[:64] or None

        def _call() -> Dict[str, Any]:
            resp = client.post(upstream + "/v1/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()

        response_data, em = measure_inference_energy(energy_state, _call)
        # EnergyMeasurement always carries a wall-clock value; guard anyway so
        # a hypothetical None degrades to 0.0 rather than crashing issuance.
        latency = float(em.wall_seconds) if em.wall_seconds is not None else 0.0
        usage = response_data.get("usage") or {}
        ti = usage.get("prompt_tokens")
        to = usage.get("completion_tokens")
        ti = int(ti) if isinstance(ti, (int, float)) else None
        to = int(to) if isinstance(to, (int, float)) else None

        carbon = fetch_carbon_context()
        record = issuer.issue(
            model=response_data.get("model") or payload.get("model") or "unknown",
            tokens_in=ti,
            tokens_out=to,
            energy=em.as_receipt_energy(),
            carbon=carbon,
            latency_seconds=latency,
            requester=requester,
        )
        out = JSONResponse(content=response_data)
        out.headers["x-szl-receipt-id"] = record["body"]["receipt_id"]
        out.headers["x-szl-receipt-digest"] = record["digest"]
        out.headers["x-szl-energy-state"] = record["body"]["energy"]["state"]
        return out

    @app.get("/receipts")
    def list_receipts() -> Dict[str, Any]:
        return {
            "count": len(issuer.records),
            "receipts": [
                {
                    "seq": r["body"]["seq"],
                    "digest": r["digest"],
                    "energy_state": r["body"]["energy"]["state"],
                    "measured_joules": r["body"]["energy"]["measured_joules"],
                    "synthetic": r["body"]["synthetic"],
                    "signature_present": r["signature_present"],
                }
                for r in issuer.records
            ],
        }

    @app.get("/receipts/{seq}")
    def get_receipt(seq: int) -> Dict[str, Any]:
        recs = issuer.records
        if seq < 0 or seq >= len(recs):
            raise HTTPException(status_code=404, detail="no receipt at seq %d" % seq)
        return recs[seq]

    @app.post("/rollup")
    def rollup() -> Dict[str, Any]:
        return build_daily_rollup(issuer.records, store_dir=store,
                                  private_key_pem=key)

    return app


def main() -> None:  # pragma: no cover - convenience entry
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1",
                port=int(os.environ.get("SZL_PROXY_PORT", "8377")))
