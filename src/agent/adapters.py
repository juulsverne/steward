"""Bounded trusted fixture adapters for B4; they never contact municipal systems."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import contracts as c
from .models import Signal

FIXTURE_SCENARIOS = {"baseline", "couch-open-one-v1"}


def fixture_service_record(data_root: str | Path, scenario: str) -> dict:
    """One named, reviewed fixture choice shared by seed and later API lookups."""
    if scenario not in FIXTURE_SCENARIOS:
        raise ValueError("unknown fixture scenario")
    root = Path(data_root)
    record = dict(json.loads((root / "service_records.json").read_text(encoding="utf-8"))[0])
    if scenario == "couch-open-one-v1":
        record.update(status="OPEN", completed_at=None)
    return record


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

    def __init__(self, data_root: str | Path = "data", *, scenario: str = "baseline"):
        root = Path(data_root)
        if scenario not in FIXTURE_SCENARIOS:
            raise ValueError("unknown fixture scenario")
        self.scenario = scenario
        self._addresses = {
            item["address"].casefold(): c.LocationRecord(
                lat=item["lat"], lon=item["lon"], accuracy_m=item["accuracy_m"],
                provenance=item["provenance"],
            )
            for item in json.loads((root / "addresses.json").read_text(encoding="utf-8"))
        }
        self._record = fixture_service_record(root, scenario)

    def geocode(self, signal: Signal) -> GeocodeResult:
        location = self._addresses.get(signal.reported_location.casefold())
        return GeocodeResult("MATCH", location) if location else GeocodeResult("NO_MATCH", None)

    def service_record(self, signal: Signal) -> ServiceResult:
        text = signal.raw_text.casefold()
        if signal.reported_location.casefold() == "state st & madison st (demo)" and any(
            word in text for word in ("couch", "sofa")
        ):
            record = self._record
            return ServiceResult("MATCH", external_record_id=record["id"], status=record["status"],
                completed_at=(datetime.fromisoformat(record["completed_at"]).astimezone(UTC)
                              if record.get("completed_at") else None))
        return ServiceResult("NO_MATCH")
