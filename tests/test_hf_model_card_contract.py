"""Source-controlled card for the Hugging Face model repo SZLHOLDINGS/szl-energy-attest.

hf-models/szl-energy-attest/README.md was imported verbatim from the Hub. The
Hub repository is a source pointer (MIRROR_EMPTY); these checks keep every
claim the card makes about this repository tied to a file that states it.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "hf-models" / "szl-energy-attest" / "README.md"


def _card():
    text = CARD.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, "card must start with YAML front matter"
    return match.group(1), text[match.end():]


def test_license_matches_the_repository_license():
    front_matter, body = _card()
    assert re.search(r"(?m)^license: apache-2\.0$", front_matter)
    assert "Apache License" in (ROOT / "LICENSE").read_text(encoding="utf-8")[:200]
    assert body.rstrip().endswith("Apache-2.0.")


def test_mirror_empty_claim_matches_hub_mirror_status():
    _, body = _card()
    status = json.loads((ROOT / "HUB_MIRROR_STATUS.json").read_text(encoding="utf-8"))
    assert status["artifact"] == "SZLHOLDINGS/szl-energy-attest"
    assert status["hub_state"] == "MIRROR_EMPTY"
    assert "`MIRROR_EMPTY` on " + status["observed_at"][:10] in body
    assert status["canonical_source"] in body


def test_listed_source_paths_exist():
    _, body = _card()
    for path in ("pyproject.toml", "szl_energy_attest", "energy_core", "examples",
                 "tests", "MIGRATION_PROVENANCE.json", "SPEC.md"):
        assert f"`{path}" in body, path
        assert (ROOT / path).exists(), path


def test_card_makes_no_measured_or_benchmark_claim():
    _, body = _card()
    assert "MEASURED" not in body
    assert not re.search(r"\b\d+(\.\d+)?\s*(tokens/J|tok/J|J/token|W\b)", body)
