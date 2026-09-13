import sys

import pytest

from agent.foundation import main
from agent.store import Store


def test_foundation_command_persists_real_state_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    path = tmp_path / "foundation.sqlite3"
    monkeypatch.setattr(sys, "argv", ["foundation", "--db", str(path)])
    assert main() == 0
    assert "OFFLINE FOUNDATION CHECK" in capsys.readouterr().out
    with Store(path) as store:
        assert store.get_issue("demo-couch")["evidence_score"] == 85
        assert len(store.events("demo-couch")) == 4
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
