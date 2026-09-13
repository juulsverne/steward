# Steward API identity boundary

The local API implements the labeled demo persona boundary, health, and session reads.
It is a sandbox with publicly selectable seeded identities, **not verified identity**.
Anyone using the selector can choose another demo persona. Do not submit private
information. Resource permissions still apply to the selected actor on every request.
The generic starter `/ask` route is removed. Business operations and full case/timeline
read routes belong to later build cards; no model runs during persona selection.

## Local setup

Run from the repository root. Install the locked web/development extras with
`uv sync --locked --extra web --extra dev`. Create `.steward` explicitly for the named
SQLite database. Preserve any existing `.env`; copy only the needed empty settings
from `.env.example` into your private configuration.

Set `STEWARD_ORIGIN=http://localhost:8000`, `STEWARD_LOCAL_HTTP=true`, and
`STEWARD_STORE_PATH=.steward/steward.sqlite3`. Generate **two independent values once**
with Python's `secrets.token_hex(32)` and save them as `STEWARD_SESSION_SECRET` and
`STEWARD_SERVICE_TOKEN` in the ignored private `.env` or persistent process environment.
Each must be 64 lowercase hexadecimal characters from 32 random bytes. Empty, equal,
low-diversity and repeated-pattern placeholders are rejected. Never copy test values.
Write generated values directly into your private configuration using an exclusive-create
setup process; do not print them into agent tool output or paste them into chat. If a
configuration file exists, preserve it and arrange an explicit private update rather
than overwriting it. No setup command in this card generates credentials for you.
Protect this configuration with the owning user's filesystem permissions. The API
never creates, overwrites or regenerates secrets or `.env` files.

Start with `uv run --no-sync uvicorn agent.server:app --host 127.0.0.1 --port 8000 --no-proxy-headers`.
Web settings are validated at app creation; normal CLI/offline imports and existing
model Settings constructors do not require web secrets. Startup loads the versioned
`data/policy.yaml` and binds this one named Store to `south_loop_demo`. This is not a
multi-district database.

Restarting with the same secrets preserves unexpired human cookies and service access.
Rotating the signing secret invalidates human cookies without changing domain records.
Rotating the service token requires updating the trusted agent transport separately.
There is no per-session revocation database; an earlier signed cookie remains valid
until expiry or key rotation. Do not regenerate secrets on every launch.

Hosted configuration requires one exact HTTPS origin and `STEWARD_LOCAL_HTTP=false`.
It uses `__Host-steward-demo; Secure; HttpOnly; SameSite=Strict; Path=/` without Domain.
Explicit loopback HTTP development uses the separate `steward-demo-local` cookie.
Cookies expire after 12 hours and only intentional persona selection renews them.
Deployment, persistent secrets on the selected host, and TLS remain hosting gates.

## Shipped endpoints

| Endpoint | Behavior |
|---|---|
| GET `/health` | Minimal `ToolResult` with `{ok:true}`; no model call or database probe |
| GET `/api/demo/session` | Safe human persona catalog, sandbox notice and selected actor or null |
| POST `/api/demo/persona` | Strict `{persona_id: string}` selects one configured human, signs cookie |

The POST requires `Content-Type: application/json`, an exact allowed `Origin`,
`X-Steward-Request: 1`, and an `Idempotency-Key` of 1–128 characters matching
`[A-Za-z0-9][A-Za-z0-9._:-]*`. Its body is limited to 4096 bytes. It accepts no authority
overrides or service persona. Selection changes only a credential: no case record,
domain idempotency receipt, event or invocation is created. Repeating it may renew expiry.

Human unsafe requests use the same Origin/custom-header protection, including bootstrap.
Origin/Host allowlists come from configuration, never client Host or forwarded headers.
Missing/null/malformed/unlisted origins are rejected. There is no wildcard or reflective
CORS. `STEWARD_DEVELOPMENT_ORIGINS` accepts explicit loopback HTTP origins only in local
mode; use a same-origin Vite `/api` proxy, since this setting does not enable CORS.
Reverse proxies must preserve the configured external Host. Proxy-header interpretation
is disabled in the local launch command; hosted proxy trust must be explicitly configured.

Only trusted agent HTTP clients use `Authorization: Bearer <STEWARD_SERVICE_TOKEN>`.
Never put that token or AWS credentials in browser code, cookies, query strings, reports
or OpenAPI examples. Tokens and human cookies cannot be mixed. Bearer requests with an
Origin header are rejected. Service cannot select a human persona or impersonate crew
check-in/proof or operator decisions. Operators cannot dispatch, inspect, settle or close.

## Interfaces for the next cards

`create_app(ApiSettings, store_factory=Store)` owns transport/request IDs and response
handling. `require_action(request, Action)` resolves credentials and checks role/district.
`mutation_context(request, Action, expected_revision=...)` additionally requires the
idempotency key and returns B1's `MutationContext`; `request.state.request_id` stays a
transport-only identifier. Route code supplies the operation and validated revision,
never a caller-supplied ActorContext. B11/B12 will add saved invocation context validation.

Use `with request_store(request) as store:` **inside one synchronous route/worker call**.
It opens and closes one SQLite connection on that thread, including failure paths.
Do not use it as a FastAPI yield dependency: dependency entry and route execution can
run on different workers. Async upload handlers must hand the entire synchronous
storage operation to one worker after upload handling. SQLite thread checks stay enabled.
Session/health handlers never open a Store.

`AccessBoundary(server_actor, configured_district)` supplies role checks and explicit
`receipt`, `issue`, `job`, and `evidence` projections plus `require_job` ownership checks.
Residents get only their saved submitter-owned receipt, with no history endpoint.
Crew get only their vendor's job facts and saved before/current proof associations.
Supplying a job ID never grants access to an unrelated evidence ID. Operators/service
use the configured district and saved plan districts; absent and out-of-scope resources
both return the same 404 shape. `Store.plans_for_issue` is a typed internal read for this
check. Projections exclude raw reporter messages, storage references/hashes and internal
model metadata. Later byte-serving routes must use the same evidence boundary.
For retained signal-only evidence associations, `Store.issue_for_signal` resolves the
current canonical link and applies the saved issue district checks. An immutable intake
receipt or historical association with no issue ID does not prove a signal is still unlinked.

These helpers are permission primitives, not dispatch/settlement/proof policy approval.
Every later domain mutation must recheck ownership, current state/revision and deterministic
gates inside the same Store writer transaction as the effect, audit event and persisted
actor-scoped idempotency receipt. No network/model work belongs inside that lock.
Full operational timelines, exceptions, collections, invocation views and business
routes remain with their owning cards. Test-only harness routes are not in the shipped app.

All responses carry a fresh server `X-Request-ID`, `Cache-Control: no-store`, and
`X-Content-Type-Options: nosniff`. Caller request IDs are not authoritative. Domain replies
use B1's typed `ToolResult`; error bodies do not echo submitted values, SQL, traces or secrets.

| HTTP | Outcome |
|---|---|
| 200 (201/202 when explicitly committed/documented by later routes) | OK |
| 200 | NEEDS_REVIEW |
| 401 / 403 / 409 | DENIED: credential / permission / revision, key or state conflict |
| 404 | NOT_FOUND, including out-of-scope records |
| 400 / 405 / 413 / 415 / 422 / 429 | ERROR; mixed credentials use DENIED at 400 |
| 500 / 503 | ERROR: unexpected failure / storage unavailable |

Signing uses [ItsDangerous timed signatures](https://itsdangerous.palletsprojects.com/en/stable/timed/).
Validation errors use a sanitized typed envelope following
[FastAPI's exception-handler boundary](https://fastapi.tiangolo.com/tutorial/handling-errors/).
