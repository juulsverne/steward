"""Transactional foundation store. No agent judgment or financial mutations yet."""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from .models import PROVENANCE, Signal, nonempty, utc_time
from .scoring import score_evidence

POLICY_VERSION = "south-loop-foundation-v1"
PRECISE_GEOCODE_MAX_M = 30
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY, category TEXT NOT NULL, location TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'CANDIDATE',
    evidence_score INTEGER NOT NULL DEFAULT 0 CHECK(evidence_score BETWEEN 0 AND 100),
    score_json TEXT NOT NULL, geocode_json TEXT, service_record_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS issue_sources (
    issue_id TEXT NOT NULL REFERENCES issues(id),
    signal_id TEXT NOT NULL UNIQUE REFERENCES signals(id),
    PRIMARY KEY (issue_id, signal_id)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL REFERENCES issues(id),
    event_type TEXT NOT NULL, timestamp TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
"""


def encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False)


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    """One connection per invocation; writer transactions serialize score updates.

    Arguments are facts supplied by trusted adapters, not exposed HTTP tool inputs.
    Future action tools must derive authority from stored evidence and policy.
    """

    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys = ON")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ValueError(f"unsupported database schema {version}")
            if version == 0:
                self.db.executescript(
                    f"BEGIN IMMEDIATE;\n{SCHEMA}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;"
                )
        except Exception:
            self.db.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.db.close()

    @contextmanager
    def _write(self):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            yield

    def _event(self, issue_id: str, event_type: str, payload: dict) -> None:
        self.db.execute(
            "INSERT INTO events(issue_id, event_type, timestamp, payload) VALUES (?, ?, ?, ?)",
            (issue_id, event_type, now(), encoded({
                **payload, "policy_version": POLICY_VERSION, "actor": "foundation_service",
            })),
        )

    def _require_open(self, issue_id: str) -> dict:
        issue = self.get_issue(issue_id)
        if issue["status"] not in {"CANDIDATE", "MONITORING", "ACTIONABLE", "RESOLUTION_ACTIVE"}:
            raise ValueError("issue closed or not accepting evidence; preserve new signal for review")
        return issue

    def create_issue(self, issue_id: str, category: str, location: str) -> dict:
        for name, value in (("issue_id", issue_id), ("category", category), ("location", location)):
            nonempty(value, name)
        with self._write():
            existing = self.db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
            if existing:
                if existing["category"] != category or existing["location"] != location:
                    raise ValueError("issue id payload conflict")
            else:
                self.db.execute(
                    "INSERT INTO issues(id, category, location, score_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (issue_id, category, location, encoded(score_evidence([]).to_dict()), now()),
                )
                self._event(issue_id, "ISSUE_CREATED", {"category": category, "location": location})
            result = self.get_issue(issue_id)
        return result

    def _refresh_score(self, issue_id: str) -> dict:
        issue = self.get_issue(issue_id)
        rows = self.db.execute(
            "SELECT s.payload FROM signals s JOIN issue_sources x ON x.signal_id = s.id "
            "WHERE x.issue_id = ? ORDER BY s.id", (issue_id,),
        ).fetchall()
        signals = [Signal.from_dict(json.loads(row["payload"])) for row in rows]
        geocode = issue["geocode"]
        score = score_evidence(
            signals,
            precise_geocode=geocode is not None and geocode["accuracy_m"] <= PRECISE_GEOCODE_MAX_M,
            matching_service_record=issue["service_record"] is not None,
        ).to_dict()
        self.db.execute(
            "UPDATE issues SET evidence_score = ?, score_json = ? WHERE id = ?",
            (score["total"], encoded(score), issue_id),
        )
        return score

    def add_signal(self, issue_id: str, signal: Signal) -> dict:
        payload = encoded(signal.to_dict())
        with self._write():
            # Return identical retries even if the issue has since closed.
            existing = self.db.execute(
                "SELECT s.payload, x.issue_id FROM signals s "
                "JOIN issue_sources x ON s.id = x.signal_id WHERE s.id = ?", (signal.id,),
            ).fetchone()
            if existing:
                if existing["payload"] != payload:
                    raise ValueError("signal id payload conflict")
                if existing["issue_id"] != issue_id:
                    raise ValueError("signal already linked to another issue")
            else:
                self._require_open(issue_id)
                self.db.execute("INSERT INTO signals(id, payload) VALUES (?, ?)", (signal.id, payload))
                self.db.execute(
                    "INSERT INTO issue_sources(issue_id, signal_id) VALUES (?, ?)",
                    (issue_id, signal.id),
                )
                score = self._refresh_score(issue_id)
                self._event(issue_id, "SIGNAL_LINKED", {
                    "signal_id": signal.id, "provenance": signal.provenance,
                    "score": score, "evidence_ids": self.get_issue(issue_id)["signal_ids"],
                })
            result = self.get_issue(issue_id)
        return result

    def record_geocode(self, issue_id: str, *, accuracy_m: float, provenance: str) -> dict:
        if (
            type(accuracy_m) not in (int, float) or not math.isfinite(accuracy_m)
            or accuracy_m < 0 or provenance not in PROVENANCE
        ):
            raise ValueError("geocode needs finite nonnegative accuracy and explicit provenance")
        geocode = {"accuracy_m": float(accuracy_m), "provenance": provenance}
        with self._write():
            issue = self._require_open(issue_id)
            if issue["geocode"] != geocode:
                self.db.execute(
                    "UPDATE issues SET geocode_json = ? WHERE id = ?", (encoded(geocode), issue_id)
                )
                self._event(issue_id, "GEOCODE_RECORDED", {
                    "geocode": geocode, "score": self._refresh_score(issue_id),
                })
            result = self.get_issue(issue_id)
        return result

    def record_service_match(self, issue_id: str, record: dict) -> dict:
        """Record a supplied matching-record fact, not a lookup or a physical dispute."""
        if set(record) != {"id", "status", "provenance", "completed_at"}:
            raise ValueError("service record requires id, status, provenance, completed_at")
        nonempty(record["id"], "record.id")
        nonempty(record["status"], "record.status")
        if record["provenance"] not in PROVENANCE:
            raise ValueError("service record needs explicit provenance")
        record = dict(record)
        if record["completed_at"] is not None:
            record["completed_at"] = utc_time(record["completed_at"]).isoformat()
        with self._write():
            issue = self._require_open(issue_id)
            if issue["service_record"] != record:
                self.db.execute(
                    "UPDATE issues SET service_record_json = ? WHERE id = ?",
                    (encoded(record), issue_id),
                )
                self._event(issue_id, "SERVICE_MATCH_RECORDED", {
                    "record": record, "score": self._refresh_score(issue_id),
                })
            result = self.get_issue(issue_id)
        return result

    def get_issue(self, issue_id: str) -> dict:
        row = self.db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None:
            raise KeyError(issue_id)
        issue = dict(row)
        for column, key in (
            ("score_json", "score"), ("geocode_json", "geocode"),
            ("service_record_json", "service_record"),
        ):
            value = issue.pop(column)
            issue[key] = json.loads(value) if value is not None else None
        issue["signal_ids"] = [r[0] for r in self.db.execute(
            "SELECT signal_id FROM issue_sources WHERE issue_id = ? ORDER BY signal_id", (issue_id,)
        )]
        return issue

    def events(self, issue_id: str) -> list[dict]:
        self.get_issue(issue_id)
        return [
            {**dict(row), "payload": json.loads(row["payload"])}
            for row in self.db.execute(
                "SELECT * FROM events WHERE issue_id = ? ORDER BY id", (issue_id,)
            )
        ]
