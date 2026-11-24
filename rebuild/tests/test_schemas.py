import pytest
from pydantic import ValidationError

from director.schemas import BuilderResult, Decision, Order, Provenance, ReviewResult


def test_order_minimal_gets_safe_defaults():
    o = Order.model_validate({"goal": "add(a, b) 함수 추가"})
    assert o.allowed_paths == [] and o.max_files_changed == 15 and o.risk_level == "LOW"


def test_order_ignores_unknown_keys_from_ai():
    o = Order.model_validate({"goal": "x", "mood": "happy"})
    assert not hasattr(o, "mood")


@pytest.mark.parametrize("bad", [{}, {"goal": ""}, {"goal": "x", "risk_level": "EXTREME"}, {"goal": "x", "max_files_changed": 0}])
def test_order_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        Order.model_validate(bad)


def test_review_verdict_is_closed_set():
    assert ReviewResult(verdict="pass", summary="ok").p0 == []
    with pytest.raises(ValidationError):
        ReviewResult(verdict="looks good", summary="ok")


def test_decision_and_builder_result():
    assert Decision(decision="HUMAN_REQUIRED", rationale="결제 코드").next_steps == []
    with pytest.raises(ValidationError):
        Decision(decision="MAYBE", rationale="?")
    with pytest.raises(ValidationError):
        BuilderResult(status="DONE", summary="?")


def test_provenance_declared_default():
    p = Provenance(role="HEAD", provider="claude", executable="/x/claude", argv=["claude"], timestamp="2026-11-24T00:00:00")
    assert p.api_key_used is False and p.exit_code is None
