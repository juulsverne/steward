"""Observation facts, not model decisions or claims of authority."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

PROVENANCE = {"seeded", "live", "synthetic"}
SOURCE_ROLES = {"resident_observation", "community_observation", "official_record"}


def nonempty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")


def utc_time(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class Signal:
    id: str
    source: str
    source_author_id: str | None
    raw_text: str
    reported_location: str
    received_at: datetime
    provenance: str
    observed_at: datetime | None = None
    image_sha256: str | None = None
    repost_of: str | None = None
    # ``None`` deliberately serializes as absent so schema-1 fixture payloads retain their
    # original bytes and IDs. Trusted adapters set an explicit role for new records.
    source_role: str | None = None
    image_dhash: str | None = None

    def __post_init__(self) -> None:
        for name in ("id", "source", "raw_text", "reported_location"):
            nonempty(getattr(self, name), name)
        for name in ("source_author_id", "repost_of"):
            if getattr(self, name) is not None:
                nonempty(getattr(self, name), name)
        if self.provenance not in PROVENANCE:
            raise ValueError("unknown provenance")
        if self.source_role is not None and self.source_role not in SOURCE_ROLES:
            raise ValueError("unknown source role")
        if self.source_role == "official_record" and self.image_sha256 is not None:
            raise ValueError("official records cannot claim physical image evidence")
        if self.repost_of == self.id:
            raise ValueError("a signal cannot repost itself")
        if self.image_sha256 is not None and (
            not isinstance(self.image_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.image_sha256)
        ):
            raise ValueError("image_sha256 must be a lowercase SHA256 digest")
        if self.image_dhash is not None and (not isinstance(self.image_dhash, str)
                or not re.fullmatch(r"[0-9a-f]+", self.image_dhash)):
            raise ValueError("image_dhash must be a lowercase hexadecimal fingerprint")
        object.__setattr__(self, "received_at", utc_time(self.received_at))
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", utc_time(self.observed_at))
            if self.observed_at > self.received_at:
                raise ValueError("observation cannot be later than receipt")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["received_at"] = self.received_at.isoformat()
        data["observed_at"] = self.observed_at.isoformat() if self.observed_at else None
        if self.source_role is None:
            data.pop("source_role")
        if self.image_dhash is None:
            data.pop("image_dhash")
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        return cls(**data)

    @property
    def effective_source_role(self) -> str:
        """Legacy observations remain observations; only server adapters add explicit roles."""
        return self.source_role or "resident_observation"


@dataclass(frozen=True)
class EvidenceScore:
    components: dict[str, int]
    threshold: int = 70

    @property
    def total(self) -> int:
        return min(100, sum(self.components.values()))

    @property
    def actionable(self) -> bool:
        return self.total >= self.threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "components": self.components,
            "total": self.total,
            "threshold": self.threshold,
            "actionable": self.actionable,
        }


SERVICE_STATUSES = {"OPEN", "IN_PROGRESS", "COMPLETED"}
CONFLICT_STATES = {"none", "pending", "disputed"}


@dataclass(frozen=True)
class ServiceRecord:
    """One external system's account of a service request. Never physical truth."""

    id: str
    status: str
    provenance: str
    completed_at: datetime | None = None
    conflict: str = "none"

    def __post_init__(self) -> None:
        nonempty(self.id, "record.id")
        if self.status not in SERVICE_STATUSES:
            raise ValueError("service record status must be OPEN, IN_PROGRESS, or COMPLETED")
        if self.provenance not in PROVENANCE:
            raise ValueError("service record needs explicit provenance")
        if self.conflict not in CONFLICT_STATES:
            raise ValueError("conflict must be none, pending, or disputed")
        if self.status == "COMPLETED":
            if self.completed_at is None:
                raise ValueError("a COMPLETED record needs completed_at")
            object.__setattr__(self, "completed_at", utc_time(self.completed_at))
        else:
            if self.completed_at is not None:
                raise ValueError("only a COMPLETED record has completed_at")
            if self.conflict != "none":
                raise ValueError("only a COMPLETED record can conflict with newer evidence")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServiceRecord:
        return cls(**data)
