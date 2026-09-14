# Steward API identity boundary

The local API implements the labeled demo persona boundary, authenticated signal intake, and
service-only investigation facts and decisions.
It is a sandbox with publicly selectable seeded identities, **not verified identity**.
Anyone using the selector can choose another demo persona. Do not submit private
information. Resource permissions still apply to the selected actor on every request.
The generic starter `/ask` route is removed. Dispatch, proof, settlement and full case/timeline reads belong to later build cards. Persona selection and receipt-first intake do not run a model.

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

Create the labeled demo dataset with the [named seed/reset commands](../data/README.md) before starting the API. The seed is a 65-point CANDIDATE; no monitoring decision or full workflow is implied.

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

Investigation mutations enforce the configured service role and saved issue/plan/signal/
evidence scope, including replay. Source linking, classification, jurisdiction, decision
proposals and investigation actions require `X-Steward-Expected-Revision` (the issue
revision); missing headers fail validation. Fact versions are allocated under the writer
lock in one per-issue order across geocode/classification/jurisdiction. Source issue
revisions remain the input revisions, separate from the resulting issue revisions returned
in receipts. Identical keys return saved results after later state/configuration changes;
changed caller inputs conflict. Adapter outputs are frozen at the first execution.

`CurrentIssueFacts` is an internal typed producer for later plan/context consumers. It
publishes `unresolved_hazards` and `hazard_sources` (classification fact or successful intake
inspection IDs); benign reclassification cannot clear an earlier known hazard. Current
jurisdiction must reference the current classification and current supporting facts.
Investigation actions cannot reopen terminal issues or overwrite an active job workflow.
Direct service decisions have an `INVESTIGATION_REQUESTED` cause distinct from their
`INVESTIGATION_DECIDED` result; runtime metadata remains absent unless actually supplied
through a validated saved invocation.

Intake inspection uses a short durable claim, no database lock during inference, and an
immutable result/event/request receipt. Simultaneous requests for the same cache basis
receive HTTP 503 `ERROR / INSPECTION_IN_PROGRESS` without waiting or starting another call;
this temporary response is not a committed final receipt. Success cache reuse creates a
requesting signal/evidence record with `cached_from_id`; original inference usage stays on
the source record. Cache identity covers stored bytes and full model/profile/region,
prompt/request/schema/preprocessing/configuration versions. Errors receive HTTP 503 with
their persisted event IDs; replay retains that error, while a new key may attempt recovery.
A 120-second expired claim is recorded as `INSPECTION_INTERRUPTED` with unknown usage. A
late result is retained for attribution but fenced from the receipt and success cache.
No transport error creates an operator action or fabricated visual findings. Inspection
does not run automatically during upload. Candidate reads filter eligible scoped records
before the 20-result bound and return `truncated` when further matches exist.

| Endpoint | Behavior |
|---|---|
| GET `/health` | Minimal `ToolResult` with `{ok:true}`; no model call or database probe |
| GET `/api/demo/session` | Safe human persona catalog, sandbox notice and selected actor or null |
| POST `/api/demo/persona` | Strict `{persona_id: string}` selects one configured human, signs cookie |
| POST `/api/signals` | Authenticated multipart resident intake; returns only the saved receipt ID and pending acknowledgment |
| GET `/api/signals/related`, GET `/api/issues/similar` | Service-only bounded candidate summaries from stored IDs; no raw image bytes or references |
| POST `/api/issues` | Service-only creation from one stored unlinked physical-observation signal and concise rationale |
| POST `/api/issues/{id}/geocode`, `/service-records/search` | Service-only trusted seeded adapter facts keyed to a stored linked signal |
| POST `/api/issues/{id}/sources` | Service-only explicit link of one stored signal to a case, with a saved match rationale |
| POST `/api/issues/{id}/classification`, `/jurisdiction`, `/decisions` | Service-only saved B4 proposals and gate-validated investigation decision intents; decision intent alone does not mutate lifecycle state |
| POST `/api/issues/{id}/operational-decisions` | Service-only durable operational proposal with typed saved basis and current server gates; it never dispatches, settles, reworks, or closes |
| POST `/api/issues/{id}/investigation-action`, `/official-dispute` | Service-only, revision-checked application of an eligible saved investigation decision |
| POST `/api/signals/{id}/intake-inspection` | Service-only configured image inspection of stored evidence; exact-version results are cached |

`POST /api/signals` requires the same human Origin/custom-header and idempotency protections as
other browser mutations. It accepts required nonblank `description` and `location`, optional timezone-aware `observed_at`,
and one optional JPEG/PNG `image`. The raw image cap is 10 MiB. The server validates the decoded
single-frame bytes, removes metadata while normalizing to JPEG, derives the persisted digest and
perceptual fingerprint, and writes the private object before atomically committing its evidence
association, signal receipt, and pending invocation. Client filenames, image paths, hashes,
provenance, source author/role, issue state, score, and receipt time are ignored or rejected.

The response is `202` only after that durable commit. Its `receipt_id` deliberately equals the
stable `signal_id`; it includes `received_at`, `accepted: true`, and `processing: "PENDING"`.
It does not expose storage references, image hashes, actor history, issue linkage, or invocation
metadata. An identical actor/key/payload retry returns this same response; a changed payload
conflicts. Unknown locations are retained as reported text and receive no geocode fact.

`POST /api/demo/persona` requires `Content-Type: application/json`, an exact allowed `Origin`,
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

## Agent HTTP tool transport (B10 Stage B)

`agent.tools.build_steward_tool_session(TrustedTransport(...))` creates one async-closeable
`InvocationToolSession` for one trusted runner invocation. `TrustedTransport` is supplied by
the runner, not a model tool call: it holds the one validated API origin, service token and
required saved invocation ID. The session owns exactly one HTTPX client and captures those
values privately in domain `AgentTool` adapters. Its tool inputs contain only domain IDs,
bounded proposals and observed revisions; they never accept an origin, token, actor,
invocation ID, idempotency key, retry count, lease, fence or deadline.

The package retains starter `agent.tools.TOOLS` for compatibility; the new session exposes
25 domain tools, including the thirteen architecture tools. B11 will replace the starter
consumer with `session.tools`. The registry covers investigation, planning, dispatch,
completion inspection, settlement, closure, escalation, rework and narrow saved-state helpers.
It intentionally has no generic URL/HTTP, browser, shell, filesystem, crew proof, human
check-in or operator-choice tool. A tool parses raw JSON strictly before any lifecycle or HTTP
action, rejects extra fields and nonfinite values, and preserves every API outcome with its
reason, gates and event/evidence IDs. Saving an operational decision is still an intent, not
an action.

The client disables redirects and ambient proxies, verifies HTTPS and enforces finite
connect/read/write/pool plus whole-attempt and absolute invocation deadlines. The defaults are
20 seconds per attempt and 120 seconds per invocation; a trusted `deadline_at` can shorten the
remaining invocation budget. It requests identity encoding and stops streaming at 256 KiB,
rejecting compressed responses instead of decompressing an unbounded payload. Raw tool inputs
are capped at 128 KiB, twelve nesting levels, 64 items per collection and 2,000 characters per
string, with stricter identifier and shared DTO constraints. No error exposes a raw remote body.

Tool name, OpenAPI operation ID, receipt operation and response DTO are explicit mappings.
The API re-exports the exact `agent.http_protocol.OPERATION_IDS` registry. For example,
`release_payment` maps to receipt operation `settle`; both escalation endpoints map to
`escalate_to_operator`. Operational-intent headers derive the same issue/job revision from the
typed basis. Intake inspection, rework, close and cancel send no body. All successful results
use their operation's full shared DTO; typed denials and inspection errors remain observable.

Each immutable logical command receives a compatible private key. Repeated calls/recovery
preserve that key, original invocation, command and three-attempt allowance. A saved terminal
result returns without HTTP. Only actual transient transport uncertainty or an inspection's
live `503 ERROR / INSPECTION_IN_PROGRESS` can retry; terminal errors, malformed output and
DENIED/NEEDS_REVIEW cannot. Separate legitimate calls with identical arguments retain separate
identities. The private `session.recover(logical_request_id)` uses this same transport/parser.

The async lifecycle has `prepare(call_ref, command) -> PreparedRequest`,
`load(logical_request_id) -> PreparedRequest`, `begin_attempt(logical_request_id) -> AttemptPermit`
and `finish_attempt(attempt_id, observation) -> CompletionAck`. Each attempt records its ordinal,
HTTP status/request ID when available, latency, result and uncertainty; an attempted send is
not proof of a commit. Failed acknowledgment preserves an unresolved observation and exposes a
safe error, never an unacknowledged success. Cancellation retains uncertainty and uses at most
50 ms of the remaining invocation budget for acknowledgment cleanup. No receipt ID or server
fingerprint is invented from a client hash or event ID.

Pass one `lifecycle_factory(client)` to attach B12's future coordinator to the same owned
transport, or inject one lifecycle directly. `InMemoryRequestLifecycle` is the explicit Stage-B
default and is **not restart durable**. B12 must require its durable implementation, enforce
actual lease/fencing headers on the server and record durable traces; current optional permit
fields do not claim those server controls exist. B11 still owns context refresh and agent
execution. Test injection through `http_transport` supplies no second production client.

## Interfaces for the next cards

`create_app(ApiSettings, store_factory=Store)` owns transport/request IDs and response
handling. `require_action(request, Action)` resolves credentials and checks role/district.
`mutation_context(request, Action, expected_revision=...)` additionally requires the
idempotency key and returns B1's `MutationContext`; `request.state.request_id` stays a
transport-only identifier. Route code supplies the operation and validated revision,
never a caller-supplied ActorContext. A service request may supply one
`X-Steward-Invocation-Id`; duplicate header values are rejected, human requests cannot
supply it, and the domain validates its persisted cause. It is not a lease or fence;
B12 adds those current-claim checks later.

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

## Operational intents (B10 Stage A)

`POST /api/issues/{issue_id}/operational-decisions` records one service-owned proposed
`REQUEST_DISPATCH`, `REQUEST_SETTLEMENT`, `REQUEST_OPERATOR`, `REQUEST_REWORK`, or
`RESOLVE` decision. Its JSON body has only a summary of at most 2,000 characters, up to
64 optional stored evidence IDs,
and a discriminated basis. The basis carries the applicable saved plan/vendor, job/proof/
verification, authentic denial, operator choice, or payment reference plus the caller's
expected issue or job revision. `X-Steward-Expected-Revision` is required and must match
that basis. The server resolves every referenced record, records actual issue/job revisions,
and returns an `OperationalDecisionResult` with the immutable `DecisionRecord` and its
current deterministic gate.

Canonical intake evidence can be cited through its saved signal-to-issue link; unlinked
or other-issue evidence cannot. Dispatch and pre-job escalation previews share their
server evaluators with actual actions. A genuine old proposal records its expected and
actual revisions with failing freshness gates. Historical completion/budget denials and
operator choices retain their immutable provenance checks, including on exact replay;
later rework does not make an authentic old denial corrupt. Damaged financial state is
an error and does not produce an invented successful gate.

`/openapi.json` publishes every public operation's explicit ID, JSON or multipart body,
required transport headers and typed response envelope. References and discriminator
mappings resolve against named components. The accept, rework, cancel, close and intake
inspection operations have no domain body; proof metadata remains a bounded JSON string
within the multipart form. Stage B supplies HTTP registration; B12 owns durable retries.

The HTTP result `OK / DECISION_SAVED` means only that the proposal and receipt were saved.
An in-scope proposal that is currently ineligible still receives a saved decision with a
failing gate; it performs no business action. Missing, foreign, contradictory, or corrupt
references are rejected. For an exact replay, current actor, invocation cause, and immutable
references are checked again, then the original result is returned even if dispatch, payment,
or rework has since changed eligibility. A new matching-but-old issue/job revision is also
saved, with the expected and actual revision retained in its basis and a failed stale gate.
Actual mutation endpoints keep their normal compare-and-swap behavior.

Public request DTOs and safe read projections live in `agent.http_contracts`, including
`OperationalDecisionProposalRequest`, planning/dispatch/proof/exception requests, B4 proposal
requests, candidate/exception/session/job views, and vendor options. This module has no
FastAPI, Store, operations, or actor-boundary import, so the later HTTP client can import its
wire contracts without importing the server. Existing `agent.api` request imports remain
compatible re-exports. All public API operations publish frozen unique OpenAPI operation IDs;
the new route is `decide_operational`.

All responses carry a fresh server `X-Request-ID`, `Cache-Control: no-store`, and
`X-Content-Type-Options: nosniff`. Caller request IDs are not authoritative. Domain replies
use B1's typed `ToolResult`; error bodies do not echo submitted values, SQL, traces or secrets.

| HTTP | Outcome |
|---|---|
| 200 (201/202 where explicitly committed and documented) | OK |
| 200 / 202 | NEEDS_REVIEW, including a saved exception awaiting the operator |
| 401 / 403 / 409 | DENIED: credential / permission / revision, key or state conflict |
| 404 | NOT_FOUND, including out-of-scope records |
| 400 / 405 / 413 / 415 / 422 / 429 | ERROR; mixed credentials use DENIED at 400 |
| 500 / 503 | ERROR: unexpected failure / storage unavailable |

Signing uses [ItsDangerous timed signatures](https://itsdangerous.palletsprojects.com/en/stable/timed/).
Validation errors use a sanitized typed envelope following
[FastAPI's exception-handler boundary](https://fastapi.tiangolo.com/tutorial/handling-errors/).

## Plans and simulated dispatch (B5)

These routes consume the saved B4 classification, compatible jurisdiction, current
trusted geocode and successful intake inspection provenance. They perform no inference.
The service bearer is required for planning, vendor options and dispatch. Both POSTs
require `Idempotency-Key` and `X-Steward-Expected-Revision`; that revision always names
the **issue**, including on the plan-addressed dispatch route. Bodies reject extra fields.

| Route | Body / response data |
|---|---|
| POST `/api/issues/{issue_id}/plan` | `{"classification_fact_id":"saved-id"}` → `EntityResult` naming the immutable plan, revision 0 |
| GET `/api/plans/{plan_id}/vendors` | `VendorOptions`: complete saved plan, current `issue_revision`, eligible seeded vendor facts in distance/workload/performance/ID order |
| POST `/api/plans/{plan_id}/dispatch` | `{"vendor_id":"south_loop_services"}` → `EntityResult` naming the POSTED job, revision 0 |
| GET `/api/jobs/{job_id}` | `CrewJobView`: own-vendor crew, configured operator or service; scope, primary target, marked area, frozen coordinates/precision, equipment, crew count, price, proof requirements, plan/reservation IDs and job revision |
| GET `/api/budget` | Configured operator/service only; `BudgetAvailability` with initial, reserved, spent and available integer cents |

Successful POSTs return 201. A known authorized domain refusal saves a DENIED receipt
and audit event, returns 403, and changes no financial state. A stale expected issue
revision returns 409 with that persisted denial. Changed input under an existing key
returns 409 `IDEMPOTENCY_CONFLICT`. Invalid/missing fields return 422; absent or
out-of-scope resources return 404. Exact retries recheck current actor/resource scope
and caller fingerprint, then return the original ToolResult and event IDs verbatim.

`PlanBasis` records classification, jurisdiction and geocode IDs, each fact's version
and original source issue revision, plus issue revisions before/after plan creation.
Those fact versions are independent of issue revisions. It also retains supporting
evidence IDs and `PlanInspectionReference` entries separating the requesting inspection
and canonical signal from the original successful inference and finished claim. Cached
associations reuse the original usage receipt. The service-only vendor response exposes
these typed references; crew job projections omit internal evidence/model provenance.
Older plans without a basis remain readable but cannot qualify for B5 dispatch.

The primary verification target is separate from full cleanup scope and marked area.
Dispatch coordinates and accuracy are frozen from the referenced trusted geocode;
completion consumers must use that snapshot. The server derives integer cents and
equipment from the rate card and saved interpreted quantity: one large couch is
6000 + 1200 = 7200 cents, with truck/two crew and all standard proof requirements.
The list supplies vendor facts for the model's choice; it does not automatically select
or reserve a vendor. Choosing any currently eligible listed vendor is supported.

Dispatch rechecks current evidence through the shared read-only scorer, compatible
responsibility, all preserved unresolved hazards, location, plan/fact freshness, vendor,
quote and journal under one SQLite writer transaction. It commits the POSTED job,
RESERVED reservation, RESERVE ledger entry, `SIMULATED_DISPATCH` event, issue transition
to RESOLUTION_ACTIVE and idempotency receipt together. Denied attempts preserve the
actual plan/vendor, expected/current issue revisions, quote, budget snapshot, hazard
sources, score components and policy gates in `EventFacts.dispatch` and sibling fields.
No crew acceptance or pending runtime invocation is manufactured by dispatch.

## Crew acceptance and proof (B6)

Crew browser routes require the existing authenticated cookie, `Origin`,
`X-Steward-Request`, `Idempotency-Key`, and `X-Steward-Expected-Revision`.  That revision
is always the **job** revision. `POST /api/jobs/{id}/accept` has no domain body and moves
only `POSTED` to `ASSIGNED`. `POST /api/jobs/{id}/check-in` accepts only
`latitude`, `longitude`, optional `accuracy_m`, and optional timezone-aware `claimed_at`;
the location/time remain crew claims while `checked_in_at` is a separate server receipt time.
Neither route runs a model or creates an invocation.

`POST /api/jobs/{id}/proof` is bounded multipart. A first proof from `CHECKED_IN` contains
distinct `before` and `after` JPEG/PNG files plus strict JSON metadata with optional
`before_observed_at` and `after_observed_at`; a B8-opened rework accepts only a new `after`
and optional `after_observed_at`. The server normalizes and privately stores bytes before a
single transaction saves immutable evidence associations, submission, `PROOF_SUBMITTED` job
state, event, pending proof invocation, and receipt. The response is a pending **“Proof
received”** acknowledgment and never claims verification, payment, or resolution.

DEMO criterion 8 covers acceptance and check-in/location. Its retained-before-evidence
assertion remains pending until the first proof is committed in criterion 9, where it must
reference that exact immutable original-before evidence ID. This paired upload contract has no
separate before-only upload action.

## Completion inspection (B7)

`POST /api/jobs/{id}/inspect` is service-only and accepts exactly a saved
`submission_id`, with `Idempotency-Key` and the expected current **job** revision in headers.
The service reloads the job's immutable submission, stored normalized bytes, original before
association, frozen plan target/scope/work-area/dispatch location, and frozen image request
configuration. It records a bounded attempt before invoking the inspector outside SQLite, then
fences finalization against the current proof/revision, saved cause, frozen basis and any
pending or decided completion exception. The typed response includes the exact attempt/proof
and verification IDs, input/result revisions, nullable findings and observations, deterministic
checks, prerequisites, score components/total and named failed or unknown requirements. An ERROR
has an attempt ID and no invented verification, findings or score. Saved receipts replay the
original snapshot; existing non-inspection receipt shapes are unchanged.

An exact already-current interpretation requested with a new key references the original result
and event without advancing the job or invoking again. Changed interpretation configuration may
install a new result at the then-current revision. The full immutable request includes system
text, schema/tool description, message template, inference settings, preprocessing identity and
the plan's separate target, full cleanup scope and work area. Changes require affected live model
qualification; offline repair checks do not qualify a model.

A live claim returns a transient `INSPECTION_IN_PROGRESS` without a final receipt. After expiry,
the old key receives an immutable `INSPECTION_INTERRUPTED` error; subsequent work uses a new key.
A different-key takeover saves the old request's terminal receipt before acquiring a new claim.
Late physical responses are retained as immutable observations linked to the original attempt,
but cannot populate the cache, install a result or rewrite a prior receipt. A response first
finalized after its deadline receives `INSPECTION_FENCED`. Usage is counted by unique physical
attempt/observation, never by number of replayed receipts. A cache association records zero
physical calls and its source attempt; unavailable physical usage remains unknown.

Schema 5 adds the completion claim and observation journals while retaining schema-4 rows and
receipts. `Store.current_verification` is a strict authorization-phase read. After rework,
payment or cancellation advances the job, history readers use the exact saved exception/payment
verification ID and validate its relationships instead of weakening that freshness check.

A schema-valid result persists typed findings, deterministic GPS/time/reuse checks, the exact
input and result job revisions, and `current_verification_id`. Only a current result with all
prerequisites and at least 95 points changes the job to `VERIFIED`; valid 90 or unknown findings
remain `PROOF_SUBMITTED` but still supersede an older verification pointer. Reuse compares the
candidate after image to earlier server-ordered `PROOF_SUBMITTED` after images across jobs; it
does not use claimed capture time or the before image. Transport or malformed-output failures
persist only a recoverable failed attempt and receipt: no verification, exception, payment, or
job state transition is fabricated.

Budget accounting validates the saved relationships and counts outstanding RESERVE
amounts plus spent CONSUME amounts once; Payment is not subtracted again. RELEASE frees
the corresponding reservation. Inconsistent journals fail closed. The normal first
dispatch displays total 50000, reserved 7200, spent 0 and available 42800 cents.

B5 provides the HTTP operation and model-selected-vendor request seam. Generalized
persisted agent intent and runtime orchestration remain B10/B11 work; B4's decision
route still owns only its investigation decisions. Settlement remains a later B9 card.

## Exceptions and operator rework (B8)

Completion escalation is service-only. `POST /api/jobs/{job_id}/exceptions` requires an
`Idempotency-Key`, a job revision in `X-Steward-Expected-Revision`, and strict JSON with
the saved `submission_id`, `verification_id`, `denial_event_id`, and `reason_code`. It
accepts only the exact current B7 verification/proof and a persisted `settle` denial whose
event, components, gates, unmet requirements, frozen proof basis, current checks, policy,
and unpaid reservation all agree. B8's primitive tests retain explicitly synthetic denial
fixtures; B9 also exercises this consumer with the actual settlement endpoint described below.

`POST /api/issues/{issue_id}/exceptions` uses an issue revision in the same header. It
accepts strict `authority`, `no_vendor`, or `budget` kinds. A budget exception additionally
requires the saved B5 `DISPATCH_DENIED` event ID. The service recomputes the attempted plan,
vendor, quote, policy, issue/fact basis, and current journal balance; stale, recovered,
inconsistent, or non-budget denials cannot create a funding exception. Pre-job exceptions
retain no invented job, proof, verification, or image relationship.
The saved denial keeps its original budget snapshot; current funds may legitimately differ
and must still be insufficient. All pre-job kinds require an unresolved pre-job lifecycle
with no active job.

Authorized operators and the service can read `GET /api/exceptions/{id}` and
`GET /api/issues/{id}/exceptions`. The safe detail includes exception and current job
revisions, saved proof/verification and evidence IDs, scope/target/work area, nullable
findings/checks, prerequisite and 95-point score gates, unmet requirements, denial identity,
and saved decision/invocation status. It omits private image references and stored bytes.
Advertised actions are actor-specific and require current applicable evidence. Operators
see only Request completion on an eligible PENDING exception; DECIDED processing status is
visible without exposing the service's rework control. Historical proof remains readable
after later job revisions or interpretation changes.

Only an authenticated operator can `POST /api/exceptions/{id}/request-completion`. Its
header names the expected exception revision; its strict JSON body contains only
`submission_id` and `expected_job_revision`. A successful `202 NEEDS_REVIEW / DECISION_SAVED`
persists one immutable decision, `OPERATOR_DECISION` event, one pending invocation, and the
exception's DECIDED transition. The `PendingEntityResult` contains the decision ID and actual
invocation ID while leaving `state_revision` null; current E+1 and unchanged job J are read
from the safe detail. It is an acknowledgment of durable intent, not processing, payment, or
rework completion. Same-key and compatible second-key clicks return the saved choice.
Compatible new-key escalation receipts retain the original event, evidence, requirements,
and result revision; read detail for current revisions. They create no second exception event.

`POST /api/operator-decisions/{id}/rework` is service-only, bodyless, and uses the expected
job revision header. It validates the unhandled saved decision, exact proof/verification,
unpaid RESERVED reservation, and saved operator event/invocation before atomically marking the
same job `REWORK_REQUIRED`, the exception HANDLED, and the decision handled. It preserves the
plan, vendor, quote, reservation, ledger, and original proof. If `area_clear` was explicitly
false the instruction asks to clear remaining material; unknown findings instead name the
unresolved requirement without claiming debris was observed. PENDING and DECIDED completion
exceptions continue blocking new proof until this committed transition. Cancellation and
settlement mutations remain B9 responsibilities.
Every new completion action rechecks the full frozen interpretation, saved proof/plan/source,
current policy, deterministic prerequisites and score, and original reserved journal. A
supplied service invocation must match the exact saved operator choice before receipt replay
and under the transaction. Exact committed-request replay remains historical after fresh
identity and saved-cause authorization; it does not re-execute work or refresh an old finding.

## Simulated settlement, closure and cancellation (B9)

All three financial mutations are service-only and require `Idempotency-Key` and
`X-Steward-Expected-Revision`. Human personas cannot settle, cancel or close. The usual
server-bound actor, saved resource/cause authorization and request ID/error behavior apply.
No caller may provide prices, scores, acceptance flags, payment IDs or financial balances.

| Route | Revision header | Body | Successful effect |
|---|---|---|---|
| `POST /api/jobs/{job_id}/settle` | Current JOB revision | Strict JSON containing only `submission_id` | One simulated payment, one CONSUME, CONSUMED reservation, PAID job at J+1 |
| `POST /api/jobs/{job_id}/cancel` | Current JOB revision | No body | One RELEASE, RELEASED reservation, CANCELLED job at J+1; issue remains unresolved |
| `POST /api/issues/{issue_id}/close` | Current ISSUE revision | No body | RESOLVED issue at I+1 with accepted submission and server `resolved_at`; job and money unchanged |

Close and cancel reject every nonempty body, including `{}`. Duplicate length headers are
rejected; absent/zero length headers do not bypass inspection of the actual stream. The
server rejects the first nonempty chunk without buffering the remainder, before mutation.

`200 OK` returns an `EntityResult`: payment ID/job revision for settlement, job ID/job
revision for cancellation, or issue ID/issue revision for closure. Saved event IDs and
evidence IDs accompany the result. A denied business attempt returns `403 DENIED` and a
durable audit/receipt without changing money or domain revision. Stale revisions are
audited action denials. A changed payload under an existing key remains a `409
IDEMPOTENCY_CONFLICT`. Invalid body/cause is rejected; inconsistent stored financial or
proof relationships return `503 ERROR / FINANCIAL_STATE_INVALID` with transaction rollback.
A close without a dispatched active contract returns `404` without inventing a financial audit.

For a new payment, the service rechecks the exact latest proof, current successful
interpretation and physical/cache provenance, complete request configuration, current
policy, deterministic checks, pending exception, and original reserved journal under one
write transaction. It does not reprice the dispatched contract. The 90-point result records
`SETTLEMENT_DENIED`, keeps 7,200 cents reserved and zero spent, and can then support the
separate B8 escalation/choice/rework operations. Valid accepted proof consumes 7,200 cents
once; available/reserved/spent become 42,800/0/7,200 in the single-job example.

`EventFacts.settlement` is a typed server audit holding the action, original plan/amount,
nullable reservation/payment/proof/verification IDs, expected and observed JOB/ISSUE
revisions, original budget snapshot and the broader action gate. `EventFacts` still retains
the exact B7 completion components, two prerequisite/score gates and original unmet names.
A score failure does not pretend that scene/target prerequisites failed. B8 validates the
present real settlement audit before accepting its denial; stale or other-action refusal
cannot substitute for a current completion-only failure. Historical budget snapshots are
not required to equal a later balance after other valid jobs reserve funds.

Closure validates the historical paid proof, frozen request and successful interpretation,
settlement receipt/event, original contract and consumed journal. It does not re-inspect or
compare against later default model/prompt/policy configuration. `Store.current_verification`
remains strict and is not used for this historical paid read. A restart after payment can
therefore close without another payment; compatible new close keys return the original
resolution without changing its timestamp or emitting a second resolution event.

Exact-key replay follows fresh actor/resource/cause authorization before current-state
checks. A denied close remains replayable against its saved contract and proof after
cancellation or a newer proof; a new close must bind the current proof. A supplied settlement
invocation from an earlier proof cannot authorize or replay settlement of a later proof.
Operational HTTP invocation binding and agent intent/tool integration remain B10–B12 work.

Unpaid cancellation atomically releases the reservation and marks an open PENDING/DECIDED
completion exception CANCELLED with the actual cancellation event/time. It preserves the
operator's original choice and leaves `handled_at` null when rework never happened. Already
HANDLED history is retained. Paid jobs cannot be cancelled or refunded. Independent requests
cannot both consume and release the same reservation. These operations and offline tests
do not claim live agent execution or complete demo acceptance.

## Invocation case context and agent construction (B11)

`GET /api/invocations/{invocation_id}/context` (`read_case_context`) is a service-only
read requiring the matching `X-Steward-Invocation-Id` and bearer credential. A resident,
crew, operator, missing header or different invocation cannot load the packet. It uses
one deferred SQLite read snapshot; it never repairs a cause or creates a receipt.
Missing records return404; inconsistent saved cause/cursor returns422; unavailable
storage returns503. The original SIGNAL_RECEIVED may remain issue-less while its
canonical invocation and current issue are linked. Original trigger policy/revision,
current issue/job revisions and invocation processing revision are separate fields.

The dependency-light `CaseContext` exposes typed source/receipt/observation times,
source identity/lineage, evidence IDs/hashes, current shared score and saved issue score,
policy and role/model identities, typed geocode/classification/jurisdiction, retained
hazard references, service lookup and applied official status, original plan/quote,
job/check-in, proof, verification findings/checks/gates, operator choice, reservation,
payment and safe result receipt IDs. Unknown stays null. It excludes byte locations,
image bytes, raw SDK request/reasoning, credentials, keys and lease/fence controls.
The `applicable_to_current_job_revision` flag is a revision relationship, not a new
payment permission: the mutation still revalidates its complete current physical basis.
Historical verification uses exact proof/exception/payment references after job revision
advancement. A paid case retains accepted findings without pretending they are a fresh
current verification or requiring another payment.

`candidates` contains at most10 summaries and `events` at most20. Pass the returned
`next_candidates_cursor` as `candidates_cursor` and/or `next_events_cursor` as
`events_cursor` to the same authenticated endpoint. Omitted cursor or `0` starts the
first page. Candidate row watermarks and event ID keysets exclude newly appended rows
from subsequent pages; current display facts still reflect the new request's consistent
snapshot. Critical trigger/proof/failed gate/choice/payment fields are outside these pages.
Candidate summaries can include an already-linked canonical issue; they are evidence
for matching, not permission to rebind a source. Freshness is rechecked at each mutation.

`core.build_agent(session, model=None, lifecycle=None, provider_observer=None,
deadline_at=None)` constructs a fresh sequential Agent with the session's25 domain tools,
no default printing and no implicit Strands retry. `core.invoke_case(agent)` supplies the
fixed saved-trigger request and enforces the whole remaining monotonic execution window.
It returns a safe `CaseExecutionResult`, not raw model reasoning or an invented success.
Its in-process12-cycle/40-request/120-second bounds do not implement B12 durability.
Default text output is2048 tokens (`AGENT_MAX_OUTPUT_TOKENS`,1–8192), with finite provider
connection/read bounds (`AGENT_PROVIDER_TIMEOUT_SECONDS`, default30, maximum120) and one
SDK attempt. Explicit AWS_PROFILE uses that profile; absent profile retains the ambient
provider chain. Vision model selection remains independent.

Before every model cycle the trusted host uses that SAME session HTTP client to load
fresh context and replace the single delimited evidence packet, retaining actual tool
conversation history. The fixed read operation is not a26th model tool or generic URL
capability. `InvocationHooks.refresh` also accepts the pagination cursors for trusted
host use. Actual host reads/attempts are separate from requested model tools. A saved
intent is not a stop; actual watch/route/dispatch/exception/rework/resolution effects are.
The real offline engine test proves a low-score inspection can reach a real settlement
denial and then an exception; later same-batch tools are suppressed only after the effect.

B12 can inject `ExecutionLifecycle.authorize(ExecutionRequest)` and
`observe(ExecutionObservation)`: both are awaited, must return True, and refusal/error
stops new work. Model requests include the refreshed case; tool requests include the
immutable validated Command and real tool-use reference. HTTP physical attempts still
use the accepted prepare/begin_attempt/finish_attempt lifecycle on the owned client.
Default lifecycle is explicitly non-durable. The separate synchronous provider observer
receives only invocation ID, ordinal, operation and monotonic time for the public
Botocore `before-send` event. It cannot claim that the request was physically sent,
accepted, billed or durably acknowledged, and it cannot authorize work. Timeout or
cancellation may detach an SDK worker; B12 must preserve uncertainty and fence late writes.

The `agent` CLI is API-based: `agent submit --description TEXT --location TEXT [--image
FILE] [--observed-at UTC_TIME] [--key KEY]` selects a configured sandbox resident and
creates a real persisted event. Preserve the printed key for uncertain submit recovery.
`agent context INVOCATION_ID` reads via the private environment service token;
`agent resume INVOCATION_ID` requests persisted processing through the B12 resume endpoint.
It exits0 when processing is enabled,2 when disabled, and does not itself construct a model.
`--origin` precedes the subcommand. Never paste the service token into chat or CLI args.
Preflight and image spike commands remain separate from this production domain registry.

The offline seed now atomically binds its original pending invocation while linking the
baseline signal; its immutable original event stays unchanged. Existing seeded precision
is represented using the accepted B4 geocode producer and reviewed address fixture,
so persisted/current/context baseline scores all remain65 and the issue stays CANDIDATE.
No model classification, dispatch, or inference is fabricated by the seed.

CLI service reads bind the ambient `STEWARD_SERVICE_TOKEN` to `STEWARD_ORIGIN`
(default `http://127.0.0.1:8000`). Configure that trusted destination privately alongside
the token; `context` and `resume` reject a different `--origin` before constructing a
credential-bearing client. Explicit resident `submit --origin` behavior is unchanged
(`--origin` is a global option before the subcommand). Model temperature must be a
finite numeric value in the inclusive range 0–1; booleans, strings, NaN, infinities and
out-of-range values are rejected before provider construction.

## Durable processing and recovery (B12)

Set `STEWARD_RUNTIME_ENABLED=true` explicitly in the API environment to enable the
dispatcher. Its default is false, including ordinary component tests. Enabling it can
invoke the configured Bedrock models. Preserve the existing private service/session
secrets across restarts; the runner uses the configured `STEWARD_ORIGIN` and service
credential on one invocation-owned HTTP client. The API must be reachable at that origin.
The API startup scan discovers saved pending and expired interrupted work; accepted
domain events also wake discovery. A wakeup is only a hint. The dispatcher closes each
short Store unit before HTTP/provider work and runs one invocation at a time. Normal
WAITING/COMPLETED/ERROR invocations remain dormant. No browser receives runtime credentials.

Schema7 preserves prior records and adds execution episodes, prepared logical commands,
reserved attempts, immutable attempt observations/control receipts/traces, and separate
intake physical observations. The FastAPI service alone owns these records. The runner
has no SQLite interface. The existing25 domain tools remain the same local/AgentCore
HTTP implementation; production execution installs `DurableLifecycle` through the
accepted lifecycle factory and awaits each authorization and acknowledgment.

Each saved invocation has an initial120-second server-UTC execution episode and at most
one120-second recovery episode for genuinely interrupted unfinished processing. Its
original trigger, lifetime12 model-cycle/40 requested-tool limits and each logical
request's original key/deadline/three-attempt allowance survive takeover. A30-second
lease is renewed every10seconds within the unchanged episode. Client monotonic deadlines
conservatively subtract coordinator round-trip time; they never replace server authority.
Unknown reserved attempts consume allowance. Expired unresolved commands cannot issue
a replacement POST/key. Receipt reconciliation can read an already committed result,
including after final exhaustion, without granting new execution authority. Recovery
after payment may let the model choose RESOLVE using remaining allowance; the coordinator
does not make that choice. Acknowledged errors and normal saved stops do not earn recovery.

Lost coordinator finish/observation acknowledgments carry a private typed interruption
through the HTTP client, agent hooks and execution result. The runner stops further work
and leaves the original invocation RUNNING for fenced recovery, even when a tool returned
a safe ERROR envelope to the SDK. The next owner reconciles the saved logical request
before another model decision. This does not reopen genuine model/domain terminal errors.
Runtime permit refusals retain HTTP409 and their specific reason (including
DEADLINE_EXCEEDED); they are distinct from ordinary HTTP422 input validation.

The fixed service-only private POST operations under `/internal/invocations/{id}/` are
`claim`, `renew`, `prepare`, `load`, `begin`, `finish`, `reconcile`, `requests`, `authorize`,
`observe`, and `complete`. Their strict `RuntimeControl`/`ControlReply` schemas are in
OpenAPI. They are not model tools and bypass domain lifecycle recursion. Stable nonces
make lost acknowledgments replayable. Each control transport has at most3 attempts and
a20-second bound within the remaining episode; observation/reconciliation after its end
has a separate5-second bound that cannot authorize work. Server-received controls are
counted separately from domain attempts and requested model tools.

Invocation-bearing domain requests require private `X-Steward-Attempt-Id`,
`X-Steward-Lease-Owner`, and `X-Steward-Fencing-Token` alongside the existing invocation,
revision and idempotency headers. The server derives the canonical command from the
actual method/path/query/body/revision and compares it to the saved preparation.
The effect writer rechecks lease/fence/deadline/command/key before receipt replay and
before commit, including inspection finalization. Direct service helpers without an
invocation retain ordinary policy; adding an invocation without a permit is rejected.
Late physical model observations are separate immutable evidence and grant no effects.

`GET /api/invocations/{id}` returns `ToolResult[RuntimeStatus]`; `after_id` paginates
20 trace records with `next_cursor` and `truncated`. Operator/service projections include
safe operation/arguments/results, policy/model versions, usage/elapsed time when actually
observed, receipt IDs and transport outcome metadata. Requested and observed phases remain
distinct. An individual trace exceeding8KiB omits its arguments/result and sets
`content_truncated=true`. Owning resident/crew projections are narrower; district and
saved job/vendor boundaries still apply. Traces exclude keys, lease owners/fences, raw
journals, hidden reasoning, image paths and credentials. SDK before-send observations
are explicitly not evidence of a successful request, inference or billing.

`POST /api/invocations/{id}/resume` is service-only and strictly bodyless. It returns
the current saved status and `PROCESSING_ENABLED` or `PROCESSING_DISABLED`, waking
discovery when enabled. It does not promise completed work or restart a normal wait.
The CLI's configured-origin credential binding applies to this operation as to context.

The intake adapter now validates native provider JSON with strict JSON semantics, retaining
actual stop reason and usage before parsing. Its unchanged prompt/schema use a shared1024
output-token cap in both request and configuration fingerprints, after the retained512
baseline reproduced truncation. Invalid/truncated findings remain ERROR and cannot become
successful cached evidence. Component qualification is separate from B13 API acceptance.
