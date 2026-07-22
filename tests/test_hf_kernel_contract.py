import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CARD_DIR = ROOT / "hf-kernels" / "governed-inference-meter"


def _contract():
    return json.loads((CARD_DIR / "contract.json").read_text(encoding="utf-8"))


def test_quickstart_requires_explicit_trust_and_immutable_revision():
    contract = _contract()
    card = (CARD_DIR / "README.md").read_text(encoding="utf-8")
    revision = contract["observed_revision"]

    assert re.fullmatch(r"[0-9a-f]{40}", revision)
    assert contract["required_trust_remote_code"] is True
    assert f'revision="{revision}"' in card
    assert "trust_remote_code=True" in card
    assert 'get_kernel("SZLHOLDINGS/governed-inference-meter")' not in card
    assert 'revision="main"' not in card


def test_contract_points_to_folded_canonical_package():
    contract = _contract()

    assert contract["canonical_source"] == "szl-holdings/szl-energy-attest"
    assert contract["compatibility_package"] == "szl_energy_attest.inference_meter"
