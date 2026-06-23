# SPDX-License-Identifier: Apache-2.0
# © 2026 Lutar, Stephen P. — SZL Holdings · ORCID 0009-0001-0110-4173
"""szl-energy-attest CLI — emit a clearly-labeled SAMPLE energy-attestation
receipt chain and verify its hash chain, fully offline.

Usage:
    python -m szl_energy_attest.cli emit     # mint a 2-receipt SAMPLE chain -> stdout JSON
    python -m szl_energy_attest.cli verify   # mint + re-walk the chain, print PASS/FAIL
    python -m szl_energy_attest.cli emit --out receipts.json

This NEVER fabricates a joule. On a CPU-only box the energy fields are null and
labeled UNAVAILABLE; on a GPU box with a live NVML/exporter delta the same code
path would carry a MEASURED joule. Either way the chain re-hashes and verifies.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import (build_receipt, verify_chain, verify_receipt_offline,
               measure_joules, nvml_available, sign_chain, verify_signature,
               canon_source, GENESIS_PREV, LABEL_MEASURED, __version__)


def _sample_chain():
    """Build a small, CLEARLY-LABELLED sample chain off the real measure path.

    We call measure_joules() honestly: on this box (no GPU) it returns
    (None, UNAVAILABLE), so the receipts carry null joules. If you run this on a
    measuring node and hand a real reading into measure_joules(reading=..,
    label='MEASURED'), the same receipts would carry MEASURED joules.
    """
    j0, lab0 = measure_joules()          # honest: None/UNAVAILABLE on CPU-only
    r0 = build_receipt(
        tokens=128, node="example-node-a", measured_joules=j0, label=lab0,
        price_per_mwh=None, gco2=None, decision="no_choice",
        prev=GENESIS_PREV,
        note="SAMPLE receipt — single node, no comparable alternative this tick")

    j1, lab1 = measure_joules()
    r1 = build_receipt(
        tokens=256, node="example-node-b", measured_joules=j1, label=lab1,
        price_per_mwh=None, gco2=None, decision="no_choice",
        prev=r0["digest"],
        note="SAMPLE receipt — chained to previous; energy honest-null on CPU")
    return [r0, r1]


def cmd_emit(args) -> int:
    chain = _sample_chain()
    out = {
        "tool": "szl_energy_attest",
        "version": __version__,
        "canon_source": canon_source(),
        "nvml_available": nvml_available(),
        "disclaimer": ("SAMPLE / illustrative receipts. Energy is MEASURED only "
                       "from a real NVML delta; null + UNAVAILABLE means no GPU on "
                       "this box. No joule, price, or carbon figure is fabricated."),
        "receipts": chain,
    }
    text = json.dumps(out, indent=2)
    if getattr(args, "out", None):
        with open(args.out, "w") as f:
            f.write(text + "\n")
        print(f"wrote {len(chain)} receipt(s) to {args.out}")
    else:
        print(text)
    return 0


def cmd_verify(args) -> int:
    chain = _sample_chain()
    ok, length, brk = verify_chain(chain)
    print(f"canon_source : {canon_source()}")
    print(f"nvml_available: {nvml_available()}")
    print(f"chain length : {length}")
    for i, r in enumerate(chain):
        print(f"  [{i}] node={r['node']:<16} tokens={r['tokens']:<5} "
              f"joules={r['measured_joules']} label={r['label']} "
              f"digest={r['digest'][:23]}…")
    if ok:
        print("VERIFY PASS — every receipt re-hashes and the chain links cleanly.")
        # Negative control: tamper one field and prove the chain breaks.
        tampered = json.loads(json.dumps(chain))
        tampered[0]["tokens"] = 999999
        bad_ok, _, bad_brk = verify_chain(tampered)
        print(f"tamper check : altering tokens -> verify ok={bad_ok} "
              f"(break at index {bad_brk}) — tamper-evident as designed.")
        # Third-party, zero-dependency offline verifier (the attestable point).
        off = verify_receipt_offline(chain)
        print(f"offline 3rd-party check: ok={off['ok']} honesty_ok={off['honesty_ok']} "
              f"— verifiable with stdlib alone, no szl/torch imports.")
        # Optional DSSE/cosign signature hook: honest UNSIGNED with no key.
        env = sign_chain(chain)
        sig = verify_signature(chain, env)
        print(f"signature    : label={env['signature_label']} "
              f"(signed={sig['signed']}, valid={sig['valid']}) — {env['note']}")
        return 0
    print(f"VERIFY FAIL — first break at index {brk}.")
    return 1


def cmd_offline_verify(args) -> int:
    """Verify an external receipt-chain JSON file using ONLY the standalone,
    zero-dependency verifier (no szl core needed beyond this one function)."""
    with open(args.path) as f:
        data = json.load(f)
    res = verify_receipt_offline(data)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="szl-energy-attest",
                                description="Attestable energy receipts for governed compute.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("emit", help="emit a sample receipt chain as JSON")
    pe.add_argument("--out", help="write JSON to this file instead of stdout")
    pe.set_defaults(func=cmd_emit)
    pv = sub.add_parser("verify", help="emit and verify a sample receipt chain")
    pv.set_defaults(func=cmd_verify)
    po = sub.add_parser("offline-verify",
                        help="verify an external chain JSON with the standalone verifier")
    po.add_argument("path", help="path to a receipts JSON file (chain, envelope, or single)")
    po.set_defaults(func=cmd_offline_verify)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
