"""Deterministic V1 evidence points. This does not decide whether to dispatch."""

from __future__ import annotations

from collections.abc import Sequence

from .models import EvidenceScore, Signal


def independent_source_count(signals: Sequence[Signal]) -> int:
    """Conservatively group known authors, copies, images, and repost lineage.

    Source-author IDs must be canonical adapter identities, not channel-local IDs.
    Exact normalized text/image matches are duplicate evidence, not extra witnesses.
    This is a small demo check, not semantic matching or production fraud detection.
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
    return len({
        root(f"signal:{signal.id}") for signal in signals if signal.source_author_id is not None
    })


def score_evidence(
    signals: Sequence[Signal],
    *,
    precise_geocode: bool = False,
    matching_service_record: bool = False,
) -> EvidenceScore:
    if type(precise_geocode) is not bool or type(matching_service_record) is not bool:
        raise ValueError("evidence flags must be booleans")
    return EvidenceScore({
        "image": 30 if any(s.image_sha256 is not None for s in signals) else 0,
        "independent_sources": min(independent_source_count(signals), 2) * 20,
        "precise_geocode": 15 if precise_geocode else 0,
        "service_match": 15 if matching_service_record else 0,
    })
