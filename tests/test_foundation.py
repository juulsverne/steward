import sys

import pytest

from agent.foundation import main
from agent.store import Store


def test_foundation_command_persists_real_state_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    path = tmp_path / "foundation.sqlite3"
    monkeypatch.setattr(sys, "argv", ["foundation", "--db", str(path)])
    assert main() == 0
    out = capsys.readouterr().out
    assert "OFFLINE FOUNDATION CHECK" in out
    assert '"phase": "completed_record_pending"' in out
    with Store(path) as store:
        issue = store.get_issue("demo-couch")
        assert issue["evidence_score"] == 100
        assert issue["service_record"]["conflict"] == "disputed"
        assert [e["event_type"] for e in store.events("demo-couch")] == [
            "ISSUE_CREATED", "GEOCODE_RECORDED", "SIGNAL_LINKED", "SERVICE_MATCH_RECORDED",
            "SIGNAL_LINKED", "OFFICIAL_STATUS_DISPUTED",
        ]
    original = path.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert path.read_bytes() == original


def test_foundation_refuses_any_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "precious.txt"
    path.write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["foundation", "--db", str(path)])
    with pytest.raises(SystemExit):
        main()
    assert path.read_text(encoding="utf-8") == "keep me"
