"""External HTTP acceptance driver for the Steward API.

This module never imports Store or domain operations.  It records returned API state
and refuses to substitute a human/model choice with a local mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv


class DriverFailure(RuntimeError):
    pass


@dataclass
class Artifact:
    schema_version: str = "b13-http-acceptance-v1"
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    origin: str = ""
    fixture_scenario: str = "baseline"
    run_id: str = field(default_factory=lambda: uuid4().hex)
    steps: list[dict] = field(default_factory=list)
    invocations: dict[str, dict] = field(default_factory=dict)
    criteria: dict[str, dict] = field(default_factory=dict)
    finished_at: str | None = None

    def record(self, name: str, response: httpx.Response, *, assertion: str | None = None) -> dict:
        try:
            body = response.json()
        except ValueError:
            body = {"non_json": True}
        request = response.request
        request_meta = {"method": request.method, "path": request.url.path}
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                request_meta["json"] = _safe(json.loads(request.content))
            except (ValueError, TypeError):
                request_meta["json"] = "invalid_json"
        item = {"name": name, "status_code": response.status_code, "request_id": response.headers.get("X-Request-ID"),
                "request": request_meta,
                "body": _safe(body), "assertion": assertion, "at": datetime.now(UTC).isoformat()}
        self.steps.append(item)
        return body


def _safe(value):
    """Keep useful API receipts while refusing credential/reasoning-shaped fields."""
    blocked = {"authorization", "cookie", "token", "secret", "api_key", "chain_of_thought", "reasoning"}
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items() if key.lower() not in blocked}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return value


class DemoDriver:
    def __init__(self, base_url: str, *, service_token: str, artifact: Artifact, timeout: float = 20.0,
                 transport: httpx.BaseTransport | None = None):
        self.artifact, self.origin = artifact, base_url.rstrip("/")
        self.artifact.origin = self.origin
        self.service_headers = {"Authorization": f"Bearer {service_token}"}
        self.service_client = httpx.Client(base_url=self.origin, trust_env=False, follow_redirects=False,
                                           timeout=timeout, transport=transport)
        self.human_client = httpx.Client(base_url=self.origin, trust_env=False, follow_redirects=False,
                                         timeout=timeout, transport=transport)

    def close(self):
        self.service_client.close()
        self.human_client.close()

    def service_get(self, name: str, path: str, **kwargs) -> dict:
        response = self.service_client.get(path, headers=self.service_headers, **kwargs)
        body = self.artifact.record(name, response)
        if response.status_code != 200:
            raise DriverFailure(f"{name} returned HTTP {response.status_code}")
        return body

    def select_persona(self, persona_id: str):
        response = self.human_client.post("/api/demo/persona", headers={"Origin": self.origin, "X-Steward-Request": "1",
                                    "Idempotency-Key": f"persona-{uuid4().hex}"}, json={"persona_id": persona_id})
        self.artifact.record(f"select:{persona_id}", response)
        if response.status_code != 200:
            raise DriverFailure(f"cannot select {persona_id}")

    def human_post(self, name: str, path: str, *, revision: int, json_body=None, files=None) -> dict:
        response = self.human_client.post(path, headers={"Origin": self.origin, "X-Steward-Request": "1",
            "Idempotency-Key": f"demo-{name}-{uuid4().hex}", "X-Steward-Expected-Revision": str(revision)},
            json=json_body, files=files)
        body = self.artifact.record(name, response)
        if response.status_code not in {200, 201, 202}:
            raise DriverFailure(f"{name} returned HTTP {response.status_code}")
        return body

    def submit_resident(self, report: dict) -> dict:
        self.select_persona("resident-2")
        response = self.human_client.post("/api/signals", headers={"Origin": self.origin, "X-Steward-Request": "1",
            "Idempotency-Key": f"demo-resident-two-{uuid4().hex}"}, files={
                "description": (None, report["raw_text"]), "location": (None, report["reported_location"]),
                "observed_at": (None, report["observed_at"]),
            })
        body = self.artifact.record("resident-two-corroboration", response)
        if response.status_code != 202:
            raise DriverFailure("independent resident report was not accepted")
        return body["data"]

    def assert_step(self, name: str, condition: bool, detail: str):
        item = {"assertion": detail, "passed": condition, "at": datetime.now(UTC).isoformat()}
        self.artifact.criteria[name] = item
        self.artifact.steps.append({"name": name, **item})
        if not condition:
            raise DriverFailure(f"assertion failed: {name}: {detail}")

    def record_pending(self, name: str, detail: str):
        item = {"assertion": detail, "passed": None, "status": "PENDING_SECOND_RUN",
                "at": datetime.now(UTC).isoformat()}
        self.artifact.criteria[name] = item
        self.artifact.steps.append({"name": name, **item})

    def wait_for_terminal(self, invocation_id: str, *, seconds: float = 180.0) -> dict:
        deadline, after = time.monotonic() + seconds, 0
        last = None
        while time.monotonic() < deadline:
            status = self.service_get(f"status:{invocation_id}:{after}", f"/api/invocations/{invocation_id}",
                                      params={"after_id": after})["data"]
            self._save_invocation(invocation_id, status)
            last = status
            while status.get("next_cursor") is not None:
                after = status["next_cursor"]
                status = self.service_get(f"trace:{invocation_id}:{after}", f"/api/invocations/{invocation_id}",
                                          params={"after_id": after})["data"]
                self._save_invocation(invocation_id, status)
            if status["status"] in {"WAITING", "COMPLETED", "ERROR"}:
                if status["status"] == "ERROR":
                    raise DriverFailure(f"invocation {invocation_id} ended ERROR: {status.get('error_code')}")
                return status
            time.sleep(1)
        raise DriverFailure(f"invocation {invocation_id} timed out; last={last and last.get('status')}")

    def _save_invocation(self, invocation_id: str, status: dict) -> None:
        """Retain every bounded safe trace page rather than only the final cursor page."""
        previous = self.artifact.invocations.get(invocation_id, {})
        trace = [*previous.get("trace", ())]
        seen = {item.get("id") for item in trace if isinstance(item, dict) and item.get("id") is not None}
        for item in status.get("trace", ()):
            if not isinstance(item, dict) or item.get("id") is None or item["id"] not in seen:
                trace.append(item)
                if isinstance(item, dict) and item.get("id") is not None:
                    seen.add(item["id"])
        self.artifact.invocations[invocation_id] = {**status, "trace": _safe(trace)}

    def wait_for_exception(self, job_id: str, submission_id: str, *, seconds: float = 180.0) -> dict:
        """Await the saved policy effect after the proof receipt invocation completes."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            items = self.service_get("completion-inbox-poll", "/api/exceptions")["data"]["exceptions"]
            found = next((item for item in items if item["job_id"] == job_id and item["submission_id"] == submission_id), None)
            if found is not None:
                return found
            time.sleep(1)
        raise DriverFailure("proof receipt omitted invocation ID and no saved completion exception appeared")

    def timeline(self, issue_id: str) -> list[dict]:
        cursor, events, seen = None, [], set()
        while True:
            params = {"limit": 50}
            if cursor:
                params["cursor"] = cursor
            page = self.service_get("issue-timeline", f"/api/issues/{issue_id}/events", params=params)["data"]
            for event in page["events"]:
                if event["id"] not in seen:
                    events.append(event)
                    seen.add(event["id"])
            cursor = page.get("next_cursor")
            if cursor is None:
                return events

    def assert_event(self, issue_id: str, event_type: str, *, outcome: str | None = None,
                     submission_id: str | None = None) -> dict:
        event = next((item for item in self.timeline(issue_id) if item["type"] == event_type
                      and (outcome is None or item.get("outcome") == outcome)
                      and (submission_id is None or item["entity_ids"].get("submission_id") == submission_id)), None)
        if event is None:
            raise DriverFailure(f"missing saved event {event_type}")
        return event

    def assert_signal_score(self, issue_id: str, signal_id: str, total: int) -> None:
        event = next((item for item in self.timeline(issue_id) if item["type"] == "SIGNAL_LINKED"
                      and item["entity_ids"].get("signal_id") == signal_id
                      and item.get("evidence_score") == total), None)
        self.assert_step("criterion-3", event is not None,
                         f"saved SIGNAL_LINKED event for {signal_id} projects exact evidence score {total}")

    def run_first_human_boundary(self, *, issue_id: str, before: Path, partial: Path) -> tuple[dict, str]:
        """Perform only crew proof actions after the agent has saved a dispatch.

        The caller must first wait for agent decisions and verify the returned job.
        """
        detail = self.service_get("detail-before-crew", f"/api/issues/{issue_id}")["data"]
        job, plan = detail["current"]["job"], detail["current"]["plan"]
        if job is None or plan is None:
            raise DriverFailure("agent has not saved a dispatch; driver will not choose one")
        self.assert_step("criterion-6", plan["quote_cents"] == 7200, "saved scoped plan has 7200-cent quote")
        self.assert_step("criterion-7", job["reservation_id"] is not None and job["quote_cents"] == 7200,
                         "agent selected an eligible saved vendor with one reservation")
        self.select_persona(f"crew-{job['vendor_id']}")
        self.human_post("crew-accept", f"/api/jobs/{job['id']}/accept", revision=job["state_revision"])
        job = self.service_get("job-after-accept", f"/api/jobs/{job['id']}")["data"]
        point = plan["dispatch_location"]
        self.human_post("crew-check-in", f"/api/jobs/{job['id']}/check-in", revision=job["state_revision"],
                        json_body={"latitude": point["lat"], "longitude": point["lon"], "accuracy_m": point.get("accuracy_m")})
        job = self.service_get("job-after-check-in", f"/api/jobs/{job['id']}")["data"]
        self.assert_step("criterion-8", job["status"] == "CHECKED_IN" and job.get("accepted_at") is not None
                         and job.get("checked_in_at") is not None and job.get("dispatch_location") == point,
                         "saved crew acceptance and plan-location GPS check-in reached CHECKED_IN")
        files = {"metadata": (None, json.dumps({"before_observed_at": "2026-09-12T13:55:00Z", "after_observed_at": "2026-09-13T00:00:00Z"})), "before": (before.name, before.read_bytes(), "image/jpeg"),
                 "after": (partial.name, partial.read_bytes(), "image/jpeg")}
        proof = self.human_post("crew-first-proof", f"/api/jobs/{job['id']}/proof", revision=job["state_revision"], files=files)
        submission_id = proof["data"]["record_id"]
        proof_detail = self.service_get("detail-after-first-proof", f"/api/issues/{issue_id}")["data"]
        first = next((item for item in proof_detail["evidence"]["history"]["items"] if item["submission_id"] == submission_id), None)
        self.assert_step("criterion-9", first is not None and first.get("before_evidence_id") is not None
                         and first.get("after_evidence_id") is not None and first.get("verification_id") is None,
                         "first proof saved distinct before/partial-after evidence and awaits its receipt invocation")
        return {"id": job["id"], "reservation_id": job["reservation_id"], "price_cents": job["price_cents"],
                "before_evidence_id": first["before_evidence_id"]}, submission_id

    def proof_invocation(self, job_id: str, submission_id: str) -> str:
        receipt = self.service_get("proof-receipt", f"/api/jobs/{job_id}/proofs/{submission_id}/receipt")["data"]
        if not receipt.get("invocation_id"):
            raise DriverFailure("proof receipt lacks its saved invocation")
        return receipt["invocation_id"]

    def finish_happy_path(self, *, issue_id: str, baseline: dict, first_submission: str, after: Path,
                           seconds: float = 180.0) -> None:
        """Complete the human/operator boundaries only after saved agent effects appear."""
        job_id = baseline["id"]
        exception = self.wait_for_exception(job_id, first_submission, seconds=seconds)
        detail = self.service_get("detail-after-denial", f"/api/issues/{issue_id}")["data"]
        history = next((item for item in detail["evidence"]["history"]["items"]
                        if item["submission_id"] == first_submission), None)
        denied = self.assert_event(issue_id, "SETTLEMENT_DENIED", outcome="DENIED", submission_id=first_submission)
        self.assert_step("criterion-10", exception["total"] == 90 and exception["status"] == "PENDING"
                         and history is not None and history["accepted"] is False and history["total"] == 90
                         and detail["current"]["payment"] is None and denied is not None,
                         "actual 90 proof has failed settlement, zero payment, and a pending completion exception")
        self.select_persona("operator")
        choice = self.human_post("operator-request-completion", f"/api/exceptions/{exception['id']}/request-completion",
            revision=exception["state_revision"], json_body={"submission_id": first_submission,
            "expected_job_revision": exception["job_revision"]})
        invocation = choice["data"].get("invocation_id")
        if not invocation:
            raise DriverFailure("operator choice lacks its saved pending invocation")
        self.wait_for_terminal(invocation, seconds=seconds)
        detail_before = self.service_get("detail-before-rework", f"/api/issues/{issue_id}")["data"]
        self.select_persona(f"crew-{detail_before['current']['job']['vendor_id']}")
        job = self.service_get("job-before-rework-proof", f"/api/jobs/{job_id}")["data"]
        if job["status"] != "REWORK_REQUIRED":
            raise DriverFailure("model did not execute saved rework")
        self.assert_step("criterion-11", job["price_cents"] == baseline["price_cents"]
                         and job["reservation_id"] == baseline["reservation_id"],
                         "actual operator invocation reworked the same saved job, quote, and reservation")
        files = {"metadata": (None, json.dumps({"after_observed_at": "2026-09-13T01:00:00Z"})), "after": (after.name, after.read_bytes(), "image/jpeg")}
        proof = self.human_post("crew-rework-proof", f"/api/jobs/{job_id}/proof", revision=job["state_revision"], files=files)
        fresh_submission = proof["data"]["record_id"]
        self.wait_for_terminal(self.proof_invocation(job_id, fresh_submission), seconds=seconds)
        detail = self.service_get("detail-final", f"/api/issues/{issue_id}")["data"]
        if detail["issue"]["status"] != "RESOLVED" or detail["current"]["job"]["status"] != "PAID":
            raise DriverFailure("agent did not save one payment and resolution")
        fresh = next((item for item in detail["evidence"]["history"]["items"] if item["submission_id"] == fresh_submission), None)
        self.assert_step("criterion-12", fresh is not None and fresh["accepted"] is True and fresh["total"] == 100
                         and fresh.get("before_evidence_id") == baseline["before_evidence_id"]
                         and fresh.get("after_evidence_id") is not None and fresh.get("verification_id") is not None
                         and fresh.get("findings") is not None,
                         "fresh after-only proof produced actual 100 accepted verification")
        payment_events = [item for item in self.timeline(issue_id) if item["type"] == "SIMULATED_SETTLEMENT"]
        self.assert_step("criterion-13", detail["current"]["payment"]["amount_cents"] == 7200
                         and len(payment_events) == 1,
                         "exactly one saved simulated 7200-cent payment follows fresh verification")
        self.assert_step("criterion-14", detail["evidence"]["accepted_submission_id"] == proof["data"]["record_id"],
                         "separate resolution accepts fresh proof")
        self.assert_event(issue_id, "ISSUE_RESOLVED")
        board = self.service_get("board-final", "/api/board")["data"]
        marker = next((item for item in board["markers"] if item["issue_id"] == issue_id), None)
        if marker is None or marker["marker_state"] != "resolved":
            raise DriverFailure("board lacks resolved marker")
        self.assert_step("criterion-15", board["budget"]["spent_cents"] == 7200 and board["budget"]["reserved_cents"] == 0,
                         "Board reflects resolved marker and final simulated budget")


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--issue-id", default="demo-couch")
    parser.add_argument("--before", type=Path, default=Path("data/images/before.jpg"))
    parser.add_argument("--partial", type=Path, default=Path("data/images/middle.jpg"))
    parser.add_argument("--after", type=Path, default=Path("data/images/after.jpg"))
    parser.add_argument("--wait-seconds", type=float, default=180.0)
    parser.add_argument("--fixture-scenario", default="baseline")
    parser.add_argument("--compare", type=Path,
                        help="successful artifact from an independently reset second run")
    args = parser.parse_args(argv)
    token = os.getenv("STEWARD_SERVICE_TOKEN")
    if not token:
        parser.error("STEWARD_SERVICE_TOKEN is required privately for status and safe reads")
    artifact = Artifact(origin=args.base_url, fixture_scenario=args.fixture_scenario)
    driver = DemoDriver(args.base_url, service_token=token, artifact=artifact)
    exit_code = 1
    try:
        detail = driver.service_get("initial-detail", f"/api/issues/{args.issue_id}")["data"]
        driver.assert_step("criterion-1", detail["sources"]["items"] != [], "seed signal is linked")
        driver.assert_step("criterion-2", detail["issue"]["evidence_score"] == 65 and detail["current"]["job"] is None,
                           "first invocation begins from 65 with no dispatch")
        source = detail["sources"]["items"][0]
        receipt = driver.service_get("seed-receipt", f"/api/signals/{source['id']}/receipt")["data"]
        if not receipt.get("invocation_id"):
            raise DriverFailure("seed receipt lacks saved invocation")
        initial = driver.wait_for_terminal(receipt["invocation_id"], seconds=args.wait_seconds)
        detail = driver.service_get("detail-after-monitor", f"/api/issues/{args.issue_id}")["data"]
        monitor = detail.get("latest_decision")
        driver.assert_step("criterion-2", initial["status"] == "WAITING"
                           and detail["issue"]["evidence_score"] == 65 and detail["current"]["job"] is None
                           and monitor is not None and monitor["decision_type"] == "MONITOR",
                           "original invocation saved MONITOR at 65, explicitly waits, and made no dispatch")
        report = json.loads(Path("data/signals.json").read_text(encoding="utf-8"))[1]
        second = driver.submit_resident(report)
        second_receipt = driver.service_get("resident-two-receipt", f"/api/signals/{second['signal_id']}/receipt")["data"]
        if not second_receipt.get("invocation_id"):
            raise DriverFailure("resident-two receipt lacks saved invocation")
        driver.wait_for_terminal(second_receipt["invocation_id"], seconds=args.wait_seconds)
        detail = driver.service_get("detail-after-corroboration", f"/api/issues/{args.issue_id}")["data"]
        driver.assert_signal_score(args.issue_id, second["signal_id"], 85)
        driver.assert_step("criterion-4", detail["facts"]["official_conflict_state"] == "disputed" and detail["issue"]["evidence_score"] == 100,
                           "supported official dispute reaches 100")
        driver.assert_step("criterion-5", detail["facts"]["official_completed_at"] is not None and bool(detail["sources"]["items"]),
                           "detail retains official completion and observation facts")
        baseline, first_submission = driver.run_first_human_boundary(issue_id=args.issue_id, before=args.before, partial=args.partial)
        driver.wait_for_terminal(driver.proof_invocation(baseline["id"], first_submission), seconds=args.wait_seconds)
        driver.finish_happy_path(issue_id=args.issue_id, baseline=baseline, first_submission=first_submission,
                                 after=args.after, seconds=args.wait_seconds)
        if args.compare is None:
            driver.record_pending("criterion-16", "first successful run retained; reset independently and pass it with --compare")
        else:
            prior = json.loads(args.compare.read_text(encoding="utf-8"))
            compare_successful_runs(prior, asdict(artifact))
            driver.assert_step("criterion-16", True,
                               "two independently seeded successful artifacts have equivalent required judgments")
        exit_code = 0
    except (DriverFailure, httpx.HTTPError, OSError) as error:
        artifact.steps.append({"name": "failure", "error": str(error), "at": datetime.now(UTC).isoformat()})
    finally:
        artifact.finished_at = datetime.now(UTC).isoformat()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(asdict(artifact), indent=2, sort_keys=True), encoding="utf-8")
        driver.close()
    return exit_code


def compare_successful_runs(prior: dict, current: dict) -> None:
    """Close DEMO 16 only from two completed artifacts, never from rerunnability."""
    if (not prior.get("run_id") or not current.get("run_id") or prior["run_id"] == current["run_id"]
            or not prior.get("finished_at") or not current.get("finished_at")):
        raise DriverFailure("repeat comparison requires two distinct completed artifact runs")
    for name in [f"criterion-{number}" for number in range(1, 16)]:
        if prior.get("criteria", {}).get(name, {}).get("passed") is not True:
            raise DriverFailure(f"comparison artifact lacks successful {name}")
        if current.get("criteria", {}).get(name, {}).get("passed") is not True:
            raise DriverFailure(f"current artifact lacks successful {name}")
    if prior.get("origin") != current.get("origin") or prior.get("fixture_scenario") != current.get("fixture_scenario"):
        raise DriverFailure("repeat artifacts used different origin or fixture scenario")
    if _facts(prior) != _facts(current):
        raise DriverFailure("repeat artifacts differ on normalized final issue, payment, proof, or budget facts")


def _facts(artifact: dict) -> dict:
    steps = {item.get("name"): item.get("body", {}).get("data") for item in artifact.get("steps", ())}
    detail, board = steps.get("detail-final"), steps.get("board-final")
    if not isinstance(detail, dict) or not isinstance(board, dict):
        raise DriverFailure("comparison artifact lacks final factual API projections")
    return {"issue_status": detail.get("issue", {}).get("status"),
            "job_status": detail.get("current", {}).get("job", {}).get("status"),
            "payment_cents": detail.get("current", {}).get("payment", {}).get("amount_cents"),
            "accepted_submission": detail.get("evidence", {}).get("accepted_submission_id"),
            "spent_cents": board.get("budget", {}).get("spent_cents"),
            "reserved_cents": board.get("budget", {}).get("reserved_cents")}


if __name__ == "__main__":
    raise SystemExit(main())
