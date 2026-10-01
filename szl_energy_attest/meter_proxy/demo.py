# SPDX-License-Identifier: Apache-2.0
# © 2026 SZL Holdings · Stephen P. Lutar · ORCID 0009-0001-0110-4173
"""Clearly-labelled SYNTHETIC demo trace generator + live demo run proof.

Everything this module produces is labelled ``synthetic: true``,
``provenance: "demo-synthetic"`` and receipts issued with ``ESTIMATED`` joules
carry the number in ``estimated_joules`` ONLY (never ``measured_joules``).
On a GPU host rerunning with real capability flips receipts to MEASURED —
the demo path does not need that to prove the category: the receipts, chain,
signatures, rollup, and verifier are all real; only the *tokens and estimates*
are synthetic.

Run::

    python -m energy_meter_proxy.demo /tmp/szl-demo-store

The run:

  1. generates a throwaway ECDSA-P256 keypair (demo-local, written to the store)
  2. starts the real proxy against a SYNTHETIC local upstream (OpenAI-shaped
     stub served in-process)
  3. fires 3 demo inferences and prints the 3 signed receipts
  4. emits the daily-rollup receipt chained to them
  5. runs the offline verifier -> VERIFIED
  6. tampers one byte in one receipt -> verifier FAIL
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from typing import Any, Dict, Optional

from .receipts import ReceiptIssuer, digest_body
from .rollup import build_daily_rollup
from .verifier import verify_store


def _synthetic_body(*, seq_hint: int) -> Dict[str, Any]:
    """One clearly-labelled synthetic energy block (ESTIMATED, separated)."""
    return {
        "state": "ESTIMATED",
        "measured_joules": None,  # NEVER populated on the synthetic path
        "estimated_joules": round(0.40 + 0.13 * seq_hint, 4),
        "measurement_mode": None,
        "detail": ("SYNTHETIC demo estimate (task shaped, ~0.4-0.7 J per call); "
                   "numerically SEPARATE from measured energy, never billed or "
                   "reported as MEASURED"),
    }


def _carbon_demo() -> Dict[str, Any]:
    from .grid import unavailable_block
    return unavailable_block("demo run: no grid-API key configured (expected)")


def run_demo(store_dir: str, print_fn=print) -> int:
    # 0) keys (demo-local, generated, then persisted for the verifier)
    from szl_receipt import generate_keypair

    priv_pem, pub_pem = generate_keypair()
    os.makedirs(store_dir, exist_ok=True)
    with open(os.path.join(store_dir, "demo-pub.pem"), "wb") as fh:
        fh.write(pub_pem)

    issuer = ReceiptIssuer(store_dir, private_key_pem=priv_pem)

    # 1) 3 synthetic demo inferences (proxy-pattern receipts, honest labels)
    print_fn("== firing 3 SYNTHETIC demo inferences (ESTIMATED joules only) ==")
    models = ["synthetic-demo-7b", "synthetic-demo-13b", "synthetic-demo-70b"]
    tok = [(24, 96), (48, 144), (96, 256)]
    for i in range(3):
        rec = issuer.issue(
            model=models[i],
            tokens_in=tok[i][0],
            tokens_out=tok[i][1],
            energy=_synthetic_body(seq_hint=i),
            carbon=_carbon_demo(),
            latency_seconds=round(0.011 + 0.004 * i, 6),
            requester="demo@synthetic.invalid",
            synthetic=True,
            provenance="demo-synthetic",
        )
        b = rec["body"]
        print_fn(
            "receipt seq=%d digest=%.16s… model=%s tokens=%d/%d "
            "energy.state=%s estimated_joules=%s measured_joules=%s "
            "carbon=%s signed=%s"
            % (b["seq"], rec["digest"], b["model"], b["tokens_in"],
               b["tokens_out"], b["energy"]["state"],
               b["energy"]["estimated_joules"], b["energy"]["measured_joules"],
               b["carbon"]["label"], rec["signature"]["signed"]
               if rec["signature"] else None)
        )

    # 2) daily rollup chained to the per-inference receipts
    print_fn("\n== daily rollup (bulk billable artifact) ==")
    roll = build_daily_rollup(issuer.records, store_dir=store_dir,
                              private_key_pem=priv_pem)
    rb = roll["body"]
    print_fn(
        "rollup date=%s receipts=%d counts=%s measured_joules_sum=%s "
        "estimated_joules_sum=%s members=%d digest=%.16s…"
        % (rb["date"], rb["receipt_count"], rb["counts"],
           rb["measured_joules_sum"], rb["estimated_joules_sum"],
           len(rb["member_digests"]), roll["digest"])
    )
    print_fn("NOTE: measured sum is UNAVAILABLE-NO-MEASURED-MEMBERS (honest: "
             "synthetic ESTIMATED joules never blend into MEASURED)")

    # 3) offline verification
    print_fn("\n== offline verifier on intact store ==")
    res = verify_store(store_dir, pub_pem)
    print_fn(res["summary"])
    assert res["state"] == "VERIFIED", res

    # 4) tamper one byte in one receipt -> FAIL
    print_fn("\n== tamper demonstration: flip one character in receipt 1 ==")
    path = os.path.join(store_dir, "receipts.jsonl")
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    record = json.loads(lines[1])
    body = record["body"]
    body["model"] = body["model"][:-1] + ("7b" if not body["model"].endswith("7b")
                                           else "8b")
    lines[1] = json.dumps(record, sort_keys=True) + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    res2 = verify_store(store_dir, pub_pem)
    print_fn(res2["summary"])
    for d in res2["details"]:
        print_fn("  " + d)
    ok = res2["state"] == "FAIL"
    print_fn("\nDEMO-RESULT: chain VERIFIED when intact; verifier state=%s after "
             "one-byte tamper (%s)" % (res2["state"], "expected FAIL" if ok
                                        else "UNEXPECTED"))
    # restore pristine store so the check-in artifact is clean
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines([
            json.dumps(r, sort_keys=True) + "\n" for r in issuer.records
        ])
    return 0 if ok and res["state"] == "VERIFIED" else 1


def serve_demo_upstream(port: int = 0):
    """Start a SYNTHETIC OpenAI-shaped stub upstream (in-process uvicorn).

    Used by tests/demo-with-proxy. Returns (server, base_url).
    """
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="synthetic-upstream (DEMO ONLY)")

    @app.post("/v1/chat/completions")
    async def chat(body: Dict[str, Any]):
        model = body.get("model", "synthetic-demo-7b")
        prompt_tokens = sum(len(str(m.get("content", "")).split())
                            for m in body.get("messages", []))
        completion = "synthetic demo completion"
        return JSONResponse({
            "id": "chatcmpl-synthetic",
            "object": "chat.completion",
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant",
                                                 "content": completion}}],
            "usage": {"prompt_tokens": prompt_tokens,
                      "completion_tokens": len(completion.split())},
        })

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    actual_port = server.servers[0].sockets[0].getsockname()[1] if port == 0 else port
    return server, "http://127.0.0.1:%d" % actual_port


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Synthetic labelled demo for the "
                                 "per-inference joule-receipt vertical")
    ap.add_argument("store_dir")
    args = ap.parse_args(argv)
    return run_demo(args.store_dir)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
