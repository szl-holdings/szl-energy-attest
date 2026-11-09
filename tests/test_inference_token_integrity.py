# SPDX-License-Identifier: Apache-2.0
"""Caller-supplied token evidence must never be silently coerced."""

import pytest

from szl_energy_attest import inference_meter as meter
from szl_energy_attest.inference_meter import _receipt


INVALID_COUNTS = [True, False, -1, 1.5, 2.0, "2", None, [], float("nan"), float("inf")]


@pytest.fixture(autouse=True)
def offline_meter(monkeypatch):
    """No GPU, optional synchronizer, or signing service is used by these tests."""
    class Unmeasured:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            return {"mode": "unmeasured", "joules": None, "wall_seconds": 0.0}

    monkeypatch.setattr(meter, "EnergyMeter", Unmeasured)
    monkeypatch.setattr(meter, "_maybe_cuda_sync", lambda: None)
    monkeypatch.setattr(_receipt, "_maybe_sign", lambda *args: None)


def emit(chain, **counts):
    return chain.emit(
        model="synthetic", energy={"mode": "unmeasured", "joules": None},
        policy_decision="allow", policy_reason="test", **counts,
    )


@pytest.mark.parametrize("field", ["tokens_in", "tokens_out"])
@pytest.mark.parametrize("value", INVALID_COUNTS)
def test_invalid_input_never_reaches_policy_or_execution(field, value):
    chain = meter.ReceiptChain()
    seen = []
    counts = {"tokens_in": 1, "tokens_out": 2, field: value}
    with pytest.raises(ValueError, match=field):
        meter.meter(
            lambda: seen.append("executed"), chain=chain,
            policy=lambda ctx: seen.append("policy") or True, **counts,
        )
    assert seen == []
    assert chain.count() == 0


@pytest.mark.parametrize("field", ["tokens_in", "tokens_out"])
@pytest.mark.parametrize("value", INVALID_COUNTS)
def test_invalid_context_input_never_enters_block_or_policy(field, value):
    chain = meter.ReceiptChain()
    seen = []
    counts = {"tokens_in": 1, "tokens_out": 2, field: value}
    with pytest.raises(ValueError, match=field):
        with meter.metered(
            chain=chain, policy=lambda ctx: seen.append("policy") or True, **counts,
        ):
            seen.append("entered")
    assert seen == []
    assert chain.count() == 0


@pytest.mark.parametrize("field", ["tokens_in", "tokens_out"])
@pytest.mark.parametrize("value", INVALID_COUNTS)
def test_mutated_context_cannot_emit_coerced_count(field, value):
    chain = meter.ReceiptChain()
    with pytest.raises(ValueError, match=field):
        with meter.metered(chain=chain, tokens_in=1) as state:
            state[field] = value
    assert state["receipt"] is None
    assert chain.count() == 0


@pytest.mark.parametrize("field", ["tokens_in", "tokens_out"])
@pytest.mark.parametrize("value", INVALID_COUNTS)
def test_direct_issuance_rejects_count_before_signing_or_append(monkeypatch, field, value):
    chain = meter.ReceiptChain()
    emit(chain, tokens_in=0, tokens_out=1)
    original_head = chain.head()
    signatures = []
    monkeypatch.setattr(_receipt, "_maybe_sign", lambda *args: signatures.append(args))
    counts = {"tokens_in": 1, "tokens_out": 2, field: value}
    with pytest.raises(ValueError, match=field):
        emit(chain, **counts)
    assert signatures == []
    assert chain.count() == 1
    assert chain.head() == original_head
    assert chain.verify() == (True, 1, -1)


@pytest.mark.parametrize("count", [0, 1, 10**20])
def test_valid_counts_and_context_updates_remain_exact(count):
    chain = meter.ReceiptChain()
    seen = []
    receipt, output = meter.meter(
        lambda: "ok", tokens_in=count, tokens_out=count, chain=chain,
        policy=lambda ctx: seen.append((ctx["tokens_in"], ctx["tokens_out"])) or True,
    )
    assert output == "ok"
    assert seen == [(count, count)]
    assert receipt["tokens_in"] == receipt["tokens_out"] == count
    assert type(receipt["tokens_out"]) is int
    with meter.metered(chain=chain, tokens_in=count) as state:
        state["tokens_out"] = count
    assert state["receipt"]["tokens_out"] == count
    assert chain.verify() == (True, 2, -1)


def test_count_objects_cannot_invoke_coercion():
    class IntLike:
        def __int__(self):
            raise AssertionError("token evidence must not invoke __int__")

    class IntSubclass(int):
        pass

    for count in (IntLike(), IntSubclass(2)):
        with pytest.raises(ValueError, match="tokens_in"):
            emit(meter.ReceiptChain(), tokens_in=count, tokens_out=0)
