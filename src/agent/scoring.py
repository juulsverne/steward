"""Deterministic V1 evidence points. This does not decide whether to dispatch."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from .images import REUSE_MAX_DISTANCE, hamming
from .models import EvidenceScore, ServiceRecord, Signal

DISPUTE_MIN_INDEPENDENT_SOURCES = 2
PERSISTENCE_MIN_GAP = timedelta(hours=24)


def _source_groups(signals: Sequence[Signal]) -> dict[str, list[Signal]]:
    """Group observations that share an author, normalized text, image, or repost lineage.

    Source-author IDs must be canonical adapter identities, not channel-local IDs.
    Only known-author signals appear in the returned groups; anonymous signals still
    join lineage so a repost cannot launder a copy into a new witness. This is a small
    demo check, not semantic matching or production fraud detection.
    """
    parents: dict[str, str] = {}

    def root(key: str) -> str:
        parents.setdefault(key, key)
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    def join(left: str, right: str) -> None:
        parents[root(left)] = root(right)

    for signal in signals:
        key = f"signal:{signal.id}"
        root(key)
        join(key, f"text:{' '.join(signal.raw_text.casefold().split())}")
        if signal.source_author_id is not None:
            join(key, f"author:{signal.source_author_id}")
        if signal.image_sha256 is not None:
            join(key, f"image:{signal.image_sha256}")
        if signal.repost_of is not None:
            join(key, f"signal:{signal.repost_of}")
    groups: dict[str, list[Signal]] = {}
    for signal in signals:
        if (signal.effective_source_role != "official_record"
                and signal.source_author_id is not None):
            groups.setdefault(root(f"signal:{signal.id}"), []).append(signal)
    return groups


def independent_source_count(signals: Sequence[Signal]) -> int:
    return len(_source_groups(signals))


def newer_independent_observations(signals: Sequence[Signal], record: ServiceRecord) -> int:
    """Independent sources with at least one observation observed after the completion."""
    if record.status != "COMPLETED":
        return 0
    return sum(
        1
        for members in _source_groups(signals).values()
        if any(
            member.observed_at is not None and member.observed_at > record.completed_at
            for member in members
        )
    )


def dispute_supported(signals: Sequence[Signal], record: ServiceRecord) -> bool:
    """Deterministic precondition for disputing a COMPLETED record; not the decision itself."""
    return newer_independent_observations(signals, record) >= DISPUTE_MIN_INDEPENDENT_SOURCES


def service_record_points(record: ServiceRecord | None) -> int:
    """OPEN/IN_PROGRESS corroborate now; COMPLETED counts only once the dispute is confirmed."""
    if record is None:
        return 0
    if record.status in {"OPEN", "IN_PROGRESS"}:
        return 15
    return 15 if record.conflict == "disputed" else 0


def persistence_points(signals: Sequence[Signal]) -> int:
    """Same reporter, distinct image, at least 24h after their earlier image: 10, once."""
    for members in _source_groups(signals).values():
        fresh = [
            member for member in members
            if member.image_sha256 is not None
            and member.observed_at is not None
            and member.repost_of is None
        ]
        for earlier in fresh:
            for later in fresh:
                if (
                    earlier.source_author_id == later.source_author_id
                    and later.observed_at - earlier.observed_at >= PERSISTENCE_MIN_GAP
                    and later.image_sha256 != earlier.image_sha256
                    and _fresh_lineage(earlier, later)
                ):
                    return 10
    return 0


def _fresh_lineage(earlier: Signal, later: Signal) -> bool:
    """Server-derived perceptual fingerprints prevent a re-encoded prior photo scoring fresh."""
    # B4 must backfill/recompute historical lineage before it can award persistence.
    # Missing fingerprints are unknown freshness, never evidence of a new observation.
    if earlier.image_dhash is None or later.image_dhash is None:
        return False
    return hamming(earlier.image_dhash, later.image_dhash) > REUSE_MAX_DISTANCE


def score_evidence(
    signals: Sequence[Signal],
    *,
    precise_geocode: bool = False,
    matching_service_record: ServiceRecord | None = None,
) -> EvidenceScore:
    if type(precise_geocode) is not bool:
        raise ValueError("precise_geocode must be a boolean")
    if matching_service_record is not None and not isinstance(
        matching_service_record, ServiceRecord
    ):
        raise ValueError("matching_service_record must be a ServiceRecord or None")
    return EvidenceScore({
        "image": 30 if any(s.effective_source_role != "official_record" and s.image_sha256 is not None
                             for s in signals) else 0,
        "independent_sources": min(independent_source_count(signals), 2) * 20,
        "precise_geocode": 15 if precise_geocode else 0,
        "service_match": service_record_points(matching_service_record),
        "persistence": persistence_points(signals),
    })
