"""Observation facts, not model decisions or claims of authority."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

PROVENANCE = {"seeded", "live", "synthetic"}


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

    def __post_init__(self) -> None:
        for name in ("id", "source", "raw_text", "reported_location"):
            nonempty(getattr(self, name), name)
        for name in ("source_author_id", "repost_of"):
            if getattr(self, name) is not None:
                nonempty(getattr(self, name), name)
        if self.provenance not in PROVENANCE:
            raise ValueError("unknown provenance")
        if self.repost_of == self.id:
            raise ValueError("a signal cannot repost itself")
        if self.image_sha256 is not None and (
            not isinstance(self.image_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.image_sha256)
        ):
            raise ValueError("image_sha256 must be a lowercase SHA256 digest")
        object.__setattr__(self, "received_at", utc_time(self.received_at))
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", utc_time(self.observed_at))
            if self.observed_at > self.received_at:
                raise ValueError("observation cannot be later than receipt")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["received_at"] = self.received_at.isoformat()
        data["observed_at"] = self.observed_at.isoformat() if self.observed_at else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        return cls(**data)


@dataclass(frozen=True)
class EvidenceScore:
    components: dict[str, int]
    threshold: int = 70

    @property
    def total(self) -> int:
        return sum(self.components.values())

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
