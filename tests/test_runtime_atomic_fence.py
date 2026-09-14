"""Independent proof: a lease expiring after receipt insertion rolls back the writer."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from agent.api import create_app
from agent.config import ApiSettings
from agent.coordinator import Coordinator
from agent.runtime_contracts import command_record
from agent.seed import _seed
from agent.store import Store, StoreTransaction
from agent.tools.protocol import build_command


@pytest.mark.asyncio
async def test_commit_boundary_rechecks_lease_after_effect_and_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "atomic-fence.sqlite3"
    _seed(path, Path("data"))
    clock = [datetime.now(UTC)]
    origin = "http://127.0.0.1:8134"
    token = hashlib.sha256(b"independent-runtime-service-fixture").hexdigest()
    signing = hashlib.sha256(b"independent-runtime-session-fixture").hexdigest()
    with Store(path) as store:
        invocation = store.pending_invocations()[0]
        revision = store.get_issue_record("demo-couch").state_revision
        command = build_command("geocode_location", {
            "issue_id": "demo-couch", "signal_id": invocation.signal_id,
            "expected_issue_revision": revision,
        })
        coordinator = Coordinator(store, clock=lambda: clock[0])
        claim = coordinator.claim(invocation.id, "root-owner", "root-claim")
        coordinator.execution(claim, f"authorize-{claim.fence}-model-1", "model", 1)
        coordinator.execution(claim, f"authorize-{claim.fence}-tool-1", "tool", 1,
            details={"command": command_record(command).model_dump(mode="json")})
        prepared = coordinator.prepare(claim, "model-1-tool-1", command)
        attempt = coordinator.begin(claim, prepared.id, "root-attempt")
        before = {table: store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("request_receipts", "events", "geocode_facts")}

    original_save = StoreTransaction.save_request
    reached_receipt = []

    def expire_after_save(tx, receipt):
        result = original_save(tx, receipt)
        if receipt.invocation_id == invocation.id:
            reached_receipt.append(receipt.id)
            clock[0] += timedelta(seconds=35)
        return result

    monkeypatch.setattr(StoreTransaction, "save_request", expire_after_save)
    app = create_app(ApiSettings(store_path=path, origin=origin, local_http=True,
        session_secret=signing, service_token=token), runtime_clock=lambda: clock[0])
    headers = {
        "Authorization": f"Bearer {token}", "X-Steward-Invocation-Id": invocation.id,
        "X-Steward-Attempt-Id": attempt.id, "X-Steward-Lease-Owner": claim.owner,
        "X-Steward-Fencing-Token": str(claim.fence),
        "X-Steward-Expected-Revision": str(command.expected_revision),
        "Idempotency-Key": prepared.idempotency_key,
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=origin) as client:
        response = await client.post(command.path, headers=headers, json=json.loads(command.body_json))
    assert reached_receipt, response.text
    with Store(path) as store:
        after = {table: store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in before}
        assert after == before
        assert store.get_issue_record("demo-couch").state_revision == revision
        assert store.db.execute("SELECT COUNT(*) FROM request_receipts WHERE idempotency_key=?",
                                (prepared.idempotency_key,)).fetchone()[0] == 0
    assert response.status_code == 409, response.text
    assert response.json()["reason_code"] == "DEADLINE_EXCEEDED", response.text
