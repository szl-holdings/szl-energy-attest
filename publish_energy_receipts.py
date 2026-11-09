#!/usr/bin/env python3
"""SZL energy receipt publisher — canonical writer with readback (P0 lane P1-ENERGY).

Contract (per SZL_P0_FRONTIER_REMEDIATION plan):
- append immutable rows; never overwrite history
- each row: run_id, source_revision, artifact_sha256, timestamp_utc, runtime/tool
  versions, measured NVML joules OR explicit "UNAVAILABLE", provenance, operator
- publish to SZLHOLDINGS/energy-attested-runs (new Hub revision)
- fetch the exact Hub revision back and require byte/hash equality
- only after readback passes may downstream labels change from SIMULATED

Usage:
  python publish_energy_receipts.py publish --ledger /path/to/szl_energy_ledger.jsonl
  python publish_energy_receipts.py verify --revision <hub_sha>
Exit codes: 0 = readback passed; 1 = readback failed; 2 = usage/ledger error.
"""
import argparse, hashlib, json, os, sys, time
from huggingface_hub import HfApi

DATASET = "SZLHOLDINGS/energy-attested-runs"
SCHEMA = "szl.energy-attestation/v1"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_ledger(path):
    """Parse the daemon's hash-chained JSONL ledger; verify the chain before publishing."""
    rows, prev = [], "0" * 64
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            # chain check: each record carries prev hash; recompute record hash
            body = {k: rec[k] for k in rec if k != "record_sha256"}
            computed = hashlib.sha256(
                (prev + "|" + json.dumps(body, sort_keys=True)).encode()
            ).hexdigest()
            if rec.get("prev_sha256") != prev or (
                "record_sha256" in rec and rec["record_sha256"] != computed
            ):
                print(f"CHAIN_BREAK at row {len(rows)}: refusing to publish", file=sys.stderr)
                sys.exit(2)
            prev = computed if "record_sha256" in rec else rec.get("record_sha256", prev)
            rows.append(rec)
    return rows


def publish(ledger_path, token=None):
    api = HfApi(token=token or os.environ.get("HF_TOKEN"))
    rows = load_ledger(ledger_path)
    if not rows:
        print("empty ledger", file=sys.stderr)
        sys.exit(2)

    # build publishable rows (immutable, explicit-unavailable joules)
    pub_rows = []
    for r in rows:
        pub_rows.append({
            "run_id": r.get("run_id"),
            "source_revision": r.get("source_revision"),
            "artifact_sha256": r.get("artifact_sha256"),
            "timestamp_utc": r.get("timestamp_utc"),
            "runtime": r.get("runtime", {}),
            "measured_joules": r.get("measured_joules", "UNAVAILABLE"),
            "nvidia_smi_available": bool(r.get("nvidia_smi_available", False)),
            "provenance": r.get("provenance", "szl_energy_daemon"),
            "operator": r.get("operator", "stephenlutar2"),
            "schema": SCHEMA,
        })

    blob = json.dumps(pub_rows, indent=2, sort_keys=True)
    local = "/tmp/energy_receipts_append.json"
    open(local, "w").write(blob)
    local_sha = hashlib.sha256(blob.encode()).hexdigest()

    # append: upload as a new dated file, never overwrite existing history
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path_in_repo = f"receipts/energy-receipts-{stamp}.json"
    api.upload_file(path_or_fileobj=local, path_in_repo=path_in_repo,
                    repo_id=DATASET, repo_type="dataset")
    info = api.dataset_info(DATASET)
    rev = info.sha
    print(json.dumps({"published_revision": rev, "path": path_in_repo,
                      "local_sha256": local_sha, "rows": len(pub_rows)}, indent=2))
    return rev, path_in_repo, local_sha


def verify(rev, path, expected_sha):
    api = HfApi(token=os.environ.get("HF_TOKEN"))
    got = api.hf_hub_download(DATASET, path, revision=rev, repo_type="dataset")
    got_sha = sha256_file(got)
    ok = got_sha == expected_sha
    print(json.dumps({"revision": rev, "path": path, "expected": expected_sha,
                      "readback": got_sha, "READBACK_PASS": ok}, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("publish")
    p1.add_argument("--ledger", required=True)
    p2 = sub.add_parser("verify")
    p2.add_argument("--revision", required=True)
    p2.add_argument("--path", required=True)
    p2.add_argument("--sha256", required=True)
    a = ap.parse_args()
    if a.cmd == "publish":
        publish(a.ledger)
    else:
        verify(a.revision, a.path, a.sha256)
