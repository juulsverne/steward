"""The demo boundary uses real HTTP requests and internally seeded SQLite records."""

import importlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from agent import contracts as c
from agent.store import Store

# Test-only secrets: never used by application configuration or shipped persona setup.
SIGNING = "7a9c4e63b081f205d92461a37c90586ef413ab290675d8ebca013b25e74609df"
TOKEN = "b198d27f3ce40596a180f24d83b710e59603c147ed0f96ca5248ab031d7629fe"
ORIGIN = "http://localhost:8000"
AT = datetime(2026, 9, 13, tzinfo=UTC)
INTENT = {"Origin": ORIGIN, "X-Steward-Request": "1", "Idempotency-Key": "select-1"}


@pytest.fixture
def config(tmp_path):
    from agent.config import ApiSettings

    return ApiSettings(store_path=tmp_path / "demo.sqlite3", origin=ORIGIN,
                       local_http=True, session_secret=SIGNING, service_token=TOKEN)


@pytest.fixture
def app(config):
    from agent.api import create_app

    return create_app(config)


@pytest.fixture
def client(app):
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as value:
        yield value


def select(client, persona="resident-1"):
    return client.post("/api/demo/persona", json={"persona_id": persona}, headers=INTENT)


def test_bootstrap_is_explicit_sandbox_and_never_has_service_secret(client, config):
    empty = client.get("/api/demo/session")
    assert empty.status_code == 200
    assert empty.json()["data"]["actor"] is None
    assert empty.json()["data"]["sandbox"] is True
    assert "private information" in empty.json()["data"]["notice"]
    selected = select(client)
    assert selected.status_code == 200
    assert selected.json()["data"]["actor"]["actor_id"] == "demo-resident-1"
    cookie = selected.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert "Max-Age=43200" in cookie and "Secure" not in cookie
    assert client.get("/api/demo/session").json()["data"]["actor"]["actor_type"] == "resident"
    assert not config.store_path.exists()  # credential renewal creates no domain state
    for response in (empty, selected, client.get("/openapi.json")):
        assert TOKEN not in response.text and SIGNING not in response.text
        assert response.headers["cache-control"] == "no-store"
    assert "service" not in {p["actor_type"] for p in empty.json()["data"]["personas"]}


@pytest.mark.parametrize("patch", [
    {"persona_id": "service"}, {"persona_id": "absent"},
    {"persona_id": "resident-1", "actor_id": "operator"},
    {"persona_id": "resident-1", "vendor_id": "other"},
    {"persona_id": "resident-1", "price_cents": 1},
])
def test_persona_cannot_inject_authority(client, patch):
    response = client.post("/api/demo/persona", json=patch, headers=INTENT)
    assert response.status_code in (403, 422)
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("origin", [None, "null", "http://localhost:8001",
    "http://localhost.evil:8000", "https://localhost:8000", "http://evil.test",
    "http://localhost:8000/", "http://localhost:8000 http://evil.test"])
def test_bootstrap_rejects_untrusted_origins_even_with_forged_host(client, origin):
    headers = {**INTENT, "X-Forwarded-Host": "evil.test"}
    headers.pop("Origin")
    if origin is not None:
        headers["Origin"] = origin
    response = client.post("/api/demo/persona", json={"persona_id": "operator"}, headers=headers)
    assert response.status_code == 403
    assert response.json()["reason_code"] == "ORIGIN_FORBIDDEN"


@pytest.mark.parametrize("header", ["X-Steward-Request", "Idempotency-Key"])
def test_bootstrap_requires_intent_and_idempotency_headers(client, header):
    headers = {k: v for k, v in INTENT.items() if k != header}
    assert client.post("/api/demo/persona", json={"persona_id": "operator"},
                       headers=headers).status_code in (400, 403)


def test_forms_fetch_metadata_host_and_preflight_cannot_bypass_bootstrap(client):
    assert client.post("/api/demo/persona", data={"persona_id": "operator"},
                       headers=INTENT).status_code == 415
    assert client.post("/api/demo/persona", files={"persona_id": (None, "operator")},
                       headers={"Origin": ORIGIN}).status_code == 403
    assert client.post("/api/demo/persona", json={"persona_id": "operator"},
                       headers={**INTENT, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/demo/session", headers={"Host": "evil.test"}).status_code == 400
    preflight = client.options("/api/demo/persona", headers={
        "Origin": "http://evil.test", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in preflight.headers


def test_cookie_tamper_duplicate_expiry_removed_persona_and_rotation(client, config, monkeypatch):
    from agent.api import create_app

    select(client)
    original = client.cookies.get("steward-demo-local")
    client.cookies.clear()
    bad = client.get("/api/demo/session", headers={"Cookie": "steward-demo-local=bad"})
    assert bad.status_code == 401 and "Max-Age=0" in bad.headers["set-cookie"]
    duplicate = client.get("/api/demo/session", headers={
        "Cookie": f"steward-demo-local={original}; steward-demo-local={original}"})
    assert duplicate.status_code == 400
    for settings, expected in ((config, 200), (replace(config, session_secret=TOKEN,
                                                     service_token=SIGNING), 401)):
        with TestClient(create_app(settings), base_url=ORIGIN) as other:
            assert other.get("/api/demo/session", headers={
                "Cookie": f"steward-demo-local={original}"}).status_code == expected
    from agent.actors import configured_personas

    removed = tuple(p for p in configured_personas() if p.persona_id != "resident-1")
    with TestClient(create_app(replace(config, personas=removed)), base_url=ORIGIN) as other:
        assert other.get("/api/demo/session", headers={
            "Cookie": f"steward-demo-local={original}"}).status_code == 401
    import itsdangerous.timed

    real_time = itsdangerous.timed.time.time
    monkeypatch.setattr(itsdangerous.timed.time, "time", lambda: real_time() + 43201)
    assert client.get("/api/demo/session", headers={
        "Cookie": f"steward-demo-local={original}"}).status_code == 401
    assert select(client).status_code == 200  # bad cookies never lock out fresh selection


@pytest.mark.parametrize("changes", [
    {"session_secret": ""}, {"service_token": ""}, {"session_secret": "change-me"},
    {"session_secret": "x" * 64}, {"service_token": SIGNING},
    {"origin": "http://example.com"}, {"origin": "http://localhost:8000/path"},
    {"origin": "https://*.example.com"}, {"origin": "https://user:pass@example.com"},
    {"local_http": False}, {"store_path": ":memory:"},
])
def test_invalid_web_setup_fails_at_factory_without_secret_echo(config, changes):
    from agent.api import create_app

    with pytest.raises(ValueError) as error:
        create_app(replace(config, **changes))
    assert SIGNING not in str(error.value) and TOKEN not in str(error.value)


def test_hosted_cookies_secure_and_settings_import_needs_no_web_secret(config, monkeypatch):
    from agent.api import create_app
    from agent.config import Settings

    monkeypatch.delenv("STEWARD_SESSION_SECRET", raising=False)
    assert Settings("model", "region", 0.3, "INFO").resolved_text_model_id == "model"
    hosted = replace(config, origin="https://demo.example.com", local_http=False)
    with TestClient(create_app(hosted), base_url=hosted.origin) as other:
        response = other.post("/api/demo/persona", json={"persona_id": "operator"},
                              headers={**INTENT, "Origin": hosted.origin})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "__Host-steward-demo=" in cookie and "Secure" in cookie and "Domain=" not in cookie


def test_request_ids_safe_errors_and_starter_route_removed(client):
    responses = [client.post("/ask", json={"prompt": "secret"}),
                 client.post("/api/demo/persona", json={"persona_id": {"secret": TOKEN}},
                             headers={**INTENT, "X-Request-ID": "forged"}),
                 client.post("/api/demo/persona", json={}, headers=INTENT),
                 client.get("/health")]
    assert [r.status_code for r in responses] == [404, 422, 422, 200]
    ids = {r.headers["x-request-id"] for r in responses}
    assert len(ids) == 4
    for response in responses:
        UUID(response.headers["x-request-id"])
        assert TOKEN not in response.text
        assert "outcome" in response.json()
    assert "/ask" not in client.get("/openapi.json").json()["paths"]


def seed_boundary_records(path):
    """Internal setup only: not proof that a dispatch/payment endpoint exists."""
    from agent.actors import configured_personas
    from agent.models import Signal

    resident = configured_personas()[0].actor
    with Store(path) as store:
        for number in (1, 2):
            # Deliberately use the SAME witness and different authenticated submitters.
            owner = resident.model_copy(update={"actor_id": f"demo-resident-{number}"})
            store.store_signal(Signal(id=f"signal-{number}", source="private-source",
                source_author_id="private-witness", raw_text=f"private resident {number}",
                reported_location="private location", received_at=AT, provenance="seeded"),
                actor=owner)
        for issue, vendor, district in (("one", "south_loop_services", "south_loop_demo"),
            ("two", "windy_city_maintenance", "south_loop_demo"),
            ("foreign", "lakefront_clean_team", "other-district")):
            store.create_issue(issue, "bulky_waste", "1530 S Michigan Ave")
            with store.transaction() as tx:
                tx.insert_vendor(c.VendorRecord(id=vendor, name=vendor, insurance_verified=True,
                    service_categories=("bulky_waste",), service_area=(district,),
                    equipment=("truck",), available=True, distance_km=1.0, workload=0,
                    performance=1.0, provenance="seeded", seed_version="v1"))
                tx.insert_plan(c.PlanRecord(id=f"plan-{issue}", issue_id=issue,
                    district_id=district, service_type="bulky_waste", condition="Couch",
                    scope="Remove couch", work_area="Sidewalk", required_equipment=("truck",),
                    crew_count=2, quote_cents=7200, policy_version="south-loop-v3", created_at=AT))
                tx.insert_job(c.JobRecord(id=f"job-{issue}", issue_id=issue,
                    plan_id=f"plan-{issue}", vendor_id=vendor, price_cents=7200, created_at=AT))
                for suffix, role in (("before", "before"), ("unrelated", "signal")):
                    evidence_id = f"image-{issue}-{suffix}"
                    tx.insert_evidence(c.EvidenceRecord(id=evidence_id,
                        image_ref=f"private-object-{evidence_id}", image_sha256="b" * 64,
                        content_type="image/jpeg", size_bytes=10, provenance="synthetic",
                        received_at=AT))
                    tx.associate_evidence(c.EvidenceAssociation(id=f"assoc-{evidence_id}",
                        evidence_id=evidence_id, issue_id=issue, role=role, created_at=AT))


@pytest.fixture
def harness(config):
    from agent.actors import AccessBoundary, Action
    from agent.api import (
        create_app,
        mutation_context,
        request_store,
        require_action,
        result_response,
    )

    seed_boundary_records(config.store_path)
    application = create_app(config)

    # These routes exist only in tests. Their effects stop at authorization/projection.
    @application.get("/test/receipt/{signal_id}")
    def receipt(request: Request, signal_id: str):
        actor = require_action(request, Action.READ_RECEIPT)
        with request_store(request) as store:
            view = AccessBoundary(actor, config.district_id).receipt(store, signal_id)
        return result_response(c.ToolResult(outcome="OK", data=view))

    @application.get("/test/issue/{issue_id}")
    def issue(request: Request, issue_id: str):
        actor = require_action(request, Action.READ_ISSUE)
        with request_store(request) as store:
            view = AccessBoundary(actor, config.district_id).issue(store, issue_id)
        return result_response(c.ToolResult(outcome="OK", data=view))

    @application.get("/test/job/{job_id}")
    def job(request: Request, job_id: str):
        actor = require_action(request, Action.READ_JOB)
        with request_store(request) as store:
            view = AccessBoundary(actor, config.district_id).job(store, job_id)
        return result_response(c.ToolResult(outcome="OK", data=view))

    @application.get("/test/evidence/{evidence_id}")
    def evidence(request: Request, evidence_id: str, job_id: str | None = None):
        actor = require_action(request, Action.READ_EVIDENCE)
        with request_store(request) as store:
            view = AccessBoundary(actor, config.district_id).evidence(store, evidence_id,
                                                                    job_id=job_id)
        return result_response(c.ToolResult(outcome="OK", data=view))

    @application.post("/test/action/{name}")
    def action(request: Request, name: str):
        context = mutation_context(request, Action(name))
        return {"actor_id": context.actor.actor_id, "role": context.actor.actor_type,
                "key": context.idempotency_key, "request_id": request.state.request_id}

    return application


def test_resident_receipts_use_saved_submitter_and_reveal_no_other_history(harness):
    with TestClient(harness, base_url=ORIGIN) as client:
        select(client)
        own = client.get("/test/receipt/signal-1")
        assert own.status_code == 200
        assert set(own.json()["data"]) == {
            "receipt_id", "signal_id", "received_at", "accepted", "processing",
        }
        other = client.get("/test/receipt/signal-2")
        missing = client.get("/test/receipt/absent")
        assert other.status_code == missing.status_code == 404
        assert other.json() == missing.json()
        for path in ("/test/issue/one", "/test/job/job-one", "/test/evidence/image-one-before"):
            response = client.get(path)
            assert response.status_code == 403
            assert response.json()["data"] is None
        assert "private" not in own.text and "invocation" not in own.text
        select(client, "resident-2")
        assert client.get("/test/receipt/signal-2").status_code == 200
        assert client.get("/test/receipt/signal-1").status_code == 404


def test_vendor_job_and_evidence_scope_uses_saved_links_not_supplied_job_id(harness):
    with TestClient(harness, base_url=ORIGIN) as client:
        select(client, "crew-south_loop_services")
        own = client.get("/test/job/job-one")
        assert own.status_code == 200 and own.json()["data"]["price_cents"] == 7200
        assert "private" not in own.text and "signal_ids" not in own.text
        other = client.get("/test/job/job-two")
        assert other.status_code == 404
        assert other.json() == client.get("/test/job/absent").json()
        before = client.get("/test/evidence/image-one-before?job_id=job-one")
        assert before.status_code == 200 and before.json()["data"]["provenance"] == "synthetic"
        assert "private-object" not in before.text and "sha256" not in before.text
        for path in ("image-two-before?job_id=job-one", "image-one-before?job_id=job-two",
                     "image-one-unrelated?job_id=job-one", "image-one-before"):
            assert client.get(f"/test/evidence/{path}").status_code == 404
        assert client.get("/test/issue/one").status_code == 403


@pytest.mark.parametrize("persona,allowed,denied", [
    ("resident-1", ("submit_signal",), ("dispatch", "settle", "close", "check_in")),
    ("operator", ("submit_signal", "request_completion"),
     ("dispatch", "inspect", "settle", "close", "accept_job", "submit_proof")),
    ("crew-south_loop_services", ("submit_signal", "accept_job", "check_in", "submit_proof"),
     ("dispatch", "settle", "close", "request_completion")),
    (None, ("ingest_source", "dispatch", "inspect", "settle", "close"),
     ("submit_signal", "accept_job", "check_in", "submit_proof", "request_completion")),
])
def test_role_actions_cannot_impersonate_humans_or_grant_operator_financial_power(
    harness, persona, allowed, denied,
):
    with TestClient(harness, base_url=ORIGIN) as client:
        headers = INTENT
        if persona:
            select(client, persona)
        else:
            headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "service-1"}
        for name in allowed:
            response = client.post(f"/test/action/{name}", headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["request_id"] == response.headers["x-request-id"]
        for name in (*denied, "edit_policy"):
            response = client.post(f"/test/action/{name}", headers=headers)
            assert response.status_code == 403, response.text


def test_service_credential_cannot_arrive_through_browser_or_aliases(harness):
    with TestClient(harness, base_url=ORIGIN) as client:
        target = "/test/action/dispatch"
        assert client.post(target, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 400
        assert client.post(target, headers={**INTENT,
            "Authorization": f"Bearer {TOKEN}"}).status_code == 403
        for credentials in ("Bearer ", "Basic foo", f"Bearer {SIGNING}", f"Bearer {TOKEN}, x"):
            assert client.post(target, headers={"Authorization": credentials,
                "Idempotency-Key": "a"}).status_code == 401
        assert client.post(target, headers=[("Authorization", f"Bearer {TOKEN}"),
            ("Authorization", f"Bearer {TOKEN}")]).status_code == 400
        assert client.post(f"{target}?token={TOKEN}", json={"token": TOKEN},
                           headers={"Cookie": f"service_token={TOKEN}"}).status_code == 401
        assert select(client).status_code == 200
        assert client.post(target, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 400
        assert client.post("/api/demo/persona", json={"persona_id": "operator"},
            headers={**INTENT, "Authorization": f"Bearer {TOKEN}"}).status_code == 400
        client.cookies.clear()
        assert client.post("/api/demo/persona", json={"persona_id": "operator"},
            headers={**INTENT, "Authorization": f"Bearer {TOKEN}"}).status_code == 403
        assert client.get("/api/demo/session", headers={
            "Authorization": f"Bearer {TOKEN}"}).status_code == 403


def test_cross_district_records_are_hidden_from_operator_and_service(harness, config):
    with Store(config.store_path) as store:
        assert [p.id for p in store.plans_for_issue("one")] == ["plan-one"]
    with TestClient(harness, base_url=ORIGIN) as client:
        for persona in ("operator", None):
            client.cookies.clear()
            headers = {}
            if persona:
                select(client, persona)
            else:
                headers = {"Authorization": f"Bearer {TOKEN}"}
            assert client.get("/test/issue/one", headers=headers).status_code == 200
            for path in ("/test/issue/foreign", "/test/job/job-foreign",
                         "/test/evidence/image-foreign-before"):
                assert client.get(path, headers=headers).status_code == 404


def test_store_closes_on_failures_and_district_denial_precedes_store_open(config):
    from agent.actors import Action, DemoPersona, configured_personas
    from agent.api import create_app, request_store, require_action

    opened = []
    def factory(path):
        store = Store(path)
        opened.append(store)
        return store

    foreign = DemoPersona(persona_id="foreign", actor=c.ActorContext(actor_id="foreign-op",
        actor_type="operator", label="Other operator", district_id="other"))
    application = create_app(replace(config, personas=(*configured_personas(), foreign)),
                             store_factory=factory)

    @application.get("/test/fail")
    def fail(request: Request):
        require_action(request, Action.READ_ISSUE)
        with request_store(request) as store:
            store.get_issue_record("unknown")  # actual exception closes actual connection

    with TestClient(application, base_url=ORIGIN, raise_server_exceptions=False) as client:
        select(client, "foreign")
        response = client.get("/test/fail")
        assert response.status_code == 403 and opened == []
        select(client, "operator")
        response = client.get("/test/fail")
        assert response.status_code == 404
        assert len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError):
            opened[0].db.execute("SELECT 1")
        assert UUID(response.headers["x-request-id"])


def test_actual_server_exposes_only_sandbox_routes_with_explicit_setup(config, monkeypatch):
    import agent.core

    def forbidden_model(**kwargs):
        raise AssertionError("An HTTP identity test must never construct an agent")
    monkeypatch.setattr(agent.core, "build_agent", forbidden_model)
    monkeypatch.setenv("STEWARD_STORE_PATH", str(config.store_path))
    monkeypatch.setenv("STEWARD_ORIGIN", ORIGIN)
    monkeypatch.setenv("STEWARD_LOCAL_HTTP", "true")
    monkeypatch.setenv("STEWARD_SESSION_SECRET", SIGNING)
    monkeypatch.setenv("STEWARD_SERVICE_TOKEN", TOKEN)
    server = importlib.import_module("agent.server")
    monkeypatch.setattr(server, "build_agent", forbidden_model, raising=False)
    with TestClient(server.app, base_url=ORIGIN) as client:
        assert client.post("/ask", json={"prompt": "bypass"}).status_code == 404
        paths = client.get("/openapi.json").json()["paths"]
        assert set(paths) == {
            "/health", "/api/demo/session", "/api/demo/persona", "/api/signals",
            "/api/signals/related", "/api/issues/similar", "/api/issues",
            "/api/issues/{issue_id}/sources",
            "/api/issues/{issue_id}/geocode", "/api/issues/{issue_id}/service-records/search",
            "/api/issues/{issue_id}/classification", "/api/issues/{issue_id}/jurisdiction",
            "/api/issues/{issue_id}/decisions", "/api/issues/{issue_id}/investigation-action",
            "/api/issues/{issue_id}/official-dispute",
            "/api/signals/{signal_id}/intake-inspection",
            "/api/issues/{issue_id}/plan", "/api/plans/{plan_id}/vendors",
            "/api/plans/{plan_id}/dispatch", "/api/jobs/{job_id}",
            "/api/jobs/{job_id}/accept", "/api/jobs/{job_id}/check-in",
            "/api/jobs/{job_id}/proof", "/api/jobs/{job_id}/inspect", "/api/budget",
            "/api/jobs/{job_id}/exceptions", "/api/issues/{issue_id}/exceptions",
            "/api/exceptions/{exception_id}", "/api/exceptions/{exception_id}/request-completion",
            "/api/operator-decisions/{decision_id}/rework",
            "/api/jobs/{job_id}/settle", "/api/jobs/{job_id}/cancel", "/api/issues/{issue_id}/close",
            }
        schema = paths["/api/demo/persona"]["post"]["requestBody"]["content"]
        assert schema["application/json"]["schema"]["additionalProperties"] is False
        assert "persona_id" in schema["application/json"]["schema"]["properties"]


def test_errors_map_without_exception_content_and_connections_close(config):
    from agent.actors import AccessError, Action
    from agent.api import create_app, request_store, require_action, result_response
    from agent.store import IdempotencyConflict, RevisionConflict

    connections = []
    def factory(path):
        store = Store(path)
        connections.append(store)
        return store
    application = create_app(config, store_factory=factory)
    failures = {"unknown": RuntimeError(TOKEN), "storage": sqlite3.OperationalError(SIGNING),
                "revision": RevisionConflict(TOKEN), "idempotency": IdempotencyConflict(TOKEN),
                "state": sqlite3.IntegrityError(TOKEN), "rate": AccessError(429, "WORK_LIMIT")}

    @application.get("/test/error/{kind}")
    def error(request: Request, kind: str):
        require_action(request, Action.READ_ISSUE)
        with request_store(request):
            raise failures[kind]

    @application.get("/test/outcome/{kind}")
    def outcome(kind: str):
        return result_response(c.ToolResult(outcome=kind))

    @application.post("/test/validate")
    def validate(body: c.EntityResult):
        return body

    with TestClient(application, base_url=ORIGIN, raise_server_exceptions=False) as client:
        select(client, "operator")
        for name, status in (("unknown", 500), ("storage", 503), ("revision", 409),
                             ("idempotency", 409), ("state", 409), ("rate", 429)):
            response = client.get(f"/test/error/{name}")
            assert response.status_code == status
            assert TOKEN not in response.text and SIGNING not in response.text
            assert response.json()["data"] is None
            assert UUID(response.headers["x-request-id"])
            with pytest.raises(sqlite3.ProgrammingError):
                connections[-1].db.execute("SELECT 1")
        for name, status in (("OK", 200), ("NEEDS_REVIEW", 200), ("DENIED", 403),
                             ("NOT_FOUND", 404), ("ERROR", 500)):
            assert client.get(f"/test/outcome/{name}").status_code == status
        validation = client.post("/test/validate", json={"record_id": {"private": TOKEN}})
        assert validation.status_code == 422 and TOKEN not in validation.text
        assert validation.json()["data"]["errors"][0]["location"] == "body"
        method = client.post("/health")
        assert method.status_code == 405 and method.headers["allow"] == "GET"


def test_domain_mutations_require_intent_even_after_valid_cookie(harness):
    with TestClient(harness, base_url=ORIGIN) as client:
        select(client, "crew-south_loop_services")
        for headers, status in (({}, 403), ({"Idempotency-Key": "x"}, 403),
                                ({"Origin": ORIGIN, "X-Steward-Request": "1"}, 400)):
            assert client.post("/test/action/check_in", headers=headers).status_code == status


def test_development_origin_is_explicit_and_does_not_enable_cors(config):
    from agent.api import create_app

    origin = "http://localhost:5173"
    with TestClient(create_app(replace(config, development_origins=(origin,))),
                    base_url=ORIGIN) as client:
        response = client.post("/api/demo/persona", json={"persona_id": "resident-1"},
                                headers={**INTENT, "Origin": origin})
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers
    with pytest.raises(ValueError):
        create_app(replace(config, development_origins=("https://*.example.com",)))


def test_known_placeholder_pattern_and_service_personas_fail_setup(config):
    from agent.actors import DemoPersona
    from agent.api import create_app

    with pytest.raises(ValueError):
        create_app(replace(config, session_secret="0123456789abcdef" * 4))
    with pytest.raises(ValueError):
        create_app(replace(config, personas=(DemoPersona(persona_id="service",
            actor=c.ActorContext(actor_id="service", actor_type="service", label="Fake human")),)))


def test_oversize_bootstrap_and_duplicate_security_headers_rejected(client):
    assert client.post("/api/demo/persona", json={"persona_id": "x" * 4100},
                        headers=INTENT).status_code == 413
    headers = list(INTENT.items()) + [("Origin", ORIGIN)]
    assert client.post("/api/demo/persona", json={"persona_id": "operator"},
                        headers=headers).status_code == 400
    assert client.post("/api/demo/persona", json={"persona_id": "operator"},
        headers={**INTENT, "Cookie": "steward-demo-local=a; steward-demo-local=b"}
    ).status_code == 400


def test_case_evidence_does_not_expose_other_jobs_old_completion(harness, config):
    from agent.actors import configured_personas

    crew = next(p.actor for p in configured_personas()
                if p.persona_id == "crew-south_loop_services")
    with Store(config.store_path) as store, store.transaction() as tx:
        for suffix in ("old", "current"):
            tx.insert_evidence(c.EvidenceRecord(id=f"proof-{suffix}", image_ref=f"ref-{suffix}",
                image_sha256="c" * 64, content_type="image/jpeg", size_bytes=10,
                provenance="synthetic", received_at=AT))
            tx.associate_evidence(c.EvidenceAssociation(id=f"proof-link-{suffix}",
                evidence_id=f"proof-{suffix}", issue_id="one", job_id="job-one",
                role="completion", created_at=AT))
            tx.insert_submission(c.SubmissionRecord(id=f"submission-{suffix}", issue_id="one",
                job_id="job-one", before_evidence_id="image-one-before",
                after_evidence_id=f"proof-{suffix}", submitted_by=crew,
                submitted_at=AT, job_revision=0))
        job = store.get_job("job-one")
        tx.replace_job(job.model_copy(update={"latest_submission_id": "submission-current",
            "state_revision": 1}), 0)
    with TestClient(harness, base_url=ORIGIN) as client:
        select(client, "crew-south_loop_services")
        assert client.get("/test/evidence/proof-current?job_id=job-one").status_code == 200
        assert client.get("/test/evidence/proof-old?job_id=job-one").status_code == 404


def test_store_worker_threads_never_share_connections(config):
    from concurrent.futures import ThreadPoolExecutor
    from threading import get_ident

    from agent.actors import Action
    from agent.api import create_app, request_store, require_action

    opened_in = {}
    def factory(path):
        store = Store(path)
        opened_in[id(store)] = get_ident()
        return store
    application = create_app(config, store_factory=factory)

    @application.get("/test/worker")
    def worker(request: Request):
        require_action(request, Action.READ_ISSUE)
        with request_store(request) as store:
            assert opened_in[id(store)] == get_ident()
            store.db.execute("SELECT 1").fetchone()
        with pytest.raises(sqlite3.ProgrammingError):
            store.db.execute("SELECT 1")
        return {"ok": True}

    with TestClient(application, base_url=ORIGIN) as client:
        def invoke(_):
            return client.get("/test/worker", headers={"Authorization": f"Bearer {TOKEN}"})
        with ThreadPoolExecutor(max_workers=4) as workers:
            assert all(r.status_code == 200 for r in workers.map(invoke, range(8)))


@pytest.mark.parametrize("issue_id,explicit_issue_link,status", [
    ("foreign", True, 404), ("foreign", False, 404),
    ("one", True, 200), ("one", False, 200), (None, False, 200),
])
def test_service_evidence_follows_current_signal_link_not_historical_association(
    harness, config, issue_id, explicit_issue_link, status,
):
    with Store(config.store_path) as store:
        with store.transaction() as tx:
            tx.insert_evidence(c.EvidenceRecord(id="retained-image", image_ref="retained-ref",
                image_sha256="d" * 64, content_type="image/jpeg", size_bytes=10,
                provenance="synthetic", received_at=AT))
            tx.associate_evidence(c.EvidenceAssociation(id="original-signal-association",
                evidence_id="retained-image", signal_id="signal-1", role="signal", created_at=AT))
        if issue_id is not None:
            store.link_signal(issue_id, "signal-1")
            if explicit_issue_link:
                with store.transaction() as tx:
                    tx.associate_evidence(c.EvidenceAssociation(id="later-issue-association",
                        evidence_id="retained-image", issue_id=issue_id, role="before", created_at=AT))
        # Receipt and original evidence association are immutable historical snapshots.
        assert store.get_signal_receipt("signal-1").issue_id is None
        assert store.evidence_associations("retained-image")[-1].issue_id is None
    with TestClient(harness, base_url=ORIGIN) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.get("/test/evidence/retained-image", headers=headers)
        assert response.status_code == status
        if status == 404:
            assert response.json() == client.get("/test/evidence/absent", headers=headers).json()
        else:
            assert response.json()["data"]["id"] == "retained-image"
