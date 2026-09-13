"""Bounded trusted fixture adapters for B4; they never contact municipal systems."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import contracts as c
from .models import Signal


@dataclass(frozen=True)
class GeocodeResult:
    outcome: str
    location: c.LocationRecord | None
    source_mode: str = "seeded_adapter"
    error_code: str | None = None


@dataclass(frozen=True)
class ServiceResult:
    outcome: str
    external_record_id: str | None = None
    status: str | None = None
    completed_at: datetime | None = None
    source_mode: str = "seeded_adapter"
    error_code: str | None = None


class SeededAdapters:
    """Reviewed local lookup fixtures. Unknown inputs remain unknown; no fuzzy live lookup."""

    def __init__(self, data_root: str | Path = "data"):
        root = Path(data_root)
        self._addresses = {
            item["address"].casefold(): c.LocationRecord(
                lat=item["lat"], lon=item["lon"], accuracy_m=item["accuracy_m"],
                provenance=item["provenance"],
            )
            for item in json.loads((root / "addresses.json").read_text(encoding="utf-8"))
        }
        self._records = json.loads((root / "service_records.json").read_text(encoding="utf-8"))

    def geocode(self, signal: Signal) -> GeocodeResult:
        location = self._addresses.get(signal.reported_location.casefold())
        return GeocodeResult("MATCH", location) if location else GeocodeResult("NO_MATCH", None)

    def service_record(self, signal: Signal) -> ServiceResult:
        text = signal.raw_text.casefold()
        if signal.reported_location.casefold() == "1530 s michigan ave" and any(
            word in text for word in ("couch", "sofa")
        ):
            record = self._records[0]
            return ServiceResult("MATCH", external_record_id=record["id"], status=record["status"],
                completed_at=(datetime.fromisoformat(record["completed_at"]).astimezone(UTC)
                              if record.get("completed_at") else None))
        return ServiceResult("NO_MATCH")
