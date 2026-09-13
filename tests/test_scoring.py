from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agent.models import ServiceRecord, Signal
from agent.scoring import dispute_supported, score_evidence

OBSERVED = datetime(2026, 9, 12, 14, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 9, 11, 20, 41, tzinfo=UTC)


def signal(signal_id="s1", author="resident-1", text="A couch blocks the sidewalk.",
           observed=OBSERVED, **kwargs):
    return Signal(
        id=signal_id,
        source="demo_feed",
        source_author_id=author,
        raw_text=text,
        reported_location="1530 S Michigan Ave",
        received_at=observed + timedelta(hours=1),
        observed_at=observed,
        provenance="seeded",
        **kwargs,
    )


def record(status="COMPLETED", conflict="pending"):
    completed = status == "COMPLETED"
    return ServiceRecord(
        id="demo-service-1", status=status, provenance="seeded",
        completed_at=COMPLETED_AT if completed else None,
        conflict=conflict if completed else "none",
    )


def test_canonical_scores_are_countable_facts():
    first = signal(image_sha256="a" * 64)
    second = signal("s2", "resident-2", "The sofa and bags are still obstructing the walkway.")
    scores = [
        score_evidence([first], precise_geocode=True, matching_service_record=record()),
        score_evidence([first, second], precise_geocode=True, matching_service_record=record()),
        score_evidence(
            [first, second], precise_geocode=True,
            matching_service_record=record(conflict="disputed"),
        ),
    ]
    assert [score.total for score in scores] == [65, 85, 100]
    assert [score.actionable for score in scores] == [False, True, True]
    assert scores[0].components == {
        "image": 30, "independent_sources": 20, "precise_geocode": 15,
        "service_match": 0, "persistence": 0,
    }


def test_open_record_corroborates_a_lone_signal():
    result = score_evidence(
        [signal(image_sha256="a" * 64)], precise_geocode=True,
        matching_service_record=record(status="OPEN"),
    )
    assert result.total == 80
    assert result.actionable


def test_completed_record_credits_nothing_until_dispute_is_confirmed():
    lone = [signal(image_sha256="a" * 64)]
    pending = score_evidence(lone, precise_geocode=True, matching_service_record=record())
    disputed = score_evidence(
        lone, precise_geocode=True, matching_service_record=record(conflict="disputed")
    )
    assert pending.total == 65
    assert disputed.total == 80


def test_dispute_needs_two_independent_observations_newer_than_completion():
    completed = record()
    first = signal(image_sha256="a" * 64)
    second = signal("s2", "resident-2", "Sofa still there")
    assert not dispute_supported([first], completed)
    assert dispute_supported([first, second], completed)
    same_author = signal("s3", "resident-1", "Still there, second message")
    assert not dispute_supported([first, same_author], completed)
    older = signal("s4", "resident-2", "Saw it last week",
                   observed=datetime(2026, 9, 11, 9, tzinfo=UTC))
    assert not dispute_supported([first, older], completed)
    unknown_time = replace(second, observed_at=None)
    assert not dispute_supported([first, unknown_time], completed)
    anonymous = signal("s5", None, "Anonymous but newer")
    assert not dispute_supported([first, anonymous], completed)
    assert not dispute_supported([first, second], record(status="OPEN"))


def test_service_record_argument_must_be_typed():
    with pytest.raises(ValueError):
        score_evidence([signal()], matching_service_record=True)
    with pytest.raises(ValueError):
        score_evidence([signal()], precise_geocode=1)


@pytest.mark.parametrize("duplicate", [
    signal("s2", "resident-1", "Another message from the same person."),
    signal("s2", "resident-2", "  A COUCH   blocks the sidewalk.  "),
    signal("s2", "resident-2", "Copied photo", image_sha256="a" * 64),
    signal("s2", "resident-2", "Shared report", repost_of="s1"),
    signal("s2", None, "Anonymous witness cannot establish independence"),
])
def test_reposts_same_author_and_unknown_identity_do_not_corroborate(duplicate):
    result = score_evidence([signal(image_sha256="a" * 64), duplicate], precise_geocode=True)
    assert result.total == 65


def test_shared_lineage_and_transitive_reposts_are_one_observation():
    reports = [
        signal("s1", "a", "First copy", repost_of="outside-post"),
        signal("s2", "b", "Second copy", repost_of="outside-post"),
        signal("s3", "c", "Third copy", repost_of="s2"),
    ]
    assert score_evidence(reports).components["independent_sources"] == 20


def test_unknown_authors_and_source_cap():
    assert score_evidence([signal(author=None)]).total == 0
    reports = [signal(str(i), str(i), f"Different observation {i}") for i in range(5)]
    assert score_evidence(reports).total == 40


@pytest.mark.parametrize("changes", [
    {"received_at": datetime(2026, 9, 12)},  # noqa: DTZ001 - intentional invalid input
    {"raw_text": " "},
    {"source_author_id": " "},
    {"image_sha256": "not-a-hash"},
    {"provenance": "probably real"},
    {"repost_of": "s1"},
])
def test_invalid_observation_facts_are_rejected(changes):
    with pytest.raises(ValueError):
        replace(signal(), **changes)
