import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.migrations import SCHEMA_VERSION
from agent.store import Store

# Frozen original schema, deliberately independent of the production migration DDL.
LEGACY_SQL = """
CREATE TABLE issues (id TEXT PRIMARY KEY, category TEXT NOT NULL, location TEXT NOT NULL,
status TEXT NOT NULL DEFAULT 'CANDIDATE', evidence_score INTEGER NOT NULL DEFAULT 0,
score_json TEXT NOT NULL, geocode_json TEXT, service_record_json TEXT, created_at TEXT NOT NULL);
CREATE TABLE signals (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE issue_sources (issue_id TEXT NOT NULL REFERENCES issues(id),
signal_id TEXT NOT NULL UNIQUE REFERENCES signals(id), PRIMARY KEY(issue_id,signal_id));
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT,
issue_id TEXT NOT NULL REFERENCES issues(id), event_type TEXT NOT NULL,
timestamp TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
PRAGMA user_version=1;
"""


def legacy_fixture(path):
    score = {"components": {"image": 30, "independent_sources": 40,
             "precise_geocode": 15, "service_match": 15, "persistence": 0},
             "total": 100, "threshold": 70, "actionable": True}
    signal = {"id": "legacy-signal", "source": "demo_feed", "source_author_id": "witness",
              "raw_text": "Couch", "reported_location": "Demo", "received_at": "2026-09-12T00:00Z",
              "provenance": "seeded", "observed_at": None, "image_sha256": "a" * 64,
              "repost_of": None}
    with sqlite3.connect(path) as db:
        db.executescript(LEGACY_SQL)
        db.execute("INSERT INTO issues VALUES (?,?,?,?,?,?,?,?,?)", (
            "legacy", "bulky_waste", "Demo", "CANDIDATE", 100, json.dumps(score),
            '{"accuracy_m": 10, "provenance": "seeded"}',
            ('{"id":"311", "status":"COMPLETED", "provenance":"seeded",'
             '"completed_at":"2026-09-11T00:00Z", "conflict":"disputed"}'),
            "2026-09-12T00:00:00+00:00",
        ))
        db.execute("INSERT INTO signals VALUES (?,?)", ("legacy-signal", json.dumps(signal)))
        db.execute("INSERT INTO issue_sources VALUES (?,?)", ("legacy", "legacy-signal"))
        db.execute("INSERT INTO events VALUES (?,?,?,?,?)",
                   (41, "legacy", "OLD_EVENT", "2026-09-12T00:00:00Z", '{ "score": 100 }'))
        db.execute("UPDATE sqlite_sequence SET seq=80 WHERE name='events'")


def raw_state(path):
    with sqlite3.connect(path) as db:
        return {table: db.execute(f"SELECT * FROM {table}").fetchall()
                for table in ("issues", "signals", "issue_sources", "events")}


def test_unversioned_unknown_database_is_not_blessed(tmp_path):
    path = tmp_path / "unknown.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(ValueError, match="unversioned"):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("unrelated",)
        ]


def test_schema_version_three(tmp_path):
    with Store(tmp_path / "new.db") as store:
        assert SCHEMA_VERSION == 5
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 5


def test_upgrade_copied_v1_preserves_bytes_relations_scores_and_sequence(tmp_path):
    original, copied = tmp_path / "old.db", tmp_path / "copy.db"
    legacy_fixture(original)
    before = raw_state(original)
    shutil.copyfile(original, copied)
    with Store(copied) as store:
        assert store.get_issue("legacy")["evidence_score"] == 100
        assert store.get_issue("legacy")["service_record"]["conflict"] == "disputed"
        assert store.get_issue("legacy")["signal_ids"] == ["legacy-signal"]
        assert store.db.execute("SELECT * FROM signals").fetchall()[0][1] == before["signals"][0][1]
        actual = tuple(store.db.execute(
            "SELECT id,issue_id,event_type,timestamp,payload FROM events"
        ).fetchone())
        assert actual == before["events"][0]
        assert tuple(store.db.execute(
            "SELECT id,category,location,status,evidence_score,score_json,geocode_json,"
            "service_record_json,created_at FROM issues"
        ).fetchone()) == before["issues"][0]
        store.create_issue("new", "litter", "Other")
        assert store.events("new")[0]["id"] == 81
        assert store.pending_invocations() == []
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.db.execute("DELETE FROM events")
    with Store(copied) as store:
        assert store.events("legacy")[0]["payload"] == {"score": 100}
        assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert raw_state(original) == before


def test_failed_upgrade_rolls_back_ddl_data_and_version(tmp_path, monkeypatch):
    from agent import migrations

    path = tmp_path / "old.db"
    legacy_fixture(path)
    before = raw_state(path)
    real = migrations._upgrade_two

    def fail_after_ddl(db):
        real(db)
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(migrations, "_upgrade_two", fail_after_ddl)
    with pytest.raises(RuntimeError, match="injected"):
        Store(path)
    assert raw_state(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='jobs'").fetchone() is None
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE events SET payload='{}'")


@pytest.mark.parametrize("legacy", [False, True])
def test_concurrent_first_open_and_upgrade(tmp_path, legacy):
    path = tmp_path / "concurrent.db"
    if legacy:
        legacy_fixture(path)

    def open_store(_):
        with Store(path) as store:
            return store.db.execute("PRAGMA user_version").fetchone()[0]

    with ThreadPoolExecutor(max_workers=4) as workers:
        assert list(workers.map(open_store, range(8))) == [5] * 8
