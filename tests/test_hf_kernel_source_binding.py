"""Structural checks for the OBSERVED source binding of the published
governed-inference-meter Hub kernel. Offline: no network access."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD_DIR = ROOT / "hf-kernels" / "governed-inference-meter"
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")


def _binding():
    return json.loads((CARD_DIR / "source-binding.observed.json").read_text(encoding="utf-8"))


def _contract():
    return json.loads((CARD_DIR / "contract.json").read_text(encoding="utf-8"))


def test_binding_is_labelled_observed_and_not_publisher_v1():
    b = _binding()
    assert b["label"] == "OBSERVED"
    assert b["schema"] == "szl.kernel-source-binding.observed/v0"
    assert b["schema"] != "szl.kernel-source-binding/v1"
    assert "sole Hub writer" in b["note"]


def test_binding_pins_the_contract_revision_and_repo():
    b, c = _binding(), _contract()
    assert b["repo_id"] == c["repo_id"]
    assert b["repo_type"] == c["repo_type"] == "kernel"
    assert b["hub_revision"] == c["observed_revision"]
    assert SHA1.fullmatch(b["hub_revision"])
    assert SHA1.fullmatch(b["hub_main_at_observation"])
    assert SHA1.fullmatch(b["source_commit"])
    assert b["canonical_successor"] == c["canonical_source"]
    assert b["canonical_successor_package"] == c["compatibility_package"]


def test_every_published_python_file_is_bound_to_a_source_file():
    b = _binding()
    py = [f for f in b["files"] if f["hub_path"].endswith(".py")]
    assert len(py) == 6
    for f in py:
        assert SHA256.fullmatch(f["hub_sha256"])
        assert SHA256.fullmatch(f["lf_normalized_sha256"])
        assert SHA256.fullmatch(f["source_sha256"])
        assert f["source_path"].startswith("build/torch-universal/governed_inference_meter/")
        assert f["matches_source_after_crlf_to_lf"] is True


def test_divergence_from_canonical_successor_is_disclosed_not_hidden():
    b = _binding()
    py = [f for f in b["files"] if f["hub_path"].endswith(".py")]
    any_diverged = any(not f["matches_canonical_package_after_crlf_to_lf"] for f in py)
    assert b["published_bytes_match_canonical_successor"] is (not any_diverged)
