from __future__ import annotations

import sqlite3
import sys

import pytest

from agent.seed import main
from agent.store import Store


def run_seed(monkeypatch, path, *extra):
    monkeypatch.setattr(sys, "argv", ["seed", "--db", str(path), *extra])
    return main()


def test_seed_creates_watch_state_and_stages_second_report(tmp_path, monkeypatch, capsys):
    path = tmp_path / "demo.sqlite3"
    assert run_seed(monkeypatch, path) == 0
    output = capsys.readouterr().out
    assert "OFFLINE DEMO SEED" in output and "staged_second_report" in output
    with Store(path) as store:
        issue = store.get_issue("demo-couch")
        assert issue["evidence_score"] == 65
        assert len(store.signal_receipts_for_actor("steward-service")) == 1
        assert store.seed_receipt().seed_version
        assert store.get_budget("south_loop_demo").initial_cents == 50000


def test_seed_refuses_existing_or_foreign_reset_and_replaces_only_marked_demo(tmp_path, monkeypatch):
    path = tmp_path / "demo.sqlite3"
    run_seed(monkeypatch, path)
    original = path.read_bytes()
    with pytest.raises(SystemExit):
        run_seed(monkeypatch, path)
    assert path.read_bytes() == original
    foreign = tmp_path / "foreign.sqlite3"
    foreign.write_bytes(b"not a database")
    with pytest.raises(SystemExit):
        run_seed(monkeypatch, foreign, "--reset")
    assert foreign.read_bytes() == b"not a database"
    assert run_seed(monkeypatch, path, "--reset") == 0


@pytest.mark.parametrize("kind", ["empty", "current", "unrelated"])
def test_reset_marker_check_is_read_only_for_foreign_sqlite(tmp_path, monkeypatch, kind):
    path = tmp_path / f"{kind}.sqlite3"
    if kind == "current":
        with Store(path):
            pass
    elif kind == "unrelated":
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE keep(value TEXT)")
            db.execute("INSERT INTO keep VALUES ('unchanged')")
    else:
        with sqlite3.connect(path):
            pass
    before = path.read_bytes()
    with pytest.raises(SystemExit):
        run_seed(monkeypatch, path, "--reset")
    assert path.read_bytes() == before


def test_seed_refuses_path_outside_configured_demo_root(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    monkeypatch.setenv("STEWARD_DEMO_ROOT", str(root))
    with pytest.raises(SystemExit):
        run_seed(monkeypatch, tmp_path / "outside.sqlite3")
