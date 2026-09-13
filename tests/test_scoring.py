from dataclasses import replace
from datetime import UTC, datetime

import pytest

from agent.models import Signal
from agent.scoring import score_evidence


def signal(signal_id="s1", author="resident-1", text="A couch blocks the sidewalk.", **kwargs):
    return Signal(
        id=signal_id,
        source="demo_feed",
        source_author_id=author,
        raw_text=text,
        reported_location="1530 S Michigan Ave",
        received_at=datetime(2026, 9, 12, 15, tzinfo=UTC),
        observed_at=datetime(2026, 9, 12, 14, tzinfo=UTC),
        provenance="seeded",
        **kwargs,
    )


def test_canonical_scores_are_countable_facts():
    first = signal(image_sha256="a" * 64)
    second = signal("s2", "resident-2", "The sofa and bags are still obstructing the walkway.")
    scores = [
        score_evidence([first], precise_geocode=True),
        score_evidence([first, second], precise_geocode=True),
        score_evidence([first, second], precise_geocode=True, matching_service_record=True),
    ]
    assert [score.total for score in scores] == [65, 85, 100]
    assert [score.actionable for score in scores] == [False, True, True]
    assert scores[0].components == {
        "image": 30, "independent_sources": 20, "precise_geocode": 15, "service_match": 0
    }


def test_early_service_match_is_not_hidden_to_force_watch():
    result = score_evidence(
        [signal(image_sha256="a" * 64)], precise_geocode=True, matching_service_record=True
    )
    assert result.total == 80
    assert result.actionable


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
