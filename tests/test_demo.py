"""B13 driver dialogue tests: a strict API-shaped transport, no providers."""

from __future__ import annotations

import httpx
import pytest

from agent import demo
from agent.demo import Artifact, DemoDriver, DriverFailure, compare_successful_runs


def _event(kind, *, outcome=None, submission=None, score=None, signal=None):
    return {"id": 1, "occurred_at": "2026-09-13T00:00:00Z", "type": kind,
            "actor_label": "Steward", "actor_type": "service", "outcome": outcome,
            "entity_ids": {"submission_id": submission, "signal_id": signal}, "evidence_score": score}


class Dialogue:
    """Minimal strict HTTP server for the full crew-to-resolution sequence."""

    def __init__(self):
        self.calls = []
        self.full_main = False
        self.timeline = [_event("SETTLEMENT_DENIED", outcome="DENIED", submission="sub-1"),
                         _event("SIMULATED_SETTLEMENT", outcome="OK", submission="sub-2"),
                         _event("ISSUE_RESOLVED", outcome="OK", submission="sub-2"),
                         _event("SIGNAL_LINKED", score=85, signal="resident-2")]
        for index, event in enumerate(self.timeline, start=1):
            event["id"] = index

    @staticmethod
    def _detail(stage):
        job = {"id": "job", "vendor_id": "vendor", "state_revision": 4, "quote_cents": 7200,
               "reservation_id": "reserve", "status": "REWORK_REQUIRED" if stage == "rework" else "PAID"}
        plan = {"quote_cents": 7200, "dispatch_location": {"lat": 41.86, "lon": -87.63, "accuracy_m": 10}}
        history = ([{"submission_id": "sub-1", "accepted": False, "total": 90, "before_evidence_id": "before", "after_evidence_id": "partial", "verification_id": "verification-1", "findings": {"area_clear": False}},
                    {"submission_id": "sub-2", "accepted": True, "total": 100, "before_evidence_id": "before", "after_evidence_id": "after", "verification_id": "verification-2", "findings": {"area_clear": True}}]
                   if stage == "final" else [{"submission_id": "sub-1", "accepted": False, "total": 90, "before_evidence_id": "before", "after_evidence_id": "partial", "verification_id": None, "findings": None}])
        return {"issue": {"status": "RESOLVED" if stage == "final" else "RESOLUTION_ACTIVE"},
                "current": {"job": job, "plan": plan, "payment": {"amount_cents": 7200} if stage == "final" else None},
                "evidence": {"history": {"items": history}, "accepted_submission_id": "sub-2"}}

    def __call__(self, request):
        self.calls.append(request)
        path, method = request.url.path, request.method
        human = path == "/api/demo/persona" or method == "POST"
        if human:
            assert "authorization" not in request.headers
            assert request.headers.get("origin") == "http://steward.test"
            if path != "/api/demo/persona":
                assert "session=demo" in request.headers.get("cookie", "")
        else:
            assert request.headers.get("authorization") == "Bearer service-token"
            assert "cookie" not in request.headers
        if path == "/api/demo/persona":
            return httpx.Response(200, json={"data": {}}, headers={"set-cookie": "session=demo; Path=/"})
        if path.startswith("/api/issues/") and path.endswith("/events"):
            return httpx.Response(200, json={"data": {"events": self.timeline}})
        if path.startswith("/api/issues/"):
            seeded = any(call.url.path == "/api/signals" and call.method == "POST" for call in self.calls)
            monitored = any(call.url.path == "/api/invocations/inv-seed" for call in self.calls)
            if not seeded and self.full_main:
                data = {"issue": {"evidence_score": 65}, "current": {"job": None},
                        "sources": {"items": [{"id": "seed"}]},
                        "latest_decision": {"decision_type": "MONITOR"} if monitored else None}
            elif not any(call.url.path.endswith("/proof") for call in self.calls):
                data = self._detail("denial")
                data.update({"issue": {"evidence_score": 100}, "facts": {"official_conflict_state": "disputed", "official_completed_at": "2026-09-12T00:00:00Z"}, "sources": {"items": [{"id": "seed"}]}})
            else:
                stage = "final" if any(call.url.path == "/api/jobs/job/proofs/sub-2/receipt" for call in self.calls) else (
                    "rework" if any(call.url.path == "/api/exceptions/ex/request-completion" for call in self.calls) else "denial")
                data = self._detail(stage)
            return httpx.Response(200, json={"data": data})
        if path.startswith("/api/signals/") and path.endswith("/receipt"):
            inv = "inv-seed" if path.endswith("/seed/receipt") else "inv-two"
            return httpx.Response(200, json={"data": {"signal_id": path.split("/")[3], "invocation_id": inv}})
        if path == "/api/jobs/job":
            if any(call.url.path == "/api/exceptions/ex/request-completion" for call in self.calls):
                body = {"id": "job", "status": "REWORK_REQUIRED", "state_revision": 4, "price_cents": 7200, "reservation_id": "reserve"}
            elif any(call.url.path.endswith("/check-in") for call in self.calls):
                body = {"id": "job", "status": "CHECKED_IN", "state_revision": 3, "price_cents": 7200,
                        "reservation_id": "reserve", "accepted_at": "2026-09-13T00:00:00Z", "checked_in_at": "2026-09-13T00:01:00Z",
                        "dispatch_location": {"lat": 41.86, "lon": -87.63, "accuracy_m": 10}}
            else:
                body = {"id": "job", "status": "ASSIGNED", "state_revision": 2, "price_cents": 7200, "reservation_id": "reserve"}
            return httpx.Response(200, json={"data": body})
        if path == "/api/exceptions":
            return httpx.Response(200, json={"data": {"exceptions": [{"id": "ex", "job_id": "job", "submission_id": "sub-1", "total": 90, "status": "PENDING", "state_revision": 1, "job_revision": 4}]}})
        if path.startswith("/api/jobs/job/proofs/"):
            sub = path.split("/")[-2]
            return httpx.Response(200, json={"data": {"submission_id": sub, "job_id": "job", "invocation_id": f"inv-{sub}", "processing": "COMPLETED"}})
        if path.startswith("/api/invocations/"):
            status = "WAITING" if path.endswith("inv-seed") else "COMPLETED"
            return httpx.Response(200, json={"data": {"status": status, "next_cursor": None, "trace": []}})
        if path == "/api/board":
            return httpx.Response(200, json={"data": {"markers": [{"issue_id": "issue", "marker_state": "resolved"}, {"issue_id": "demo-couch", "marker_state": "resolved"}], "budget": {"spent_cents": 7200, "reserved_cents": 0}}})
        if method == "POST" and path.endswith("/proof"):
            sub = "sub-2" if any(call.url.path == "/api/exceptions/ex/request-completion" for call in self.calls) else "sub-1"
            return httpx.Response(202, json={"data": {"record_id": sub}})
        if method == "POST" and path == "/api/exceptions/ex/request-completion":
            return httpx.Response(202, json={"data": {"invocation_id": "inv-operator"}})
        if method == "POST" and path == "/api/signals":
            return httpx.Response(202, json={"data": {"signal_id": "resident-2"}})
        if method == "POST" and path.endswith(("/accept", "/check-in")):
            return httpx.Response(200, json={"data": {"record_id": "ok"}})
        raise AssertionError(f"unexpected request {method} {path}")


def test_full_http_dialogue_asserts_actual_denial_rework_payment_and_close(tmp_path):
    driver = DemoDriver("http://steward.test", service_token="service-token", artifact=Artifact(),
                        transport=httpx.MockTransport(Dialogue()))
    before, partial, after = (tmp_path / name for name in ("before.jpg", "partial.jpg", "after.jpg"))
    for image in (before, partial, after):
        image.write_bytes(b"image")
    try:
        baseline, first = driver.run_first_human_boundary(issue_id="issue", before=before, partial=partial)
        driver.wait_for_terminal(driver.proof_invocation(baseline["id"], first), seconds=1)
        driver.finish_happy_path(issue_id="issue", baseline=baseline, first_submission=first, after=after, seconds=1)
        driver.assert_signal_score("issue", "resident-2", 85)
        assert all(driver.artifact.criteria[f"criterion-{i}"]["passed"] is True
                   for i in (3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15))
    finally:
        driver.close()


def test_main_drives_first_run_over_strict_http_and_leaves_repeat_pending(tmp_path, monkeypatch):
    dialogue = Dialogue()
    dialogue.full_main = True
    original = demo.DemoDriver
    monkeypatch.setenv("STEWARD_SERVICE_TOKEN", "service-token")
    monkeypatch.setattr(demo, "DemoDriver", lambda *args, **kwargs: original(*args, **kwargs,
                        transport=httpx.MockTransport(dialogue)))
    out = tmp_path / "first.json"
    assert demo.main(["--base-url", "http://steward.test", "--out", str(out), "--wait-seconds", "1"]) == 0, out.read_text(encoding="utf-8")
    artifact = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert all(artifact["criteria"][f"criterion-{i}"]["passed"] is True for i in range(1, 16))
    assert artifact["criteria"]["criterion-16"]["status"] == "PENDING_SECOND_RUN"


@pytest.mark.parametrize("event", [[], [_event("SIGNAL_LINKED", score=100, signal="resident-2")]])
def test_driver_rejects_missing_or_wrong_historical_85(event):
    dialogue = Dialogue()
    dialogue.timeline = event
    driver = DemoDriver("http://steward.test", service_token="service-token", artifact=Artifact(),
                        transport=httpx.MockTransport(dialogue))
    try:
        with pytest.raises(DriverFailure):
            driver.assert_signal_score("issue", "resident-2", 85)
    finally:
        driver.close()


def test_repeat_comparison_requires_two_real_successful_artifacts():
    successful = {"origin": "http://steward.test", "fixture_scenario": "baseline", "finished_at": "done",
                  "run_id": "one", "criteria": {f"criterion-{i}": {"passed": True} for i in range(1, 16)},
                  "steps": [{"name": "detail-final", "body": {"data": {"issue": {"status": "RESOLVED"}, "current": {"job": {"status": "PAID"}, "payment": {"amount_cents": 7200}}, "evidence": {"accepted_submission_id": "sub"}}}}, {"name": "board-final", "body": {"data": {"budget": {"spent_cents": 7200, "reserved_cents": 0}}}}]}
    second = {**successful, "run_id": "two"}
    compare_successful_runs(successful, second)
    incomplete = {**successful, "criteria": {**successful["criteria"], "criterion-10": {"passed": False}}}
    with pytest.raises(DriverFailure):
        compare_successful_runs(successful, incomplete)
