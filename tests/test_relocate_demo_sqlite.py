"""Offline checks for the copy-only public demo relocation utility."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "relocate_demo_sqlite", Path(__file__).parents[1] / "scripts" / "relocate_demo_sqlite.py"
)
assert SPEC and SPEC.loader
relocate_demo_sqlite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relocate_demo_sqlite)


def _source(path: Path, *, invocation_status: str = "COMPLETED") -> tuple[float, float]:
    anchor = (41.70001, -87.60001)
    location = "Original demo anchor"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE issues (id TEXT PRIMARY KEY, location TEXT, geocode_json TEXT, status TEXT,
            evidence_score INTEGER, state_revision INTEGER, accepted_submission_id TEXT, resolved_at TEXT);
        CREATE TABLE signals (id TEXT PRIMARY KEY, payload TEXT);
        CREATE TABLE events (id INTEGER PRIMARY KEY, payload TEXT);
        CREATE TABLE plans (id TEXT PRIMARY KEY, record_json TEXT);
        CREATE TABLE jobs (id TEXT PRIMARY KEY, issue_id TEXT, plan_id TEXT, vendor_id TEXT,
            price_cents INTEGER, status TEXT, state_revision INTEGER, record_json TEXT);
        CREATE TABLE payments (id TEXT PRIMARY KEY, issue_id TEXT, job_id TEXT, reservation_id TEXT,
            submission_id TEXT, verification_id TEXT, amount_cents INTEGER, record_json TEXT);
        CREATE TABLE ledger (id TEXT PRIMARY KEY, budget_id TEXT, job_id TEXT, reservation_id TEXT,
            payment_id TEXT, kind TEXT, amount_cents INTEGER, event_id INTEGER, record_json TEXT);
        CREATE TABLE invocations (id TEXT PRIMARY KEY, trigger_event_id INTEGER, trigger_type TEXT,
            signal_id TEXT, issue_id TEXT, job_id TEXT, status TEXT, state_revision INTEGER,
            fencing_token INTEGER, record_json TEXT);
    """)
    payload = {
        "location": location,
        "summary": f"Crew checked in at {location}.",
        "dispatch_location": {"lat": anchor[0], "lon": anchor[1]},
        "checkin_location": {"lat": anchor[0] + 0.00008, "lon": anchor[1]},
        "terminal_json": json.dumps({"decision": f"Relocate from {location}"}),
    }
    db.execute("INSERT INTO issues VALUES (?,?,?,?,?,?,?,?)", (
        "demo-couch", location, json.dumps({"lat": anchor[0], "lon": anchor[1]}),
        "RESOLVED", 100, 9, "submission-1", "2026-09-14T00:00:00Z",
    ))
    db.execute("INSERT INTO signals VALUES (?,?)", ("signal-1", json.dumps(payload)))
    db.execute("INSERT INTO events VALUES (?,?)", (1, json.dumps({"decision": payload})))
    db.execute("INSERT INTO plans VALUES (?,?)", ("plan-1", json.dumps(payload)))
    db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)", (
        "job-1", "demo-couch", "plan-1", "vendor-1", 7200, "PAID", 3, json.dumps(payload),
    ))
    db.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?)", (
        "payment-1", "demo-couch", "job-1", "reservation-1", "submission-1", "verification-1", 7200,
        json.dumps(payload),
    ))
    db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?,?)", (
        "ledger-1", "budget-1", "job-1", "reservation-1", "payment-1", "CONSUME", 7200, 1,
        json.dumps(payload),
    ))
    db.execute("INSERT INTO invocations VALUES (?,?,?,?,?,?,?,?,?,?)", (
        "invocation-1", 1, "SIGNAL_RECEIVED", "signal-1", "demo-couch", "job-1", invocation_status,
        4, 2, json.dumps(payload),
    ))
    db.commit()
    db.close()
    return anchor


def test_relocation_copies_only_known_demo_projections_and_preserves_ledger(tmp_path):
    source, destination = tmp_path / "source.sqlite3", tmp_path / "loop.sqlite3"
    old_lat, old_lon = _source(source)
    before = source.read_bytes()

    result = relocate_demo_sqlite.relocate(source, destination, issue_id="demo-couch", aliases=(), radius_m=50)

    assert source.read_bytes() == before
    assert result["new_location"] == "State St & Madison St (demo)"
    with sqlite3.connect(destination) as db:
        all_text = "\n".join(str(value) for (value,) in db.execute(
            "SELECT location FROM issues UNION ALL SELECT payload FROM signals UNION ALL SELECT payload FROM events"
        ))
        assert "Original demo anchor" not in all_text
        signal = json.loads(db.execute("SELECT payload FROM signals").fetchone()[0])
        dispatch, checkin = signal["dispatch_location"], signal["checkin_location"]
        assert dispatch == {"lat": 41.88206, "lon": -87.6278}
        assert relocate_demo_sqlite._distance_m(old_lat, old_lon, old_lat + 0.00008, old_lon) == pytest.approx(
            relocate_demo_sqlite._distance_m(dispatch["lat"], dispatch["lon"], checkin["lat"], checkin["lon"])
        )
        assert db.execute("SELECT count(*) FROM ledger WHERE amount_cents=7200 AND kind='CONSUME'").fetchone()[0] == 1
        assert db.execute("SELECT status FROM jobs").fetchone()[0] == "PAID"
        assert db.execute("SELECT status FROM invocations").fetchone()[0] == "COMPLETED"
        assert db.execute("SELECT evidence_score FROM issues").fetchone()[0] == 100


def test_relocation_refuses_active_work_without_creating_destination(tmp_path):
    source, destination = tmp_path / "source.sqlite3", tmp_path / "loop.sqlite3"
    _source(source, invocation_status="PENDING")

    with pytest.raises(ValueError, match="active invocation"):
        relocate_demo_sqlite.relocate(source, destination, issue_id="demo-couch", aliases=(), radius_m=50)

    assert not destination.exists()


def test_relocation_replaces_the_longest_overlapping_caller_alias_first():
    relocate = relocate_demo_sqlite._relocator(
        "Original demo anchor",
        ("Original demo anchor, Previous district",),
        41.70001,
        -87.60001,
        50,
    )

    relocated, changed = relocate("Crew dispatched to Original demo anchor, Previous district.")

    assert changed is True
    assert relocated == "Crew dispatched to State St & Madison St (demo)."


def test_relocation_closes_the_copy_before_cleaning_a_failed_destination(tmp_path, monkeypatch):
    source, destination = tmp_path / "source.sqlite3", tmp_path / "loop.sqlite3"
    _source(source)
    monkeypatch.setattr(relocate_demo_sqlite, "_migrate_copy", lambda *_: (_ for _ in ()).throw(ValueError("stop")))

    with pytest.raises(ValueError, match="stop"):
        relocate_demo_sqlite.relocate(source, destination, issue_id="demo-couch", aliases=(), radius_m=50)

    assert not destination.exists()
    assert source.exists()
