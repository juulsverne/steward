from datetime import UTC, datetime

import pytest

from agent.models import ServiceRecord

COMPLETED_AT = datetime(2026, 9, 11, 20, 41, tzinfo=UTC)


def test_completed_record_round_trips_and_normalizes_to_utc():
    record = ServiceRecord(
        id="demo-service-1", status="COMPLETED", provenance="seeded",
        completed_at="2026-09-11T15:41:00-05:00", conflict="pending",
    )
    assert record.completed_at == COMPLETED_AT
    assert record.to_dict() == {
        "id": "demo-service-1", "status": "COMPLETED", "provenance": "seeded",
        "completed_at": "2026-09-11T20:41:00+00:00", "conflict": "pending",
    }
    assert ServiceRecord.from_dict(record.to_dict()) == record


def test_open_record_has_no_completion_and_no_conflict():
    record = ServiceRecord(id="demo-service-2", status="OPEN", provenance="seeded")
    assert record.completed_at is None
    assert record.conflict == "none"


@pytest.mark.parametrize("changes", [
    {"status": "DONE"},
    {"status": "COMPLETED", "completed_at": None},
    {"status": "OPEN", "completed_at": COMPLETED_AT},
    {"status": "OPEN", "conflict": "pending"},
    {"conflict": "resolved"},
    {"provenance": "probably real"},
    {"id": " "},
])
def test_invalid_service_records_are_rejected(changes):
    base = {
        "id": "demo-service-1", "status": "COMPLETED", "provenance": "seeded",
        "completed_at": COMPLETED_AT, "conflict": "pending",
    }
    with pytest.raises(ValueError):
        ServiceRecord(**{**base, **changes})
