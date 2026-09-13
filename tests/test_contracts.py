from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent.contracts import (
    ActorContext,
    BudgetRecord,
    DecisionRecord,
    EvidenceComponents,
    EvidenceRecord,
    InvocationRecord,
    ModelRunMetadata,
)


def test_strict_money_and_round_trip():
    for bad in (True, 1.5, "100", -1):
        with pytest.raises(ValidationError):
            BudgetRecord(id="district", initial_cents=bad, policy_version="v3")
    budget = BudgetRecord(id="district", initial_cents=50000, policy_version="v3")
    assert BudgetRecord.model_validate_json(budget.model_dump_json()) == budget


def test_unknown_facts_and_opaque_images():
    evidence = EvidenceRecord(
        id="photo", image_ref="image-opaque-1", image_sha256="a" * 64,
        content_type="image/jpeg", size_bytes=100, provenance="synthetic",
        received_at=datetime.now(UTC),
    )
    assert evidence.observed_at is None
    assert EvidenceRecord.model_validate_json(evidence.model_dump_json()) == evidence
    for ref in ("../photo", "C:\\photos\\a.jpg", "/tmp/a", "https://example.com/a"):
        with pytest.raises(ValidationError):
            EvidenceRecord.model_validate({**evidence.model_dump(), "image_ref": ref})


def test_actor_and_invocation_vocabularies():
    with pytest.raises(ValidationError):
        ActorContext(actor_id="crew", actor_type="crew", label="Crew")
    with pytest.raises(ValidationError):
        InvocationRecord(id="i", trigger_event_id=1, trigger_type="SIGNAL_RECEIVED",
                         signal_id="s", policy_version="v3", status="FAILED",
                         created_at=datetime.now(UTC))


def test_naive_times_unknown_decisions_and_extra_authority_are_rejected():
    values = {"id": "decision", "issue_id": "issue", "trigger_event_id": 1,
              "decision_type": "MONITOR", "summary": "Need newer evidence",
              "score_components": EvidenceComponents(), "policy_version": "v3",
              "created_at": datetime.now(UTC)}
    for invalid in ({"decision_type": "PAY_ANYWAY"},
                    {"created_at": datetime.now(UTC).replace(tzinfo=None)},
                    {"authorized_payment_cents": 7200}):
        with pytest.raises(ValidationError):
            DecisionRecord(**(values | invalid))
    valid = DecisionRecord(**values)
    assert DecisionRecord.model_validate_json(valid.model_dump_json()) == valid


def test_model_metadata_unknown_usage_remains_null():
    metadata = ModelRunMetadata(role="image", model_id="m", vision_model_id="m",
                                region="us-west-2", prompt_version="p")
    assert ModelRunMetadata.model_validate_json(metadata.model_dump_json()).usage is None
