"""Private fixed coordinator routes and bounded actor-scoped public processing status."""
import json
from datetime import UTC, datetime

from fastapi import Request

from . import contracts as c
from .actors import AccessBoundary, AccessError, Action
from .coordinator import Coordinator, RuntimeConflict, restored_command
from .runtime_contracts import (
    ControlReply,
    LogicalRequest,
    RuntimeControl,
    RuntimeStatus,
    RuntimeTrace,
    TransportObservation,
)
from .tools.lifecycle import AttemptObservation

CONTROL_OPERATIONS = ("claim", "renew", "prepare", "load", "begin", "finish", "reconcile",
                      "requests", "authorize", "observe", "complete")


def record_control_request(app, actor, invocation_id, operation, request_id, status_code, elapsed_ms):
    if actor is None or actor.actor_type != "service" or operation not in CONTROL_OPERATIONS:
        return
    with app.state.store_factory(app.state.api_settings.store_path) as store:
        try:
            authorize_invocation(store, actor, app.state.api_settings.district_id, invocation_id)
        except (AccessError, KeyError):
            return
        with store.transaction():
            store.db.execute("INSERT INTO runtime_control_observations VALUES (?,?,?,?,?,?)",
                (request_id, invocation_id, operation, status_code, elapsed_ms, datetime.now(UTC).isoformat()))


def authorize_invocation(store, actor, district, invocation_id):
    boundary = AccessBoundary(actor, district)
    invocation = store.get_invocation(invocation_id)
    if actor.actor_type == "crew" and invocation.job_id is None:
        raise AccessError(404, "RESOURCE_NOT_FOUND")
    if invocation.job_id:
        boundary.require_job(store, invocation.job_id)
    elif invocation.issue_id:
        boundary._issue(store, invocation.issue_id)
    elif actor.actor_type != "service":
        if not invocation.signal_id:
            raise AccessError(404, "RESOURCE_NOT_FOUND")
        if store.signal_receipt_actor(invocation.signal_id) != actor.actor_id:
            raise AccessError(404, "RESOURCE_NOT_FOUND")
    else:
        boundary.require_district()
    if actor.actor_type == "resident":
        if not invocation.signal_id:
            raise AccessError(404, "RESOURCE_NOT_FOUND")
        if store.signal_receipt_actor(invocation.signal_id) != actor.actor_id:
            raise AccessError(404, "RESOURCE_NOT_FOUND")
    return invocation


def status_projection(store, invocation_id, *, after_id=0, detailed=True):
    inv = store.get_invocation(invocation_id)
    state = Coordinator(store)._state(invocation_id)
    count = store.db.execute("SELECT COUNT(*) FROM runtime_requests WHERE invocation_id=?", (invocation_id,)).fetchone()[0]
    attempts = store.db.execute("SELECT COUNT(*) FROM runtime_attempts a JOIN runtime_requests r ON r.id=a.request_id "
                               "WHERE r.invocation_id=?", (invocation_id,)).fetchone()[0]
    controls = store.db.execute("SELECT COUNT(*) FROM runtime_control_observations WHERE invocation_id=?", (invocation_id,)).fetchone()[0]
    rows = store.db.execute("SELECT id,kind,record_json,recorded_at FROM runtime_trace WHERE invocation_id=? "
        "AND id>? ORDER BY id LIMIT 21", (invocation_id, after_id)).fetchall()
    trace = []
    for row in rows[:20]:
        raw = json.loads(row[2])
        observation, details = raw.get("observation") or {}, raw.get("details") or {}
        command = details.get("command")
        saved = None
        attempt_views = []
        receipt_id = None
        if row[1] == "tool":
            logical = store.db.execute("SELECT record_json FROM runtime_requests WHERE invocation_id=? AND call_ref LIKE ?",
                (invocation_id, f"model-%-tool-{raw['ordinal']}")).fetchone()
            if logical:
                saved = LogicalRequest.model_validate_json(logical[0])
                command = saved.command.model_dump()
                restored = restored_command(saved.command)
                if saved.idempotency_key:
                    receipt = store.db.execute("SELECT id FROM request_receipts WHERE actor_id='steward-service' AND "
                        "operation=? AND idempotency_key=?", (restored.receipt_operation, saved.idempotency_key)).fetchone()
                    receipt_id = receipt[0] if receipt else None
                for attempt in store.db.execute("SELECT a.ordinal,o.observation_json FROM runtime_attempts a LEFT JOIN "
                    "runtime_observations o ON o.attempt_id=a.id WHERE a.request_id=? ORDER BY a.ordinal", (saved.id,)):
                    observed = json.loads(attempt[1]) if attempt[1] else {}
                    attempt_views.append({"ordinal": attempt[0], "send_state": observed.get("send_state", "unknown"),
                        "elapsed_ms": observed.get("elapsed_ms"), "status_code": observed.get("status_code"),
                        "request_id": observed.get("request_id"), "cancelled": observed.get("cancelled")})
        item = RuntimeTrace(id=row[0], kind=row[1], ordinal=raw["ordinal"],
            phase="OBSERVED" if raw.get("observation") is not None else "REQUESTED", recorded_at=row[3],
            outcome=observation.get("outcome"), operation=command["operation"] if detailed and command else None,
            arguments={"path": command["path"], "query": command["query"], "body": json.loads(command["body_json"]) if command["body_json"] else None,
                       "expected_revision": command["expected_revision"]} if detailed and command else None,
            result=json.loads(observation["result_json"]) if detailed and observation.get("result_json") else None,
            usage=c.ModelUsage.model_validate(observation["usage"]) if detailed and observation.get("usage") else None,
            versions=details.get("configuration") if detailed else None, policy_version=details.get("policy_version") if detailed else None,
            receipt_id=receipt_id if detailed else None, elapsed_ms=observation.get("elapsed_ms") if detailed else None, attempts=tuple(attempt_views) if detailed else ())
        if len(item.model_dump_json().encode()) > 8192:
            # Preserve identity, outcome and timing; do not expose an unbounded model/context body.
            item = item.model_copy(update={"result": None, "arguments": None, "content_truncated": True})
        trace.append(item)
    return RuntimeStatus(invocation_id=inv.id, trigger_event_id=inv.trigger_event_id, status=inv.status,
        state_revision=inv.state_revision, episode_count=state[0] if state else 0,
        model_cycles=state[2] if state else 0, tool_requests=state[3] if state else 0,
        logical_requests=count, transport_attempts=attempts, error_code=inv.error_code, trace=tuple(trace),
        server_control_requests=controls,
        next_cursor=rows[19][0] if len(rows) > 20 else None, truncated=len(rows) > 20)


def install_runtime_routes(app):
    from .api import (
        _openapi_request_schema,
        parse_json_request,
        request_store,
        require_action,
        resolve_actor,
    )

    def endpoint(operation):
        async def control(request: Request, invocation_id: str):
            actor = require_action(request, Action.READ_CONTEXT)
            body = await parse_json_request(request, RuntimeControl, max_bytes=256 * 1024)
            from asyncio import to_thread

            def work():
                with request_store(request) as store:
                    authorize_invocation(store, actor, app.state.api_settings.district_id, invocation_id)
                    co = Coordinator(store)
                    if operation == "claim":
                        if body.owner is None or body.claim is not None:
                            raise RuntimeConflict("INVALID_CONTROL")
                        return co.claim(invocation_id, body.owner, body.nonce).model_dump()
                    claim = body.claim
                    if claim is None or claim.invocation_id != invocation_id:
                        raise RuntimeConflict("FENCED")
                    if operation == "renew":
                        return co.renew(claim).model_dump()
                    if operation == "prepare" and body.command is not None and body.call_ref:
                        return co.prepare(claim, body.call_ref, restored_command(body.command)).model_dump()
                    if operation in {"load", "reconcile"} and body.logical_request_id:
                        return getattr(co, operation)(claim, body.logical_request_id).model_dump()
                    if operation == "requests":
                        return tuple(item.model_dump() for item in co.requests(claim, unresolved_only=True))
                    if operation == "begin" and body.logical_request_id:
                        return co.begin(claim, body.logical_request_id, body.nonce).model_dump()
                    if operation == "finish" and body.attempt_id and body.observation_json:
                        value = TransportObservation.model_validate_json(body.observation_json)
                        co.finish(claim, body.attempt_id, AttemptObservation(**value.model_dump()))
                        return {"accepted": True}
                    if operation in {"authorize", "observe"} and body.kind is not None and body.ordinal is not None:
                        observation = json.loads(body.observation_json) if body.observation_json is not None else None
                        if (operation == "authorize") != (observation is None):
                            raise RuntimeConflict("INVALID_OBSERVATION")
                        details = json.loads(body.details_json) if body.details_json is not None else None
                        return {"accepted": co.execution(claim, body.nonce, body.kind, body.ordinal,
                                                         observation=observation, details=details)}
                    if operation == "complete" and body.status and body.outcome:
                        if body.status != "ERROR":
                            from .context import build_context
                            inv = store.get_invocation(invocation_id)
                            case = build_context(store, inv.trigger_event_id, actor=actor,
                                district_id=app.state.api_settings.district_id, invocation_id=invocation_id,
                                policy_path=app.state.api_settings.policy_path)
                            if case.saved_stop != body.outcome:
                                raise RuntimeConflict("SAVED_STOP_REQUIRED")
                        co.complete(claim, body.status, body.outcome)
                        return {"accepted": True}
                    raise RuntimeConflict("INVALID_CONTROL")
            return {"data": await to_thread(work)}
        return control

    for operation in CONTROL_OPERATIONS:
        app.add_api_route(f"/internal/invocations/{{invocation_id}}/{operation}", endpoint(operation),
            methods=["POST"], operation_id=f"runtime_{operation}", response_model=ControlReply,
            openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
                "schema": _openapi_request_schema(RuntimeControl)}}}})

    @app.get("/api/invocations/{invocation_id}", response_model=c.ToolResult[RuntimeStatus], operation_id="read_invocation_status")
    def processing(request: Request, invocation_id: str, after_id: int = 0):
        if after_id < 0:
            raise AccessError(422, "INVALID_CURSOR")
        actor = resolve_actor(request)
        with request_store(request) as store:
            authorize_invocation(store, actor, app.state.api_settings.district_id, invocation_id)
            return c.ToolResult(outcome="OK", data=status_projection(store, invocation_id, after_id=after_id,
                               detailed=actor.actor_type in {"service", "operator"}))

    @app.post("/api/invocations/{invocation_id}/resume", response_model=c.ToolResult[RuntimeStatus], operation_id="resume_invocation")
    async def resume(request: Request, invocation_id: str):
        require_action(request, Action.READ_CONTEXT)
        async for chunk in request.stream():
            if chunk:
                raise AccessError(422, "BODY_FORBIDDEN")
        from asyncio import to_thread
        def read():
            with request_store(request) as store:
                authorize_invocation(store, resolve_actor(request), app.state.api_settings.district_id, invocation_id)
                return status_projection(store, invocation_id)
        result = await to_thread(read)
        dispatcher = getattr(app.state, "runtime_dispatcher", None)
        if dispatcher is not None:
            dispatcher.wake.set()
        return c.ToolResult(outcome="OK", data=result, reason_code="PROCESSING_ENABLED" if dispatcher else "PROCESSING_DISABLED")
