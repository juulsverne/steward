"""Trusted intake adapters. They bind source lineage on the server, never from client fields."""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from . import contracts as c
from .images import ImageStorage, NormalizedImage, UploadError
from .models import Signal, utc_time
from .store import Store

POLICY_VERSION = "south-loop-v3"


def stable_id(kind: str, actor_or_key: str, key: str) -> str:
    return f"{kind}-{uuid5(NAMESPACE_URL, f'steward:{kind}:{actor_or_key}:{key}')}"


def resident_signal(*, actor: c.ActorContext, idempotency_key: str, description: str,
                    location: str, received_at: datetime, observed_at: datetime | None,
                    image: NormalizedImage | None, provenance: str = "live") -> Signal:
    return Signal(id=stable_id("signal", actor.actor_id, idempotency_key), source="resident_intake",
        source_author_id=actor.actor_id, source_role="resident_observation", raw_text=description,
        reported_location=location, received_at=received_at, observed_at=observed_at,
        provenance=provenance, image_sha256=image.image_sha256 if image else None,
        image_dhash=image.image_dhash if image else None)


def community_signal(row: dict, *, image: NormalizedImage | None) -> Signal:
    """Adapter-only conversion of the reviewed simulated feed fixture."""
    return Signal(id=row["id"], source="south_loop_neighbors_simulated",
        source_author_id=row["source_author_id"], source_role="community_observation",
        raw_text=row["raw_text"], reported_location=row["reported_location"],
        received_at=utc_time(row["received_at"]), observed_at=utc_time(row["observed_at"]),
        provenance="seeded", image_sha256=image.image_sha256 if image else None,
        image_dhash=image.image_dhash if image else None)


def official_signal(*, source_id: str, text: str, location: str, received_at: datetime) -> Signal:
    """Official records are auditable sources, never physical witnesses or lookup triggers."""
    return Signal(id=source_id, source="official_service_fixture", source_author_id="official-311",
        source_role="official_record", raw_text=text, reported_location=location,
        received_at=received_at, provenance="seeded")


def persist_official_record(store: Store, *, source_id: str, text: str, location: str,
                            received_at: datetime) -> c.SignalReceipt:
    """Persist one adapter-supplied official source without triggering lookup or agent work."""
    signal = official_signal(source_id=source_id, text=text, location=location, received_at=received_at)
    actor = c.ActorContext(actor_id="steward-service", actor_type="service", label="Steward",
                           district_id="south_loop_demo")
    return store.store_signal(signal, actor=actor)


def evidence_bundle(signal: Signal, image: NormalizedImage, *, received_at: datetime,
                    provenance: str) -> tuple[c.SignalEvidenceBundle, str]:
    evidence_id = stable_id("evidence", signal.id, signal.id)
    image_ref = stable_id("image", signal.id, signal.id)
    record = c.EvidenceRecord(id=evidence_id, image_ref=image_ref, image_sha256=image.image_sha256,
        content_type="image/jpeg", size_bytes=image.size_bytes, provenance=provenance,
        received_at=received_at, observed_at=signal.observed_at, perceptual_hash=image.image_dhash)
    association = c.EvidenceAssociation(id=stable_id("association", signal.id, signal.id),
        evidence_id=evidence_id, signal_id=signal.id, role="signal", created_at=received_at)
    return c.SignalEvidenceBundle(evidence=record, association=association), image_ref


def persist_signal(store: Store, *, signal: Signal, context: c.MutationContext,
                   image: NormalizedImage | None, image_root, provenance: str) -> c.RequestReceipt:
    bundle = None
    if image is not None:
        bundle, image_ref = evidence_bundle(signal, image, received_at=signal.received_at,
                                            provenance=provenance)
        try:
            ImageStorage(image_root).put(image_ref, image)
        except UploadError as error:
            if error.status == 409:
                from .store import IdempotencyConflict
                raise IdempotencyConflict("image reference content conflict") from error
            raise
    return store.receive_signal(signal, context=context,
        invocation=c.PendingInvocationSpec(id=stable_id("invocation", signal.id, signal.id),
            trigger_type="SIGNAL_RECEIVED", policy_version=POLICY_VERSION), evidence=bundle)
