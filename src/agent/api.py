"""Steward HTTP identity boundary and the narrow authenticated intake operation."""

from __future__ import annotations

import ipaddress
import re
import secrets
import sqlite3
from asyncio import to_thread
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser

from . import contracts as c
from .actors import (
    SESSION_MAX_AGE,
    AccessBoundary,
    AccessError,
    Action,
    DemoPersona,
    DemoSessions,
    configured_personas,
)
from .adapters import SeededAdapters
from .config import ApiSettings
from .decisions import record_operational_decision
from .http_contracts import (
    CandidateSignalsView,
    CandidateSignalView,
    CheckinRequest,
    ClassificationProposalRequest,
    CompletionExceptionRequest,
    CrewJobView,
    DecisionProposalRequest,
    DemoSessionView,
    DispatchRequest,
    ExceptionListView,
    HealthView,
    InspectCompletionRequest,
    IntakeReceiptView,
    InvestigationActionRequest,
    IssueCreateRequest,
    IssueExceptionRequest,
    JurisdictionProposalRequest,
    LinkSignalRequest,
    OperationalDecisionProposalRequest,
    PersonaRequest,
    PlanRequest,
    ProofMetadata,
    RequestCompletionRequest,
    SimilarIssuesView,
    SimilarIssueView,
    StoredSignalRequest,
    ValidationDetail,
    ValidationView,
    VendorOptions,
)
from .http_protocol import OPERATION_IDS
from .images import MAX_UPLOAD_BYTES, UploadError, decode_upload, known_synthetic_fixture
from .intake import persist_signal, resident_signal
from .investigation import (
    apply_investigation_decision,
    create_issue_from_signal,
    decide,
    inspect_intake_photo,
    link_signal_to_issue,
    record_geocode,
    record_service_lookup,
    save_classification,
    save_jurisdiction,
    stable_id,
)
from .models import utc_time
from .operations import (
    ProofImages,
    accept_job,
    build_resolution_plan,
    cancel_job,
    check_in,
    close_issue,
    dispatch_vendor,
    escalate_to_operator,
    exception_detail,
    inspect_completion,
    list_eligible_vendors,
    release_payment,
    request_completion,
    request_rework,
    submit_proof,
)
from .policy import load_policy
from .store import IdempotencyConflict, RevisionConflict, Store

ERROR_RESPONSES = {status: {"model": c.ToolResult[
    ValidationView | c.CompletionInspectionResult | c.EntityResult]} for status in (
    400, 401, 403, 404, 405, 409, 413, 415, 422, 429, 500, 503,
)}
MAX_MULTIPART_OVERHEAD = 64 * 1024

def _openapi_request_schema(model: type[c.Record]) -> dict:
    """Use namespaced components for both refs and discriminator mappings.

    Definitions remain attached until _configure_openapi installs them in the
    complete document. Request schemas cannot collide with response-mode schemas.
    """
    return model.model_json_schema(ref_template=f"#/components/schemas/{model.__name__}_{{model}}")


def _configure_openapi(app: FastAPI) -> None:
    json_bodies = {
        "select_demo_persona": PersonaRequest, "create_issue_from_signal": IssueCreateRequest,
        "build_resolution_plan": PlanRequest, "dispatch_vendor": DispatchRequest,
        "check_in": CheckinRequest, "inspect_completion": InspectCompletionRequest,
        "release_payment": InspectCompletionRequest, "escalate_completion_exception": CompletionExceptionRequest,
        "escalate_issue_exception": IssueExceptionRequest, "request_completion": RequestCompletionRequest,
        "geocode_location": StoredSignalRequest, "link_signal": LinkSignalRequest,
        "search_311": StoredSignalRequest, "classify_issue": ClassificationProposalRequest,
        "determine_jurisdiction": JurisdictionProposalRequest, "decide_issue": DecisionProposalRequest,
        "decide_operational": OperationalDecisionProposalRequest,
        "apply_investigation_decision": InvestigationActionRequest, "official_dispute": InvestigationActionRequest,
    }
    human_posts = {"select_demo_persona", "submit_signal", "accept_job", "check_in", "submit_proof", "request_completion"}
    no_revision = {"select_demo_persona", "submit_signal", "create_issue_from_signal", "inspect_intake_photo"}
    for route in app.routes:
        if not isinstance(route, APIRoute) or "POST" not in route.methods:
            continue
        operation = route.operation_id
        extra = dict(route.openapi_extra or {})
        parameters = {item["name"].lower(): item for item in extra.get("parameters", [])}
        header_names = ["Idempotency-Key"]
        if operation not in no_revision:
            header_names.append("X-Steward-Expected-Revision")
        if operation in human_posts:
            header_names.extend(("Origin", "X-Steward-Request"))
        else:
            parameters["x-steward-invocation-id"] = {"name": "X-Steward-Invocation-Id", "in": "header",
                "required": False, "description": "Service only; actual saved invocation identity.",
                "schema": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"}}
        for name in header_names:
            parameters[name.lower()] = {"name": name, "in": "header", "required": True,
                "schema": {"type": "string", **({"pattern": "^[0-9]+$"} if name == "X-Steward-Expected-Revision" else {})}}
        extra["parameters"] = list(parameters.values())
        if operation in json_bodies:
            extra["requestBody"] = {"required": True, "content": {"application/json": {
                "schema": _openapi_request_schema(json_bodies[operation])}}}
        elif operation == "submit_signal":
            extra["requestBody"] = {"required": True, "content": {"multipart/form-data": {"schema": {
                "type": "object", "additionalProperties": False, "required": ["description", "location"],
                "properties": {"description": {"type": "string", "minLength": 1, "pattern": r"\S"},
                    "location": {"type": "string", "minLength": 1, "pattern": r"\S"},
                    "observed_at": {"type": "string", "description": "Optional timestamp with timezone; empty means unknown."},
                    "image": {"type": "string", "format": "binary", "description": "Optional JPEG/PNG, at most 10 MiB."}}}}}}
        elif operation == "submit_proof":
            extra["requestBody"] = {"required": True, "content": {"multipart/form-data": {"schema": {
                "type": "object", "additionalProperties": False, "required": ["after", "metadata"],
                "properties": {"before": {"type": "string", "format": "binary",
                    "description": "Required for first proof; forbidden for rework. JPEG/PNG, at most 10 MiB."},
                    "after": {"type": "string", "format": "binary", "description": "Fresh JPEG/PNG, at most 10 MiB."},
                    "metadata": {"type": "string", "contentMediaType": "application/json",
                        "contentSchema": ProofMetadata.model_json_schema(), "maxLength": 4096,
                        "description": "JSON encoded ProofMetadata, at most 4096 UTF-8 bytes. Rework forbids before_observed_at, including null."}}}}}}
        route.openapi_extra = extra

    def openapi():
        if app.openapi_schema is None:
            document = get_openapi(title=app.title, version=app.version, openapi_version=app.openapi_version,
                                   description=app.description, routes=app.routes)
            components = document.setdefault("components", {}).setdefault("schemas", {})
            for path in document["paths"].values():
                for operation in path.values():
                    if not isinstance(operation, dict):
                        continue
                    content = operation.get("requestBody", {}).get("content", {})
                    for media in content.values():
                        schema = media.get("schema", {})
                        for name, definition in schema.pop("$defs", {}).items():
                            component = f"{schema['title']}_{name}"
                            if component in components and components[component] != definition:
                                raise ValueError("conflicting public request schema")
                            components[component] = definition
            app.openapi_schema = document
        return app.openapi_schema
    app.openapi = openapi


class IntakeMultiPartParser(MultiPartParser):
    """One file and bounded streamed bytes before Starlette can spool an unbounded upload."""

    def __init__(self, headers, stream, *, max_files: int = 1):
        super().__init__(headers, stream, max_files=max_files, max_fields=4,
                         max_part_size=MAX_MULTIPART_OVERHEAD)
        self._file_bytes: dict[int, int] = {}
        self._multipart_complete = False

    def on_headers_finished(self) -> None:
        super().on_headers_finished()
        file = self._current_part.file
        if file is None:
            return
        filename = file.filename or ""
        if (not filename or "/" in filename or "\\" in filename or filename.startswith("~")
                or re.match(r"^[A-Za-z]:", filename)):
            raise MultiPartException("invalid upload filename")
        self._file_bytes[id(file)] = 0

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        file = self._current_part.file
        if file is not None:
            next_size = self._file_bytes[id(file)] + end - start
            if next_size > MAX_UPLOAD_BYTES:
                raise MultiPartException("file exceeded 10 MiB")
            self._file_bytes[id(file)] = next_size
        super().on_part_data(data, start, end)

    def on_end(self) -> None:
        self._multipart_complete = True
        super().on_end()

    async def parse(self) -> FormData:
        form = await super().parse()
        if not self._multipart_complete:
            # Starlette only puts completed file parts in FormData.  A truncated
            # body must not leave its allocated spools open or become an image-less
            # signal after the parser returns successfully.
            for file in self._files_to_close_on_error:
                file.close()
            raise MultiPartException("incomplete multipart body")
        return form


async def parse_intake_form(request: Request) -> FormData:
    """Bound total request bytes independently of Content-Length and close files on parser error."""
    async def limited_stream():
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD:
                raise MultiPartException("multipart request exceeded upload limit")
            yield chunk

    return await IntakeMultiPartParser(request.headers, limited_stream()).parse()


async def parse_proof_form(request: Request) -> FormData:
    """B6's two-image form retains B3's streamed limit, completion and cleanup behavior."""
    async def limited_stream():
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > (2 * MAX_UPLOAD_BYTES) + MAX_MULTIPART_OVERHEAD:
                raise MultiPartException("multipart request exceeded upload limit")
            yield chunk

    return await IntakeMultiPartParser(request.headers, limited_stream(), max_files=2).parse()


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


def expected_revision(request: Request) -> int | None:
    value = _header(request, "x-steward-expected-revision")
    if value is None:
        return None
    if not value.isdigit():
        raise AccessError(400, "EXPECTED_REVISION_INVALID")
    return int(value)


async def parse_json_request(request: Request, model):
    if (_header(request, "content-type") or "").split(";", 1)[0].strip() != "application/json":
        raise AccessError(415, "JSON_REQUIRED")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16 * 1024:
            raise AccessError(413, "REQUEST_TOO_LARGE")
    try:
        return model.model_validate_json(bytes(raw))
    except ValueError:
        raise AccessError(422, "VALIDATION_ERROR") from None


def resolve_actor(request: Request, *, optional: bool = False) -> c.ActorContext | None:
    """Authority comes exclusively from the configured human cookie or service token."""
    authorization = _header(request, "authorization")
    cookie = _cookie(request)
    invocation_id = _header(request, "x-steward-invocation-id")
    if invocation_id is not None and authorization is None:
        raise AccessError(403, "INVOCATION_SERVICE_ONLY")
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
                     expected_revision: int | None = None, operation: str | None = None) -> c.MutationContext:
    """Bind role and actor server-side; domain operations still persist receipts/gates.

    Transport request IDs remain on request.state, separate from persisted invocation IDs.
    The operation/revision arguments come from the route, not an ActorContext body.
    """
    actor = require_action(request, action)
    invocation_id = _header(request, "x-steward-invocation-id")
    if invocation_id is not None:
        if actor.actor_type != "service":
            raise AccessError(403, "INVOCATION_SERVICE_ONLY")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", invocation_id):
            raise AccessError(400, "INVOCATION_ID_INVALID")
    return c.MutationContext(actor=actor, operation=operation or action.value,
        idempotency_key=idempotency_key(request), invocation_id=invocation_id,
        expected_revision=expected_revision)


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
               *, store_factory: Callable = Store, adapters=None, intake_inspector=None,
               completion_inspector=None) -> FastAPI:
    settings = settings or ApiSettings.from_env()
    personas = _validate_setup(settings)
    app = FastAPI(title="Steward demo sandbox", description=(
        "Seeded persona simulation, not verified identity. No private information. "
        "Authenticated intake, investigation, planning and simulated dispatch."), responses=ERROR_RESPONSES)
    app.state.api_settings = settings
    app.state.store_factory = store_factory
    app.state.adapters = adapters or SeededAdapters()
    app.state.intake_inspector = intake_inspector
    app.state.completion_inspector = completion_inspector
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

    @app.exception_handler(UploadError)
    async def upload_error(request, error):
        return result_response(c.ToolResult(outcome="ERROR", reason_code="INVALID_IMAGE"),
                               status=error.status)

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
            "schema": _openapi_request_schema(PersonaRequest)}}},
        "parameters": [{"name": name, "in": "header", "required": True,
                        "schema": {"type": "string"}} for name in (
                            "Origin", "X-Steward-Request", "Idempotency-Key")],
    })
    async def persona(request: Request):
        # Protect before parsing, including the first unauthenticated selection.
        if _header(request, "x-steward-invocation-id") is not None:
            raise AccessError(403, "INVOCATION_SERVICE_ONLY")
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
        except IdempotencyConflict:
            raise
        except ValueError:
            raise AccessError(422, "VALIDATION_ERROR") from None
        actor, cookie = app.state.sessions.select(body.persona_id)
        response = result_response(c.ToolResult[DemoSessionView](
            outcome="OK", data=app.state.sessions.view(actor)))
        response.set_cookie(app.state.cookie_name, cookie, max_age=SESSION_MAX_AGE, path="/",
                            secure=not settings.local_http, httponly=True, samesite="strict")
        return response

    @app.post("/api/signals", response_model=c.ToolResult[IntakeReceiptView], status_code=202,
              openapi_extra={"parameters": [{"name": "Idempotency-Key", "in": "header",
                  "required": True, "schema": {"type": "string"}}]})
    async def submit_signal(request: Request):
        # Bind authentication and browser intent before FastAPI/multipart touches upload bytes.
        actor = resolve_actor(request)
        action = Action.SUBMIT_SIGNAL
        AccessBoundary(actor, settings.district_id).require(action)
        context = c.MutationContext(actor=actor, operation=action.value,
            idempotency_key=idempotency_key(request))
        content_type = (_header(request, "content-type") or "").split(";", 1)[0].strip().lower()
        if content_type != "multipart/form-data":
            raise AccessError(415, "MULTIPART_REQUIRED")
        content_length = _header(request, "content-length")
        if content_length and (not content_length.isdigit() or int(content_length) > MAX_UPLOAD_BYTES + 65536):
            raise AccessError(413, "REQUEST_TOO_LARGE")
        try:
            form = await parse_intake_form(request)
        except MultiPartException as error:
            status = 422 if str(error) in {"invalid upload filename", "incomplete multipart body"} else 413
            raise AccessError(status, "VALIDATION_ERROR" if status == 422 else "REQUEST_TOO_LARGE") from None
        try:
            allowed = {"description", "location", "observed_at", "image"}
            if any(key not in allowed or len(form.getlist(key)) != 1 for key in form):
                raise AccessError(422, "VALIDATION_ERROR")
            description, location = form.get("description"), form.get("location")
            if (not isinstance(description, str) or not description.strip()
                    or not isinstance(location, str) or not location.strip()):
                raise AccessError(422, "VALIDATION_ERROR")
            observed_raw = form.get("observed_at")
            try:
                observed_at = None if observed_raw in (None, "") else utc_time(observed_raw)
            except ValueError:
                raise AccessError(422, "VALIDATION_ERROR") from None
            if observed_at is not None and observed_at > datetime.now(UTC):
                raise AccessError(422, "VALIDATION_ERROR")
            image_part = form.get("image")
            if image_part is not None and not isinstance(image_part, UploadFile):
                raise AccessError(422, "VALIDATION_ERROR")
            raw_image = None
            image_type = None
            if image_part is not None:
                raw_image = await image_part.read()
                image_type = image_part.content_type
        finally:
            await form.close()

        def persist():
            normalized = decode_upload(raw_image, image_type) if raw_image is not None else None
            provenance = ("synthetic" if raw_image is not None
                          and known_synthetic_fixture(raw_image, normalized) else "live")
            # Reuse the original durable receipt time when this deterministic signal is retried.
            provisional = resident_signal(actor=actor, idempotency_key=context.idempotency_key,
                description=description.strip(), location=location.strip(), received_at=datetime.now(UTC),
                observed_at=observed_at, image=normalized, provenance=provenance)
            with app.state.store_factory(settings.store_path) as store:
                try:
                    received_at = store.get_signal(provisional.id).received_at
                except KeyError:
                    received_at = provisional.received_at
                signal = resident_signal(actor=actor, idempotency_key=context.idempotency_key,
                    description=description.strip(), location=location.strip(), received_at=received_at,
                    observed_at=observed_at, image=normalized, provenance=provenance)
                return persist_signal(store, signal=signal, context=context, image=normalized,
                    image_root=settings.image_root, provenance=provenance)

        receipt = await to_thread(persist)
        saved = receipt.result.data
        assert isinstance(saved, c.SignalReceipt)
        return result_response(c.ToolResult(outcome="OK", data=IntakeReceiptView(
            receipt_id=saved.signal_id, signal_id=saved.signal_id, received_at=saved.received_at,
        )), status=202)

    @app.get("/api/signals/related", response_model=c.ToolResult[CandidateSignalsView])
    def related_signals(request: Request, signal_id: str):
        actor = require_action(request, Action.INVESTIGATE)
        boundary = AccessBoundary(actor, settings.district_id)
        with request_store(request) as store:
            boundary.signal(store, signal_id)
            candidates = []
            for item in store.related_signals(signal_id):
                try:
                    boundary.signal(store, item.id)
                    evidence_ids = tuple(e.id for e in store.evidence_for_entity(signal_id=item.id))
                    for evidence_id in evidence_ids:
                        boundary.evidence(store, evidence_id)
                except AccessError:
                    continue
                candidates.append(CandidateSignalView(id=item.id, source_role=item.effective_source_role,
                    source_author_id=item.source_author_id, text=item.raw_text, observed_at=item.observed_at,
                    image_evidence_ids=evidence_ids))
                if len(candidates) > 20:
                    break
            return c.ToolResult(outcome="OK", data=CandidateSignalsView(
                candidates=tuple(candidates[:20]), truncated=len(candidates) > 20))

    @app.get("/api/issues/similar", response_model=c.ToolResult[SimilarIssuesView])
    def similar_issues(request: Request, signal_id: str):
        actor = require_action(request, Action.INVESTIGATE)
        boundary = AccessBoundary(actor, settings.district_id)
        with request_store(request) as store:
            boundary.signal(store, signal_id)
            candidates = []
            for item in store.similar_issue_records(signal_id):
                try:
                    boundary.issue(store, item.id)
                except AccessError:
                    continue
                candidates.append(SimilarIssueView(id=item.id, status=item.status,
                    location=item.location, evidence_score=item.evidence_score))
                if len(candidates) > 20:
                    break
            return c.ToolResult(outcome="OK", data=SimilarIssuesView(
                candidates=tuple(candidates[:20]), truncated=len(candidates) > 20))

    @app.post("/api/issues", response_model=c.ToolResult[c.EntityResult], status_code=201)
    async def create_issue(request: Request):
        context = mutation_context(request, Action.INVESTIGATE, expected_revision=expected_revision(request),
            operation="create_issue_from_signal")
        body = await parse_json_request(request, IssueCreateRequest)
        try:
            def operation():
                with request_store(request) as store:
                    boundary = AccessBoundary(context.actor, settings.district_id)
                    if "issue_id" in request.path_params:
                        boundary.issue(store, request.path_params["issue_id"])
                    return create_issue_from_signal(store, signal_id=body.signal_id,
                        rationale=body.match_rationale, context=context)
            receipt = await to_thread(operation)
        except IdempotencyConflict:
            raise
        except ValueError:
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(receipt.result, status=201)

    @app.get("/api/jobs/{job_id}", response_model=c.ToolResult[CrewJobView])
    def read_job(request: Request, job_id: str):
        actor = require_action(request, Action.READ_JOB)
        with request_store(request) as store:
            return c.ToolResult[CrewJobView](outcome="OK",
                data=AccessBoundary(actor, settings.district_id).job(store, job_id))

    @app.get("/api/budget", response_model=c.ToolResult[c.BudgetAvailability])
    def read_budget(request: Request):
        require_action(request, Action.READ_ISSUE)
        with request_store(request) as store, store.transaction():
            return c.ToolResult[c.BudgetAvailability](outcome="OK",
                data=store.budget_availability(settings.district_id))

    @app.post("/api/issues/{issue_id}/plan", response_model=c.ToolResult[c.EntityResult], status_code=201,
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")],
                  "requestBody": {"required": True, "content": {"application/json": {
                  "schema": _openapi_request_schema(PlanRequest)}}}})
    async def plan_issue(request: Request, issue_id: str):
        context = mutation_context(request, Action.BUILD_PLAN, expected_revision=expected_revision(request))
        body = await parse_json_request(request, PlanRequest)
        try:
            def operation():
                with request_store(request) as store:
                    return build_resolution_plan(store, issue_id=issue_id,
                        classification_fact_id=body.classification_fact_id, context=context,
                        policy_path=settings.policy_path).result
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except ValueError:
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result, status=201 if result.outcome == "OK" else
                               409 if result.reason_code == "STALE_ISSUE_REVISION" else 403)

    @app.get("/api/plans/{plan_id}/vendors", response_model=c.ToolResult[VendorOptions])
    def eligible_vendors(request: Request, plan_id: str):
        actor = require_action(request, Action.LIST_VENDORS)
        with request_store(request) as store:
            return result_response(list_eligible_vendors(store, plan_id=plan_id, actor=actor,
                                                       policy_path=settings.policy_path))

    @app.post("/api/plans/{plan_id}/dispatch", response_model=c.ToolResult[c.EntityResult], status_code=201,
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")],
                  "requestBody": {"required": True, "content": {"application/json": {
                  "schema": _openapi_request_schema(DispatchRequest)}}}})
    async def dispatch_plan(request: Request, plan_id: str):
        context = mutation_context(request, Action.DISPATCH, expected_revision=expected_revision(request))
        body = await parse_json_request(request, DispatchRequest)
        try:
            def operation():
                with request_store(request) as store:
                    return dispatch_vendor(store, plan_id=plan_id, vendor_id=body.vendor_id, context=context,
                                           policy_path=settings.policy_path).result
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except ValueError:
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result, status=201 if result.outcome == "OK" else
                               409 if result.reason_code == "STALE_ISSUE_REVISION" else 403)

    @app.post("/api/jobs/{job_id}/accept", response_model=c.ToolResult[c.EntityResult],
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")]})
    async def accept_crew_job(request: Request, job_id: str):
        context = mutation_context(request, Action.ACCEPT_JOB, expected_revision=expected_revision(request))
        # This endpoint deliberately has no domain body. Never buffer an arbitrary
        # chunked body merely to reject it.
        content_length = _header(request, "content-length")
        if content_length is not None and (not content_length.isdigit() or int(content_length) != 0):
            raise AccessError(422, "VALIDATION_ERROR")
        async for chunk in request.stream():
            if chunk:
                raise AccessError(422, "VALIDATION_ERROR")
        try:
            def operation():
                with request_store(request) as store:
                    return accept_job(store, job_id=job_id, context=context).result
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except ValueError:
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/jobs/{job_id}/check-in", response_model=c.ToolResult[c.EntityResult],
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")]})
    async def crew_check_in(request: Request, job_id: str):
        context = mutation_context(request, Action.CHECK_IN, expected_revision=expected_revision(request))
        body = await parse_json_request(request, CheckinRequest)
        try:
            location = c.LocationRecord(lat=body.latitude, lon=body.longitude,
                                        accuracy_m=body.accuracy_m, provenance="live")
            def operation():
                with request_store(request) as store:
                    return check_in(store, job_id=job_id, location=location,
                        claimed_at=body.claimed_at, context=context).result
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except ValueError:
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/jobs/{job_id}/proof", response_model=c.ToolResult[c.EntityResult], status_code=202,
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")]})
    async def crew_proof(request: Request, job_id: str):
        context = mutation_context(request, Action.SUBMIT_PROOF, expected_revision=expected_revision(request))
        # Reject an unrelated crew before multipart parsing can allocate upload spools.
        with app.state.store_factory(settings.store_path) as store:
            AccessBoundary(context.actor, settings.district_id).require_job(store, job_id)
        content_type = (_header(request, "content-type") or "").split(";", 1)[0].strip().lower()
        if content_type != "multipart/form-data":
            raise AccessError(415, "MULTIPART_REQUIRED")
        content_length = _header(request, "content-length")
        limit = (2 * MAX_UPLOAD_BYTES) + MAX_MULTIPART_OVERHEAD
        if content_length and (not content_length.isdigit() or int(content_length) > limit):
            raise AccessError(413, "REQUEST_TOO_LARGE")
        try:
            form = await parse_proof_form(request)
        except MultiPartException as error:
            status = 422 if str(error) in {"invalid upload filename", "incomplete multipart body"} else 413
            raise AccessError(status, "VALIDATION_ERROR" if status == 422 else "REQUEST_TOO_LARGE") from None
        try:
            allowed = {"before", "after", "metadata"}
            if any(key not in allowed or len(form.getlist(key)) != 1 for key in form):
                raise AccessError(422, "VALIDATION_ERROR")
            if set(form.keys()) not in ({"before", "after", "metadata"}, {"after", "metadata"}):
                raise AccessError(422, "VALIDATION_ERROR")
            metadata_raw = form.get("metadata")
            if not isinstance(metadata_raw, str) or len(metadata_raw.encode("utf-8")) > 4096:
                raise AccessError(422, "VALIDATION_ERROR")
            try:
                metadata = ProofMetadata.model_validate_json(metadata_raw)
            except ValueError:
                raise AccessError(422, "VALIDATION_ERROR") from None
            before_part, after_part = form.get("before"), form.get("after")
            if before_part is not None and not isinstance(before_part, UploadFile):
                raise AccessError(422, "VALIDATION_ERROR")
            if not isinstance(after_part, UploadFile):
                raise AccessError(422, "VALIDATION_ERROR")
            if before_part is None and "before_observed_at" in metadata.model_fields_set:
                raise AccessError(422, "VALIDATION_ERROR")
            before_raw = await before_part.read() if before_part is not None else None
            before_type = before_part.content_type if before_part is not None else None
            after_raw, after_type = await after_part.read(), after_part.content_type
        finally:
            await form.close()

        try:
            def operation():
                before = decode_upload(before_raw, before_type) if before_raw is not None else None
                after = decode_upload(after_raw, after_type)
                before_provenance = ("synthetic" if before_raw is not None
                    and known_synthetic_fixture(before_raw, before) else "live")
                after_provenance = "synthetic" if known_synthetic_fixture(after_raw, after) else "live"
                images = ProofImages(before=before, after=after,
                    before_observed_at=metadata.before_observed_at,
                    after_observed_at=metadata.after_observed_at,
                    before_provenance=before_provenance if before is not None else None,
                    after_provenance=after_provenance,
                    before_observed_supplied="before_observed_at" in metadata.model_fields_set)
                with request_store(request) as store:
                    return submit_proof(store, job_id=job_id, images=images, context=context,
                                        image_root=settings.image_root).result
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except (UploadError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result, status=202)

    @app.post("/api/jobs/{job_id}/inspect", response_model=c.ToolResult[c.CompletionInspectionResult],
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")]})
    async def inspect_job_completion(request: Request, job_id: str):
        context = mutation_context(request, Action.INSPECT, expected_revision=expected_revision(request))
        body = await parse_json_request(request, InspectCompletionRequest)
        try:
            def operation():
                with request_store(request) as store:
                    return inspect_completion(store, job_id=job_id, submission_id=body.submission_id,
                        context=context, image_root=settings.image_root,
                        inspector=app.state.completion_inspector)
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result, status=200 if result.outcome == "OK" else 503 if result.outcome == "ERROR" else None)

    async def financial_response(operation):
        try:
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except KeyError:
            raise AccessError(404, "RESOURCE_NOT_FOUND") from None
        except ValueError:
            # Inconsistent stored finances/proof never become a fabricated business denial.
            raise AccessError(503, "FINANCIAL_STATE_INVALID") from None
        return result_response(result)

    financial_headers = {"parameters": [{"name": name, "in": "header", "required": True,
        "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")]}

    @app.post("/api/jobs/{job_id}/settle", response_model=c.ToolResult[c.EntityResult],
        openapi_extra=financial_headers | {"requestBody": {"required": True, "content": {"application/json": {
            "schema": _openapi_request_schema(InspectCompletionRequest)}}}})
    async def settle_job(request: Request, job_id: str):
        context = mutation_context(request, Action.SETTLE, expected_revision=expected_revision(request))
        body = await parse_json_request(request, InspectCompletionRequest)
        def operation():
            with request_store(request) as store:
                return release_payment(store, job_id=job_id, submission_id=body.submission_id,
                    context=context, policy_path=settings.policy_path).result
        return await financial_response(operation)

    async def no_financial_arguments(request):
        content_length = _header(request, "content-length")
        if content_length is not None and (not content_length.isdigit() or int(content_length) != 0):
            raise AccessError(422, "VALIDATION_ERROR")
        async for chunk in request.stream():
            if chunk:
                raise AccessError(422, "VALIDATION_ERROR")

    @app.post("/api/jobs/{job_id}/cancel", response_model=c.ToolResult[c.EntityResult], openapi_extra=financial_headers)
    async def cancel_unpaid_job(request: Request, job_id: str):
        context = mutation_context(request, Action.CANCEL, expected_revision=expected_revision(request))
        await no_financial_arguments(request)
        def operation():
            with request_store(request) as store:
                return cancel_job(store, job_id=job_id, context=context, policy_path=settings.policy_path).result
        return await financial_response(operation)

    @app.post("/api/issues/{issue_id}/close", response_model=c.ToolResult[c.EntityResult], openapi_extra=financial_headers)
    async def close_paid_issue(request: Request, issue_id: str):
        context = mutation_context(request, Action.CLOSE, expected_revision=expected_revision(request))
        await no_financial_arguments(request)
        def operation():
            with request_store(request) as store:
                return close_issue(store, issue_id=issue_id, context=context, policy_path=settings.policy_path).result
        return await financial_response(operation)

    @app.post("/api/jobs/{job_id}/exceptions", response_model=c.ToolResult[c.EntityResult], status_code=202,
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")],
                  "requestBody": {"required": True, "content": {"application/json": {
                      "schema": _openapi_request_schema(CompletionExceptionRequest)}}}})
    async def escalate_completion_exception(request: Request, job_id: str):
        context = mutation_context(request, Action.ESCALATE, expected_revision=expected_revision(request))
        body = await parse_json_request(request, CompletionExceptionRequest)
        try:
            def operation():
                with request_store(request) as store:
                    return escalate_to_operator(store, issue_id=store.get_job(job_id).issue_id,
                        job_id=job_id, submission_id=body.submission_id,
                        verification_id=body.verification_id, denial_event_id=body.denial_event_id,
                        reason_code=body.reason_code, context=context, policy_path=settings.policy_path).result
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result, status=202)

    @app.post("/api/issues/{issue_id}/exceptions", response_model=c.ToolResult[c.EntityResult], status_code=202,
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")],
                  "requestBody": {"required": True, "content": {"application/json": {
                      "schema": _openapi_request_schema(IssueExceptionRequest)}}}})
    async def escalate_issue_exception(request: Request, issue_id: str):
        context = mutation_context(request, Action.ESCALATE, expected_revision=expected_revision(request))
        body = await parse_json_request(request, IssueExceptionRequest)
        try:
            def operation():
                with request_store(request) as store:
                    return escalate_to_operator(store, issue_id=issue_id, kind=body.kind,
                        reason_code=body.reason_code, denial_event_id=body.denial_event_id,
                        context=context, policy_path=settings.policy_path).result
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result, status=202)

    @app.get("/api/exceptions/{exception_id}", response_model=c.ToolResult[c.ExceptionDetail])
    def read_exception(request: Request, exception_id: str):
        actor = require_action(request, Action.READ_ISSUE)
        with request_store(request) as store:
            return c.ToolResult[c.ExceptionDetail](outcome="OK",
                data=exception_detail(store, exception_id=exception_id, actor=actor,
                                      policy_path=settings.policy_path))

    @app.get("/api/issues/{issue_id}/exceptions", response_model=c.ToolResult[ExceptionListView])
    def list_issue_exceptions(request: Request, issue_id: str):
        actor = require_action(request, Action.READ_ISSUE)
        with request_store(request) as store:
            AccessBoundary(actor, settings.district_id).issue(store, issue_id)
            return c.ToolResult[ExceptionListView](outcome="OK", data=ExceptionListView(
                exceptions=tuple(exception_detail(store, exception_id=record.id, actor=actor,
                                                  policy_path=settings.policy_path)
                                 for record in store.exceptions_for_issue(issue_id))))

    @app.post("/api/exceptions/{exception_id}/request-completion",
              response_model=c.ToolResult[c.PendingEntityResult], status_code=202,
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")],
                  "requestBody": {"required": True, "content": {"application/json": {
                      "schema": _openapi_request_schema(RequestCompletionRequest)}}}})
    async def operator_request_completion(request: Request, exception_id: str):
        context = mutation_context(request, Action.REQUEST_COMPLETION, expected_revision=expected_revision(request))
        body = await parse_json_request(request, RequestCompletionRequest)
        try:
            def operation():
                with request_store(request) as store:
                    return request_completion(store, exception_id=exception_id, submission_id=body.submission_id,
                        expected_job_revision=body.expected_job_revision, context=context,
                        policy_path=settings.policy_path).result
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result, status=202)

    @app.post("/api/operator-decisions/{decision_id}/rework", response_model=c.ToolResult[c.EntityResult],
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")]})
    async def apply_operator_rework(request: Request, decision_id: str):
        context = mutation_context(request, Action.REWORK, expected_revision=expected_revision(request))
        content_length = _header(request, "content-length")
        if content_length is not None and (not content_length.isdigit() or int(content_length) != 0):
            raise AccessError(422, "VALIDATION_ERROR")
        async for chunk in request.stream():
            if chunk:
                raise AccessError(422, "VALIDATION_ERROR")
        try:
            def operation():
                with request_store(request) as store:
                    return request_rework(store, decision_id=decision_id, context=context,
                        policy_path=settings.policy_path).result
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/issues/{issue_id}/geocode", response_model=c.ToolResult[c.EntityResult])
    async def geocode_issue(request: Request, issue_id: str):
        context = mutation_context(request, Action.INVESTIGATE, expected_revision=expected_revision(request),
            operation="record_geocode")
        body = await parse_json_request(request, StoredSignalRequest)
        try:
            def operation():
                with request_store(request) as store:
                    boundary = AccessBoundary(context.actor, settings.district_id)
                    if "issue_id" in request.path_params:
                        boundary.issue(store, request.path_params["issue_id"])
                    _fact, receipt = record_geocode(store, issue_id=issue_id, signal_id=body.signal_id,
                        result=lambda: app.state.adapters.geocode(boundary.signal(store, body.signal_id)), context=context)
                    return receipt.result
            result = await to_thread(operation)
        except RevisionConflict:
            raise
        except IdempotencyConflict:
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/issues/{issue_id}/sources", response_model=c.ToolResult[c.EntityResult])
    async def link_candidate_signal(request: Request, issue_id: str):
        context = mutation_context(request, Action.INVESTIGATE, expected_revision=expected_revision(request),
            operation="link_signal")
        body = await parse_json_request(request, LinkSignalRequest)
        try:
            def operation():
                with request_store(request) as store:
                    boundary = AccessBoundary(context.actor, settings.district_id)
                    if "issue_id" in request.path_params:
                        boundary.issue(store, request.path_params["issue_id"])
                    receipt = link_signal_to_issue(store, issue_id=issue_id, signal_id=body.signal_id,
                        rationale=body.match_rationale, context=context)
                    return receipt.result
            result = await to_thread(operation)
        except RevisionConflict:
            raise
        except IdempotencyConflict:
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/issues/{issue_id}/service-records/search", response_model=c.ToolResult[c.EntityResult])
    async def lookup_service_record(request: Request, issue_id: str):
        context = mutation_context(request, Action.INVESTIGATE, expected_revision=expected_revision(request),
            operation="record_service_lookup")
        body = await parse_json_request(request, StoredSignalRequest)
        try:
            def operation():
                with request_store(request) as store:
                    boundary = AccessBoundary(context.actor, settings.district_id)
                    if "issue_id" in request.path_params:
                        boundary.issue(store, request.path_params["issue_id"])
                    _record, receipt = record_service_lookup(store, issue_id=issue_id, signal_id=body.signal_id,
                        result=lambda: app.state.adapters.service_record(boundary.signal(store, body.signal_id)), context=context)
                    return receipt.result
            result = await to_thread(operation)
        except RevisionConflict:
            raise
        except IdempotencyConflict:
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/issues/{issue_id}/classification", response_model=c.ToolResult[c.EntityResult])
    async def classify_issue(request: Request, issue_id: str):
        context = mutation_context(request, Action.INVESTIGATE, expected_revision=expected_revision(request),
            operation="save_classification")
        body = await parse_json_request(request, ClassificationProposalRequest)
        try:
            def operation():
                with request_store(request) as store:
                    boundary = AccessBoundary(context.actor, settings.district_id)
                    if "issue_id" in request.path_params:
                        boundary.issue(store, request.path_params["issue_id"])
                    issue = store.get_issue_record(issue_id)
                    source = boundary.signal(store, body.signal_id)
                    fact = c.ClassificationFact(id=stable_id("classification", issue_id, context.idempotency_key),
                        issue_id=issue_id, signal_id=body.signal_id, category=body.category,
                        visible_objects=body.visible_objects, hazards=body.hazards, primary_target=body.primary_target,
                        full_cleanup_scope=body.full_cleanup_scope, marked_work_area=body.marked_work_area,
                        large_object_count=body.large_object_count,
                        supporting_evidence_ids=body.supporting_evidence_ids, unknowns=body.unknowns,
                        source_issue_revision=issue.state_revision, provenance=source.provenance, proposed_by=context.actor,
                        created_at=datetime.now(UTC))
                    _saved, receipt = save_classification(store, fact, context=context)
                    return receipt.result
            result = await to_thread(operation)
        except RevisionConflict:
            raise
        except IdempotencyConflict:
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/issues/{issue_id}/jurisdiction", response_model=c.ToolResult[c.EntityResult])
    async def determine_jurisdiction(request: Request, issue_id: str):
        context = mutation_context(request, Action.INVESTIGATE, expected_revision=expected_revision(request),
            operation="save_jurisdiction")
        body = await parse_json_request(request, JurisdictionProposalRequest)
        try:
            def operation():
                with request_store(request) as store:
                    boundary = AccessBoundary(context.actor, settings.district_id)
                    if "issue_id" in request.path_params:
                        boundary.issue(store, request.path_params["issue_id"])
                    issue = store.get_issue_record(issue_id)
                    classification = store.get_classification_fact(body.classification_fact_id)
                    fact = c.JurisdictionFact(id=stable_id("jurisdiction", issue_id, context.idempotency_key),
                        issue_id=issue_id, classification_fact_id=body.classification_fact_id,
                        responsibility=body.responsibility, supporting_fact_ids=body.supporting_fact_ids,
                        unknowns=body.unknowns, source_issue_revision=issue.state_revision,
                        provenance=classification.provenance, proposed_by=context.actor, created_at=datetime.now(UTC))
                    _saved, receipt = save_jurisdiction(store, fact, context=context)
                    return receipt.result
            result = await to_thread(operation)
        except RevisionConflict:
            raise
        except IdempotencyConflict:
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/issues/{issue_id}/decisions", response_model=c.ToolResult[c.EntityResult])
    async def decide_issue(request: Request, issue_id: str):
        context = mutation_context(request, Action.INVESTIGATE, expected_revision=expected_revision(request),
            operation="decide")
        body = await parse_json_request(request, DecisionProposalRequest)
        try:
            def operation():
                with request_store(request) as store:
                    boundary = AccessBoundary(context.actor, settings.district_id)
                    if "issue_id" in request.path_params:
                        boundary.issue(store, request.path_params["issue_id"])
                    decide(store, issue_id=issue_id, proposed_type=body.decision_type,
                        summary=body.summary, evidence_ids=body.evidence_ids, context=context)
                    return store.request_for_operation(context).result
            result = await to_thread(operation)
        except RevisionConflict:
            raise
        except IdempotencyConflict:
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/issues/{issue_id}/operational-decisions",
              response_model=c.ToolResult[c.OperationalDecisionResult], operation_id="decide_operational",
              openapi_extra={"parameters": [{"name": name, "in": "header", "required": True,
                  "schema": {"type": "string"}} for name in ("Idempotency-Key", "X-Steward-Expected-Revision")]
                  + [{"name": "X-Steward-Invocation-Id", "in": "header", "required": False,
                      "schema": {"type": "string"}}],
                  "requestBody": {"required": True, "content": {"application/json": {
                      "schema": _openapi_request_schema(OperationalDecisionProposalRequest)}}}})
    async def decide_operational(request: Request, issue_id: str):
        context = mutation_context(request, Action.DECIDE_OPERATIONAL,
            expected_revision=expected_revision(request))
        body = await parse_json_request(request, OperationalDecisionProposalRequest)
        try:
            def operation():
                with request_store(request) as store:
                    return record_operational_decision(store, issue_id=issue_id, proposal=body,
                                                       context=context).result
            result = await to_thread(operation)
        except (IdempotencyConflict, RevisionConflict):
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/issues/{issue_id}/investigation-action", response_model=c.ToolResult[c.EntityResult])
    async def apply_decision(request: Request, issue_id: str):
        context = mutation_context(request, Action.APPLY_INVESTIGATION_DECISION,
            expected_revision=expected_revision(request), operation="apply_investigation_decision")
        body = await parse_json_request(request, InvestigationActionRequest)
        try:
            def operation():
                with request_store(request) as store:
                    boundary = AccessBoundary(context.actor, settings.district_id)
                    if "issue_id" in request.path_params:
                        boundary.issue(store, request.path_params["issue_id"])
                    receipt = apply_investigation_decision(store, issue_id=issue_id,
                        decision_id=body.decision_id, context=context)
                    return receipt.result
            result = await to_thread(operation)
        except RevisionConflict:
            raise
        except IdempotencyConflict:
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/issues/{issue_id}/official-dispute", response_model=c.ToolResult[c.EntityResult])
    async def dispute_official_status(request: Request, issue_id: str):
        context = mutation_context(request, Action.APPLY_INVESTIGATION_DECISION,
            expected_revision=expected_revision(request), operation="official_dispute")
        body = await parse_json_request(request, InvestigationActionRequest)
        try:
            def operation():
                with request_store(request) as store:
                    boundary = AccessBoundary(context.actor, settings.district_id)
                    if "issue_id" in request.path_params:
                        boundary.issue(store, request.path_params["issue_id"])
                    decision = store.get_decision(body.decision_id)
                    if decision.issue_id != issue_id or decision.decision_type != "DISPUTE_OFFICIAL_STATUS":
                        raise ValueError("official dispute requires its saved decision")
                    receipt = apply_investigation_decision(store, issue_id=issue_id,
                        decision_id=body.decision_id, context=context)
                    return receipt.result
            result = await to_thread(operation)
        except RevisionConflict:
            raise
        except IdempotencyConflict:
            raise
        except (KeyError, ValueError):
            raise AccessError(422, "VALIDATION_ERROR") from None
        return result_response(result)

    @app.post("/api/signals/{signal_id}/intake-inspection", response_model=c.ToolResult[c.EntityResult])
    async def inspect_intake(request: Request, signal_id: str):
        context = mutation_context(request, Action.INSPECT, operation="inspect_intake_photo")
        try:
            def operation():
                with request_store(request) as store:
                    boundary = AccessBoundary(context.actor, settings.district_id)
                    if "issue_id" in request.path_params:
                        boundary.issue(store, request.path_params["issue_id"])
                    return inspect_intake_photo(store, signal_id=signal_id, image_root=settings.image_root,
                        inspector=app.state.intake_inspector, context=context)
            result = await to_thread(operation)
            return result_response(result, status=503 if result.outcome == "ERROR" else None)
        except KeyError:
            raise AccessError(404, "RESOURCE_NOT_FOUND") from None

    # Refuse a server change that has not frozen its public client operation ID.
    for route in app.routes:
        if isinstance(route, APIRoute) and route.operation_id is None:
            method = next(iter(sorted(route.methods - {"HEAD", "OPTIONS"})), "get").lower()
            try:
                route.operation_id = OPERATION_IDS[(method.upper(), route.path)]
            except KeyError as error:
                raise RuntimeError(f"missing explicit operation ID for {method} {route.path}") from error
    _configure_openapi(app)
    return app
