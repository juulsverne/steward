"""Execute deployment scripts with exported, fail-closed AWS/npm shell fakes."""
import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")
BASH = (Path(GIT).parent.parent / "bin/bash.exe") if os.name == "nt" else shutil.which("bash")
pytestmark = pytest.mark.skipif(not BASH or not Path(BASH).exists(), reason="Bash required")


def run_script(tmp_path, script, *args, extra="", **overrides):
    env = os.environ.copy()
    env.update({"CALL_LOG": str(tmp_path / "calls"), "FAKE_STATUS": "Success",
                "FAKE_BACKUP": str(tmp_path / "backup"), **overrides})
    harness = r'''
set -e
aws() {
  echo "$*" >> "$CALL_LOG"
  case "$1 $2" in
    "ssm send-command") echo command-123 ;;
    "ssm wait") [ "$FAKE_STATUS" = Success ] ;;
    "ssm get-command-invocation")
      if [[ "$*" == *StandardOutputContent* ]]; then
        echo 'steward-backup: uploaded s3://steward-hackathon-589354718907/backups/20260914T211310Z/'
      else echo "$FAKE_STATUS"; fi ;;
    "s3 cp")
      local previous='' arg
      for arg in "$@"; do
        if [[ "$previous" == s3://*/backups/* ]]; then
          cp "$FAKE_BACKUP/${previous##*/}" "$arg"
          return
        fi
        previous="$arg"
      done
      ;;
    "s3 ls") : ;;
    "ec2 terminate-instances") return 93 ;;
    *) echo "blocked unexpected AWS call: $*" >&2; return 94 ;;
  esac
}
npm() {
  echo "npm $*" >> "$CALL_LOG"
  if [ "${FAIL_BUILD:-}" = 1 ]; then return 95; fi
  if [ "$1" = run ]; then mkdir -p dist; cp source.txt dist/index.html; fi
}
sleep() { :; }
export -f aws npm sleep
'''
    result = subprocess.run(
        [str(BASH), "--noprofile", "--norc", "-c", harness + extra + '\nsource "$@"',
         str(script), str(script), *args], cwd=tmp_path, env=env,
        text=True, capture_output=True, timeout=40, check=False,
    )
    log = tmp_path / "calls"
    return result, log.read_text() if log.exists() else ""


def fixture_repo(tmp_path):
    (tmp_path / "frontend").mkdir()
    for name, text in {"source.txt": "selected frontend", "package.json": "{}",
                       "package-lock.json": "{}"}.items():
        (tmp_path / "frontend" / name).write_text(text)
    shutil.copytree(ROOT / "deploy", tmp_path / "deploy")
    (tmp_path / "deploy/selected.txt").write_text("selected deploy")
    def git(*args):
        return subprocess.check_output([GIT, *args], cwd=tmp_path, text=True).strip()
    git("init", "-q")
    git("add", "frontend", "deploy")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "selected revision")
    commit = git("rev-parse", "HEAD")
    (tmp_path / "frontend/source.txt").write_text("dirty frontend")
    (tmp_path / "frontend/dist").mkdir()
    (tmp_path / "frontend/dist/index.html").write_text("stale build")
    (tmp_path / "deploy/selected.txt").write_text("dirty deploy")
    return commit


def test_artifacts_build_selected_revision_and_create_output(tmp_path):
    commit = fixture_repo(tmp_path)
    out = tmp_path / "new/nested/artifacts"
    result, log = run_script(tmp_path, ROOT / "deploy/build-artifact.sh", commit, "test-bucket",
                             ARTIFACT_OUT=str(out))
    assert result.returncode == 0, result.stderr
    with tarfile.open(out / f"frontend-dist-{commit}.tar.gz") as archive:
        assert archive.extractfile("frontend/dist/index.html").read() == b"selected frontend"
    with tarfile.open(out / f"deploy-bundle-{commit}.tar.gz") as archive:
        assert archive.extractfile("deploy/selected.txt").read() == b"selected deploy"
    assert "npm ci" in log and "npm run build" in log


def test_provision_build_failure_precedes_any_aws_call(tmp_path):
    commit = fixture_repo(tmp_path)
    result, log = run_script(tmp_path, tmp_path / "deploy/provision.sh",
                             COMMIT=commit, FAIL_BUILD="1")
    assert result.returncode != 0
    assert "npm ci" in log, result.stderr
    assert all(line.startswith("npm ") for line in log.splitlines()), log


def make_backup(tmp_path, *, corrupt=False, malformed=False):
    backup = tmp_path / "backup"
    backup.mkdir()
    stamp = "20260914T211310Z"
    lines = []
    for name in [f"steward-{stamp}.sqlite3", f"images-{stamp}.tar.gz"]:
        content = name.encode()
        (backup / name).write_bytes(content)
        lines.append(f"{hashlib.sha256(content).hexdigest()}  ./{name}\n")
    if malformed:
        lines.pop()
    (backup / f"manifest-{stamp}.sha256").write_bytes("".join(lines).encode())
    if corrupt:
        (backup / f"steward-{stamp}.sqlite3").write_bytes(b"damaged")


@pytest.mark.parametrize("status", ["Failed", "InProgress", "TimedOut", "Cancelled"])
def test_teardown_never_deletes_after_unsuccessful_backup(tmp_path, status):
    make_backup(tmp_path)
    result, log = run_script(tmp_path, ROOT / "deploy/teardown.sh", "destroy", FAKE_STATUS=status)
    assert result.returncode != 0
    assert "terminate-instances" not in log, log
    assert "delete-volume" not in log


@pytest.mark.parametrize("failure", ["corrupt", "malformed", "missing"])
def test_teardown_requires_exact_downloaded_backup(tmp_path, failure):
    make_backup(tmp_path, corrupt=failure == "corrupt", malformed=failure == "malformed")
    if failure == "missing":
        (tmp_path / "backup/images-20260914T211310Z.tar.gz").unlink()
    result, log = run_script(tmp_path, ROOT / "deploy/teardown.sh", "destroy")
    assert result.returncode != 0
    assert "terminate-instances" not in log, log


def test_teardown_reaches_termination_only_after_verified_backup(tmp_path):
    make_backup(tmp_path)
    result, log = run_script(tmp_path, ROOT / "deploy/teardown.sh", "destroy")
    # The fake halts at the first destructive command, never reaching real AWS.
    assert result.returncode == 93, result.stderr
    assert "ssm wait command-executed" in log
    assert log.count("s3 cp") == 3
    assert "--parameters" in log and "systemctl stop steward" in log
    assert "steward-20260914T211310Z.sqlite3: OK" in result.stdout
