"""Regression checks for the governed-inference-meter compatibility fold."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from szl_energy_attest import inference_meter as meter


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "MIGRATION_PROVENANCE.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_migration_manifest_matches_successor_bytes() -> None:
    evidence = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert evidence["schema"] == "szl.archive-migration-provenance/v1"
    for mapping in evidence["mappings"]:
        destination = ROOT / mapping["destination"]
        assert destination.is_file(), mapping["destination"]
        assert _sha256(destination) == mapping["destination_sha256"]
        if mapping["transform"] == "exact-copy":
            assert mapping["source_sha256"] == mapping["destination_sha256"]


def test_legacy_attestation_and_spine_surface_is_exported() -> None:
    expected = {
        "attest",
        "compliance_evidence",
        "verify_statement",
        "emit_szl_receipt",
        "from_meter_receipt",
        "meter_szl_receipt",
        "canonical_receipt_body",
        "verify_szl_receipt",
        "verify_szl_statement",
    }
    assert expected.issubset(set(meter.__all__))
    assert all(callable(getattr(meter, name)) for name in expected)


def test_legacy_receipt_verifier_fails_closed_on_missing_field_and_bad_seq() -> None:
    chain = meter.ReceiptChain()
    chain.emit(
        model="migration-regression",
        tokens_in=1,
        tokens_out=1,
        energy={"mode": "unmeasured", "joules": None, "wall_seconds": 0.0},
        policy_decision="allow",
        policy_reason="test",
    )
    assert chain.verify() == (True, 1, -1)

    original = dict(chain._records[0])
    del chain._records[0]["model"]
    assert chain.verify() == (False, 1, 0)

    chain._records[0] = original
    chain._records[0]["seq"] = 7
    assert chain.verify() == (False, 1, 0)
