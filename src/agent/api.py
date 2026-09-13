"""Steward HTTP identity boundary. Domain operation routers belong to later cards."""

from __future__ import annotations

import ipaddress
import re
import secrets
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from . import contracts as c
from .actors import (
    SESSION_MAX_AGE,
    AccessBoundary,
    AccessError,
    Action,
    DemoPersona,
    DemoSessions,
    DemoSessionView,
    configured_personas,
)
from .config import ApiSettings
from .policy import load_policy
from .store import IdempotencyConflict, RevisionConflict, Store


class PersonaRequest(c.Record):
    persona_id: c.OpaqueId


class HealthView(c.Record):
    ok: bool


class ValidationDetail(c.Record):
    code: str = "INVALID_FIELD"
    location: str


class ValidationView(c.Record):
    errors: tuple[ValidationDetail, ...]


ERROR_RESPONSES = {status: {"model": c.ToolResult[ValidationView]} for status in (
    400, 401, 403, 404, 405, 409, 413, 415, 422, 429, 500, 503,
)}


def result_response(result: c.ToolResult, *, status: int | None = None) -> JSONResponse:
    """Map a typed outcome; operations opt into 201/202 only after durable commit."""
    default = {"OK": 200, "NEEDS_REVIEW": 200, "DENIED": 403,
               "NOT_FOUND": 404, "ERROR": 500}[result.outcome]
    return JSONResponse(result.model_dump(mode="json"), status_code=status or default)


def error_response(error: AccessError, cookie_name: str) -> JSONResponse:
    outcome = ("NOT_FOUND" if error.status == 404 else "DENIED" if
               error.status in {401, 403, 409} or error.reason == "MIXED_CREDENTIALS" else "ERROR")
    response = result_response(c.ToolResult(outcome=outcome, reason_code=error.reason),
                               status=error.status)
    if error.clear_cookie:
        response.delete_cookie(cookie_name, path="/", httponly=True, samesite="strict",
                               secure=cookie_name.startswith("__Host-"))
    return response


def _origin(value: str) -> tuple[str, bool]:
    try:
        url = urlsplit(value)
        host = url.hostname
        if (not host or url.scheme not in {"http", "https"} or url.path or url.query
                or url.fragment or url.username or url.password or "*" in value
                or any(ch.isspace() for ch in value)):
            raise ValueError
        authority = f"[{host}]" if ":" in host else host
        if url.port is not None:
            authority += f":{url.port}"
        if value != f"{url.scheme}://{authority}":
            raise ValueError
        loopback = host == "localhost"
        if not loopback:
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                if not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", host):
                    raise ValueError from None
        return authority, loopback
    except (ValueError, AttributeError) as error:
        raise ValueError("STEWARD_ORIGIN must be one canonical origin without a path") from error


def _validate_setup(settings: ApiSettings) -> tuple[DemoPersona, ...]:
    for secret in (settings.session_secret, settings.service_token):
        if (not isinstance(secret, str) or not re.fullmatch(r"[0-9a-f]{64}", secret)
                or len(set(secret)) < 12 or any(
                    secret == secret[:n] * (64 // n) for n in (1, 2, 4, 8, 16, 32))):
            raise ValueError("Web secrets must be independent random 32-byte hex values")
    if secrets.compare_digest(settings.session_secret, settings.service_token):
        raise ValueError("Session signing and service credentials must differ")
    _, local = _origin(settings.origin)
    if settings.local_http:
        if not local or not settings.origin.startswith("http://"):
            raise ValueError("Local HTTP mode requires a loopback HTTP origin")
    elif not settings.origin.startswith("https://"):
        raise ValueError("Hosted mode requires HTTPS")
    for origin in settings.development_origins:
        _, local = _origin(origin)
        if not settings.local_http or not local or not origin.startswith("http://"):
            raise ValueError("Additional origins are only explicit local HTTP development origins")
    path = Path(settings.store_path)
    if str(path) in {".", ":memory:"} or path.is_dir() or not path.parent.is_dir():
        raise ValueError("Configure a named Store file in an existing private directory")
    policy = load_policy(settings.policy_path)
    if settings.district_id != "south_loop_demo" or policy["district"] != settings.district_id:
        raise ValueError("The named Store must use the versioned south_loop_demo policy")
    personas = settings.personas if settings.personas is not None else configured_personas()
    if not personas:
        raise ValueError("Configure at least one human demo persona")
    seen_ids, seen_actors = set(), set()
    for entry in personas:
        entry = DemoPersona.model_validate_json(entry.model_dump_json())
        if (entry.actor.actor_type == "service" or entry.persona_id in seen_ids
                or entry.actor.actor_id in seen_actors or entry.actor.actor_id == "steward-service"
                or (entry.actor.actor_type != "crew" and entry.actor.vendor_id is not None)):
            raise ValueError("Demo personas must be distinct configured human identities")
        seen_ids.add(entry.persona_id)
        seen_actors.add(entry.actor.actor_id)
    return tuple(personas)


def _header(request: Request, name: str) -> str | None:
    values = request.headers.getlist(name)
    if len(values) > 1:
        raise AccessError(400, "AMBIGUOUS_HEADER")
    return values[0] if values else None


def _cookie(request: Request) -> str | None:
    name = request.app.state.cookie_name
    values = []
    for raw in request.headers.getlist("cookie"):
        for part in raw.split(";"):
            key, separator, value = part.strip().partition("=")
            if key == name:
                values.append(value if separator else "")
    if len(values) > 1:
        raise AccessError(400, "AMBIGUOUS_COOKIE")
    return values[0] if values else None


def browser_intent(request: Request) -> None:
    origin = _header(request, "origin")
    if origin not in request.app.state.allowed_origins:
        raise AccessError(403, "ORIGIN_FORBIDDEN")
    if (_header(request, "x-steward-request") != "1"
            or _header(request, "sec-fetch-site") == "cross-site"):
        raise AccessError(403, "REQUEST_INTENT_REQUIRED")


def idempotency_key(request: Request) -> str:
    key = _header(request, "idempotency-key")
    if key is None or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", key):
        raise AccessError(400, "IDEMPOTENCY_KEY_REQUIRED")
    return key


def resolve_actor(request: Request, *, optional: bool = False) -> c.ActorContext | None:
    """Authority comes exclusively from the configured human cookie or service token."""
    authorization = _header(request, "authorization")
    cookie = _cookie(request)
    if authorization is not None and cookie is not None:
        raise AccessError(400, "MIXED_CREDENTIALS")
    if authorization is not None:
        if _header(request, "origin") is not None:
            raise AccessError(403, "BROWSER_SERVICE_FORBIDDEN")
        match = re.fullmatch(r"Bearer ([0-9a-f]{64})", authorization)
        if not match or not secrets.compare_digest(
            match.group(1), request.app.state.api_settings.service_token
        ):
            raise AccessError(401, "INVALID_SERVICE_CREDENTIAL")
        return c.ActorContext(actor_id="steward-service", actor_type="service", label="Steward",
                              district_id=request.app.state.api_settings.district_id)
    if cookie is not None:
        actor = request.app.state.sessions.resolve(cookie)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            browser_intent(request)
        return actor
    if optional:
        return None
    raise AccessError(401, "AUTH_REQUIRED")


def require_action(request: Request, action: Action) -> c.ActorContext:
    actor = resolve_actor(request)
    AccessBoundary(actor, request.app.state.api_settings.district_id).require(action)
    return actor


def mutation_context(request: Request, action: Action, *,
                     expected_revision: int | None = None) -> c.MutationContext:
    """Bind role and actor server-side; domain operations still persist receipts/gates.

    Transport request IDs remain on request.state, separate from persisted invocation IDs.
    The operation/revision arguments come from the route, not an ActorContext body.
    """
    actor = require_action(request, action)
    return c.MutationContext(actor=actor, operation=action.value,
        idempotency_key=idempotency_key(request), expected_revision=expected_revision)


@contextmanager
def request_store(request: Request):
    """Open/use/close within ONE synchronous endpoint/worker call, never Depends(yield).

    SQLite retains check_same_thread. An async upload route must hand this entire
    synchronous unit to a worker after decoding, rather than moving a live connection.
    """
    actor = resolve_actor(request)
    AccessBoundary(actor, request.app.state.api_settings.district_id).require_district()
    if getattr(request.state, "store_opened", False):
        raise RuntimeError("Only one Store connection may be opened per request")
    request.state.store_opened = True
    try:
        with request.app.state.store_factory(request.app.state.api_settings.store_path) as store:
            yield store
    except KeyError:
        raise AccessError(404, "RESOURCE_NOT_FOUND") from None


def create_app(settings: ApiSettings | None = None,
               *, store_factory: Callable = Store) -> FastAPI:
    settings = settings or ApiSettings.from_env()
    personas = _validate_setup(settings)
    app = FastAPI(title="Steward demo sandbox", description=(
        "Seeded persona simulation, not verified identity. No private information. "
        "Domain operation routes are not yet implemented."), responses=ERROR_RESPONSES)
    app.state.api_settings = settings
    app.state.store_factory = store_factory
    app.state.sessions = DemoSessions(settings.session_secret, personas)
    app.state.cookie_name = "steward-demo-local" if settings.local_http else "__Host-steward-demo"
    app.state.allowed_origins = frozenset((settings.origin, *settings.development_origins))
    app.state.allowed_hosts = frozenset(_origin(origin)[0] for origin in app.state.allowed_origins)

    @app.middleware("http")
    async def transport(request: Request, call_next):
        request.state.request_id = str(uuid4())
        try:
            if _header(request, "host") not in app.state.allowed_hosts:
                raise AccessError(400, "HOST_FORBIDDEN")
            response = await call_next(request)
        except AccessError as error:
            response = error_response(error, app.state.cookie_name)
        except Exception:  # noqa: BLE001 -- outer HTTP boundary must redact unexpected errors
            # Never echo exceptions, request content, SQL, paths, or credentials.
            response = error_response(AccessError(500, "INTERNAL_ERROR"), app.state.cookie_name)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(AccessError)
    async def access_error(request, error):
        return error_response(error, app.state.cookie_name)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        locations = {"body", "path", "query", "header"}
        details = tuple(ValidationDetail(location=(entry["loc"][0] if entry.get("loc")
            and entry["loc"][0] in locations else "request")) for entry in error.errors()[:20])
        return result_response(c.ToolResult[ValidationView](outcome="ERROR",
            reason_code="VALIDATION_ERROR", data=ValidationView(errors=details)), status=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        response = error_response(AccessError(error.status_code,
            "RESOURCE_NOT_FOUND" if error.status_code == 404 else "INVALID_REQUEST"),
            app.state.cookie_name)
        if error.status_code == 405 and error.headers and "Allow" in error.headers:
            response.headers["Allow"] = error.headers["Allow"]
        return response

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_error(request, error):
        return error_response(AccessError(409, "IDEMPOTENCY_CONFLICT"), app.state.cookie_name)

    @app.exception_handler(RevisionConflict)
    async def revision_error(request, error):
        return error_response(AccessError(409, "REVISION_CONFLICT"), app.state.cookie_name)

    @app.exception_handler(sqlite3.OperationalError)
    async def storage_error(request, error):
        return error_response(AccessError(503, "STORAGE_UNAVAILABLE"), app.state.cookie_name)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, error):
        return error_response(AccessError(409, "STATE_CONFLICT"), app.state.cookie_name)

    @app.get("/health", response_model=c.ToolResult[HealthView])
    def health():
        return c.ToolResult[HealthView](outcome="OK", data=HealthView(ok=True))

    @app.get("/api/demo/session", response_model=c.ToolResult[DemoSessionView])
    def session(request: Request):
        actor = resolve_actor(request, optional=True)
        if actor is not None and actor.actor_type == "service":
            raise AccessError(403, "ROLE_FORBIDDEN")
        return c.ToolResult[DemoSessionView](outcome="OK", data=app.state.sessions.view(actor))

    @app.post("/api/demo/persona", response_model=c.ToolResult[DemoSessionView], openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {
            "schema": PersonaRequest.model_json_schema()}}},
        "parameters": [{"name": name, "in": "header", "required": True,
                        "schema": {"type": "string"}} for name in (
                            "Origin", "X-Steward-Request", "Idempotency-Key")],
    })
    async def persona(request: Request):
        # Protect before parsing, including the first unauthenticated selection.
        cookie = _cookie(request)  # Permit replacement of one invalid cookie, not ambiguity.
        if _header(request, "authorization") is not None:
            if cookie is not None:
                raise AccessError(400, "MIXED_CREDENTIALS")
            raise AccessError(403, "ROLE_FORBIDDEN")
        browser_intent(request)
        idempotency_key(request)
        if (_header(request, "content-type") or "").split(";", 1)[0].strip() != "application/json":
            raise AccessError(415, "JSON_REQUIRED")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 4096:
                raise AccessError(413, "REQUEST_TOO_LARGE")
        try:
            body = PersonaRequest.model_validate_json(bytes(raw))
        except ValueError:
            raise AccessError(422, "VALIDATION_ERROR") from None
        actor, cookie = app.state.sessions.select(body.persona_id)
        response = result_response(c.ToolResult[DemoSessionView](
            outcome="OK", data=app.state.sessions.view(actor)))
        response.set_cookie(app.state.cookie_name, cookie, max_age=SESSION_MAX_AGE, path="/",
                            secure=not settings.local_http, httponly=True, samesite="strict")
        return response

    return app
