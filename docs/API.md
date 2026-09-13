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
| POST `/api/issues/{id}/classification`, `/jurisdiction`, `/decisions` | Service-only saved proposals and gate-validated decision intents; decision intent alone does not mutate lifecycle state |
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
| 200 (201/202 where explicitly committed and documented) | OK |
| 200 | NEEDS_REVIEW |
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
route still owns only its investigation decisions. Crew proof, verification, exceptions
and settlement remain separate later cards.
