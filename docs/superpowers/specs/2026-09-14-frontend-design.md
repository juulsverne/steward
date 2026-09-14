# Steward frontend design: frame plus five surfaces

Status: proposed, September 14, 2026, 10:45 AM Chicago. Written after the B13 live API gate passed on the `codex/steward-build` branch. Nothing under `frontend/` exists yet.

This document builds on the [P1 frame spec](2026-09-14-frontend-frame-design.md) and resolves its open choices. It adds the visual system and the content of all five surfaces so that P1 through P6 can be built today. Product behavior, actors, authority and the sixteen acceptance criteria come from [PRD](../../PRD.md) sections 4.3 and 7, [DEMO](../../DEMO.md) and the task cards in [BUILD_PLAN](../../BUILD_PLAN.md) section 8. Tone and principles come from `.impeccable.md`. Nothing here adds API authority, changes actors, or lets model prose set status.

## 1. Decisions confirmed with the owner

| Question | Decision |
|---|---|
| Scope for today | Ship staged. Frame first, then Issue Detail and Board to full polish for the video, then Inbox, Crew Form and Resident intake as clean working forms. Deadline is 7 PM Chicago tonight. |
| Visual direction | Civic editorial. Generous whitespace, fine rules, large evidence imagery, precise motion. A modern public institution's operations tool. |
| Headings | Newsreader for page titles and section heads. Public Sans for all interface text. |
| Who builds | This session. The lead builds the frame, then dispatches one subagent per page with disjoint file ownership, and integrates one page at a time. |
| Types | Generated from OpenAPI. A Python script exports `create_app().openapi()` to `frontend/openapi.json` offline, then `openapi-typescript` generates `src/api/schema.d.ts`. Both files are committed. |
| Router | React Router. Five surfaces, deep links through the server fallback. |
| Map | Plain `leaflet` with a small React wrapper, no `react-leaflet`. One dependency, full control of markers, labels and failure handling. |
| Component library | None. Hand-written primitives. Vanilla CSS with custom-property tokens, no Tailwind. |

Everything in the P1 frame spec that is not overridden above stands: same-origin serving from FastAPI, HttpOnly persona cookie, `ToolResult` envelope handling, intent headers on every mutation, idempotency key reuse, bounded polling, the error table, the test list.

## 2. Goals and non-goals

Goals:

- A nontechnical judge can open Issue Detail and explain why Steward waited, disputed, dispatched, blocked payment and later permitted it, without reading model prose.
- Every one of the sixteen criteria has a visible proof on a screen, as mapped in the P1 design preflight.
- The interface looks like something a district office would plausibly run: calm, credible, contemporary. Light default, complete dark theme.
- Crew and intake forms are complete at 360 px wide. The whole flow works by keyboard.

Non-goals for today: hosting (H4), a resident status page, any operator action other than Request completion, any chat surface, animation beyond state transitions, and any change to API authority.

## 3. Architecture

Adopted from the P1 frame spec, with these concrete file boundaries so that page workers never touch the same file.

```
frontend/
  package.json  vite.config.ts  tsconfig.json  index.html  openapi.json
  public/                      favicon, demo assets clearly named synthetic
  src/
    main.tsx                   root, router, theme bootstrap before first paint
    App.tsx                    frame: header, persona switcher, nav, outlet, footer notice
    theme.css                  tokens (light default, dark override), reset, type, utilities
    api/schema.d.ts            generated, committed
    api/client.ts              call, read, mutate, upload, pollUntil, ApiError
    api/session.ts             session store and persona switch
    api/labels.ts              status, decision, outcome, invocation and provenance labels
    lib/format.ts              money, timestamps, points, plural helpers
    components/                lead-owned primitives (section 5)
    pages/OperationsBoard.tsx  + components/IssueMap.tsx          (P3 worker)
    pages/IssueDetail.tsx      + components/EvidenceComparison.tsx,
                                 components/DecisionCard.tsx,
                                 components/DecisionTimeline.tsx  (P2 worker)
    pages/OperatorInbox.tsx    + components/ExceptionDetail.tsx   (P4 worker)
    pages/CrewJobs.tsx, pages/CrewJob.tsx + components/ProofForm.tsx (P5 worker)
    pages/ResidentIntake.tsx                                       (P6 worker)
scripts/export_openapi.py      dumps the OpenAPI document without a running server
src/agent/api.py               static mount and client-route fallback (P1)
tests/test_static_frontend.py  fallback and caching behavior (P1)
```

Ownership rule: `theme.css`, `api/*`, `lib/*` and `components/*` listed under the lead are lead-owned. A page worker who needs a new shared primitive or a client helper writes it inside its own page folder first and notes the request; the lead promotes it after review. Page workers may add labels to `api/labels.ts` only through the lead.

Routes: `/` Board, `/issues/:issueId` Issue Detail, `/inbox` Operator Inbox, `/crew` job list and `/crew/jobs/:jobId` Crew Form, `/report` Resident intake. Pages a persona cannot use render a short explanation plus the persona switcher, never a blank screen.

Development: Vite on port 5173 proxies `/api` to `127.0.0.1:8000`. The API runs with `STEWARD_LOCAL_HTTP=true` and `STEWARD_DEVELOPMENT_ORIGINS=http://localhost:5173`. Production is same-origin from `frontend/dist`.

Realistic data for development: `python -m agent.seed --db .steward/ui.sqlite3` gives one seeded couch at 65 points. A full walked state needs one run of `python -m agent.demo --base-url http://127.0.0.1:8000 --out .steward/ui-run.json` against that database with AWS credentials. The lead does this once early so that page workers and the polish pass see every state. Screenshots for review come from the walked database.

## 4. Visual system

### 4.1 Tokens

All colors are custom properties in `theme.css`. Light values are the default on `:root`. Dark values apply under `[data-theme="dark"]` and, when no explicit choice is stored, under `prefers-color-scheme: dark`. Every status color has a text label beside it wherever it appears.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--canvas` | `#F6F3EE` | `#12151C` | page background, warm paper |
| `--surface` | `#FFFFFF` | `#1A1F29` | cards, panels, inputs |
| `--surface-2` | `#EFEBE4` | `#232936` | muted wells, table header, code |
| `--rule` | `#DDD7CC` | `#303747` | hairline dividers |
| `--rule-strong` | `#B8B0A3` | `#414A5E` | input borders, table outer border |
| `--ink` | `#14213D` | `#EEF0F4` | primary text, deep navy |
| `--ink-2` | `#47506A` | `#B7BECC` | secondary text |
| `--ink-3` | `#6F6A62` | `#8C94A6` | metadata, placeholders (4.5:1 minimum on canvas) |
| `--action` | `#0F6E6B` | `#5CC8C2` | primary buttons, links, active nav |
| `--action-hover` | `#0B5957` | `#7AD6D0` | hover and pressed |
| `--on-action` | `#FFFFFF` | `#0F1A1A` | text on action |
| `--action-soft` | `#DFF0EE` | `#163A39` | selected row, soft emphasis |
| `--focus` | `#0A4F4D` | `#8FE3DE` | 2 px ring plus 2 px offset, never removed |

Status pairs, each `--status-<name>-bg` and `--status-<name>-fg`:

| Name | Light bg / fg | Dark bg / fg | Used for |
|---|---|---|---|
| watching | `#E6ECF5` / `#2B4A7A` | `#223352` / `#A9C1EA` | CANDIDATE, MONITORING, POSTED, PENDING, WAITING |
| active | `#DFF0EE` / `#0F6E6B` | `#163A39` / `#7FD9D2` | ACTIONABLE, RESOLUTION_ACTIVE, DISPUTED, ASSIGNED, CHECKED_IN, PROOF_SUBMITTED, RUNNING |
| attention | `#FBEBD0` / `#7A4B00` | `#4A3512` / `#F2C776` | ESCALATED, REWORK_REQUIRED, pending exception, NEEDS_REVIEW |
| resolved | `#DDF1E1` / `#1E6B3A` | `#1B3D28` / `#8FD9A5` | RESOLVED, VERIFIED, PAID, COMPLETED, OK on a saved action |
| denied | `#F8E1E1` / `#8A2A2A` | `#4A1F1F` / `#F1A3A3` | DENIED, REJECTED, INVALID, ERROR |
| neutral | `#ECE8E1` / `#514B43` | `#2A2F3A` / `#C0C6D2` | ROUTED_EXTERNAL, DUPLICATE, CANCELLED, historical |

Green is reserved for the resolved pair. An external route never receives it. The lead verifies every fg-on-bg pair at 4.5:1 or better in both themes before page work starts, and records the numbers in the P1 report.

Provenance is never a color alone. `ProvenanceTag` renders the word `live`, `seeded` or `synthetic` in a small outlined chip: solid outline for live, dashed outline for seeded and synthetic, with a title attribute explaining the word.

### 4.2 Type

- Interface: Public Sans, variable weight, self-hosted through `@fontsource-variable/public-sans`. Fallback stack `system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`.
- Headings: Newsreader, variable weight and optical size, through `@fontsource-variable/newsreader`. Fallback `Georgia, "Times New Roman", serif`. Only page titles (`h1`) and section heads (`h2`) use it. Everything smaller stays Public Sans so forms and tables read as software.
- Scale, in px at the 16 px base: 12 meta, 13 small, 14 dense table and form labels, 16 body, 18 lead, 22 `h2`, 30 `h1` on desktop and 26 on mobile. Line height 1.5 for body, 1.2 for headings.
- Numbers use `font-variant-numeric: tabular-nums` everywhere a column of numbers can appear: scores, money, times, counts.
- Scores read as points against a threshold: "85 points, 70 needed" and "90 of 95 for payment". Never a percentage, never a confidence.

### 4.3 Space, shape, depth, motion

- 4 px base. Spacing steps 4, 8, 12, 16, 24, 32, 48, 64. Page gutter 16 px on mobile, 24 px from 768 px, 32 px from 1024 px. Content max width 1200 px.
- Radii: 4 px on controls and chips, 8 px on cards and images. No pill buttons except status chips.
- Depth comes from rules, not shadows. One shadow token exists for menus and the mobile action bar: `0 1px 2px rgba(20,33,61,.08), 0 8px 24px rgba(20,33,61,.08)`.
- Motion: 160 ms ease-out for hover, focus and expansion; 240 ms for panel entry. `prefers-reduced-motion: reduce` removes transforms and keeps opacity fades under 100 ms. No skeleton shimmer; pending states use a quiet placeholder with the word "Loading".
- Evidence images are the largest elements on a page. They keep their aspect ratio in an 8 px radius frame with a caption row underneath, never a card inside a card.

## 5. Shared primitives

All lead-owned, in `components/`. Each has an accessible name, works without color, and takes typed props derived from `schema.d.ts`.

| Component | Purpose |
|---|---|
| `PageHeader` | `h1` in Newsreader, optional eyebrow (district or issue category), meta row for as-of time, policy version, ids. |
| `StatusBadge` | Label plus tone from `api/labels.ts`. Never renders a color without the label. |
| `ProvenanceTag` | live, seeded, synthetic chip as described above. |
| `Points` | `value`, `threshold`, `noun` renders "85 points, 70 needed" with tabular numbers. |
| `Money` | cents to `$72.00`. Adds "simulated" when the record says so. |
| `Timestamp` | local time with zone abbreviation, ISO in `title`, "Unknown" for null, optional label such as "observed" or "received". |
| `EvidenceImage` | `<img src="/api/evidence/{id}/content[?job_id=]">` by safe evidence id, caption row with role, `Timestamp` and `ProvenanceTag`, an alt text built from role and time, and a plain fallback when the image fails. |
| `KeyValue` | Two-column definition list for facts. Collapses to stacked pairs under 480 px. |
| `SectionCard` | `h2` in Newsreader, optional right-aligned action, hairline rules. |
| `ActionButton` | Primary, secondary, quiet. Pending state keeps width, shows "Working" text, disables duplicate submission. |
| `Notice` | Informational, warning, error tones with an icon glyph and text, used for sandbox notes, tile failure, stale item and API errors. |
| `PendingState`, `EmptyState`, `ErrorNotice` | From the P1 spec. `ErrorNotice` shows the reason code text and a retry action. |
| `SavedState` | Distinguishes "Saved" from "Processing" from "Waiting" from "Completed" from "Error" using the verbatim invocation status plus a gloss. |
| `PersonaSwitcher` | Labeled select grouped by actor type; posts the persona; re-reads the session; keeps the previous choice on failure and shows the reason. |
| `ThemeToggle` | Light, dark, system. Stores only `steward-theme`. |

`api/labels.ts` holds the only mapping from enum codes to words and tones:

- IssueStatus: CANDIDATE "Candidate", MONITORING "Monitoring", ACTIONABLE "Actionable", RESOLUTION_ACTIVE "Resolution active", RESOLVED "Resolved", DISPUTED "Official status disputed", ROUTED_EXTERNAL "Routed externally", DUPLICATE "Duplicate", INVALID "Invalid", ESCALATED "Escalated to operator".
- JobStatus: POSTED "Posted", ASSIGNED "Assigned", CHECKED_IN "Checked in", PROOF_SUBMITTED "Proof submitted", VERIFIED "Verified", PAID "Paid, simulated", REWORK_REQUIRED "Rework required", REJECTED "Rejected", CANCELLED "Cancelled".
- DecisionType: MONITOR "Monitor and wait", MARK_ACTIONABLE "Mark actionable", DISPUTE_OFFICIAL_STATUS "Dispute official status", ROUTE_EXTERNAL "Route externally", REQUEST_DISPATCH "Request dispatch", REQUEST_SETTLEMENT "Request settlement", REQUEST_OPERATOR "Request operator decision", REQUEST_REWORK "Request rework", RESOLVE "Resolve".
- Outcome on a timeline event: OK "Saved", DENIED "Denied", NEEDS_REVIEW "Needs review", NOT_FOUND "Not found", ERROR "Error". A request-type decision with outcome OK is still labeled "Requested" so that a requested tool is visibly distinct from the saved mutation that followed.
- InvocationStatus is shown verbatim with a gloss: PENDING "queued", RUNNING "Steward is processing", WAITING "waiting for a crew or operator event", COMPLETED "finished", ERROR "stopped with an error".
- Timeline event `type` strings are humanized by replacing underscores and sentence-casing; the raw code stays visible in small monospace beside it because the audit trail needs it.
- ActorType: resident "Resident", crew "Crew", operator "Operator", service "Steward".

## 6. Application frame

Header, 56 px tall, canvas background with a hairline bottom rule:

- Left: wordmark "Steward" in Newsreader, then "South Loop Demo District" in Public Sans, then a `Sandbox demo` chip in the neutral pair. On mobile the district name collapses into the chip's title.
- Center: navigation as text links. Entries depend on the session actor: Board and Issue links for operator; Inbox for operator; Crew for crew; Report for resident. With no actor, only Report and the switcher show, with a one-line notice that a persona must be selected before anything can be read or submitted.
- Right: `PersonaSwitcher`, `ThemeToggle`. On mobile a labeled menu button opens a sheet containing navigation, the switcher and the toggle. The page title and the switcher remain reachable on every width.

Footer, one line in `--ink-3`: "Demo personas, seeded fixtures and simulated dispatch and settlement. No real authority or money." with a link to the repository.

Session: on load the frame calls `GET /api/demo/session`. The `notice` string from the response is rendered once in the header sheet and on the Report page. Nothing about the actor is written to storage.

## 7. Surfaces

Each page reads only from the endpoints listed, treats the response as the sole source of status, and shows pending, empty and error states through the primitives.

### 7.1 Operations Board, `/`

Reads `GET /api/board`. Refreshes every 20 seconds while the tab is visible, and on a manual Refresh button. The as-of time from the response is shown in the header meta.

Layout at 1024 px and up: `PageHeader` with district name, eyebrow "Operations board", meta with policy version and as-of time. Under it a summary strip of five tiles in one row. Below, two columns: issue list at 7/12 and map at 5/12, the map sticky to the viewport top. Under 1024 px the map sits above the list at 280 px tall, then the list. Under 640 px the summary strip wraps to two columns.

Summary tiles, each a number in Newsreader 30 px with a Public Sans label:

- Attention: `counts.attention`. When zero the tile reads "No decisions waiting" instead of the number. Never "Everything resolved".
- Watching, Active, Resolved: the three lifecycle counts from `counts`. Attention is not a lifecycle bucket, and the tiles say so in their captions: "watching, not yet actionable", "being handled", "closed with accepted proof".
- Budget: `available_cents` as the number, then a thin three-segment bar for available, reserved and spent from `budget`, each segment labeled with its amount underneath. The seeded arithmetic is visible: $428 available, $72 reserved, $0 spent after dispatch.

Issue list: one row per `markers[]` item, sorted attention first, then active, watching, resolved. Each row shows `StatusBadge` from `marker_state` with the `status` word, the `label`, and a link to `/issues/{issue_id}`. Rows for a marker with a `current_job_id` add "Job in progress"; rows with a `payment_id` add "Paid, simulated". Markers without coordinates go in a trailing group titled "Location not resolved" showing `location_unknown_reason`. Row hover uses `--action-soft`. Selecting a row focuses and pans the map to that marker; the map is a companion, never the only path.

Map: `IssueMap` wraps Leaflet with OpenStreetMap tiles and attribution. Markers are circle markers colored by `marker_state` with a permanent text label from `label`, and a popup with the same content as the list row plus the link. Green appears only for resolved. Location provenance shows in the popup with `ProvenanceTag`. If tiles fail to load, `Notice` in the map frame says map tiles are unavailable and the list continues to work. The map container is `aria-hidden` and keyboard focus never enters it; every marker is reachable through its list row.

Acceptance: after a walked run the tiles show the B5 and B9 balances, a watching case remains open, the resolved couch is green, and with tiles blocked the issue opens from its row.

### 7.2 Issue Detail, `/issues/:issueId`

Highest polish. Reads `GET /api/issues/{id}` and `GET /api/issues/{id}/events`. Images through `EvidenceImage`. If the session actor is an operator and `current.exception` is pending, the page links to `/inbox?exception={id}`. Crew personas cannot read issues (`READ_ISSUE` is operator and service only), so the page is operator-only and offers no crew link.

Layout at 1024 px and up: `PageHeader`, then a two-column grid, main at 8/12 and an aside at 4/12. Under 1024 px, single column in the order below with the aside content placed after the decision section.

1. **Current condition** (main, first). `PageHeader` eyebrow is the category, for example "Discarded couch". Title is the location. Meta row: `StatusBadge`, `Points` for `evidence_score` against 70, `responsibility` when present, hazards as a comma list when present. Under the header a one-line "Next" statement: from `current.next_actor` and `current.allowed_next`, for example "Waiting for: a new observation or an official status change" while MONITORING, "Next actor: Crew" while a job is open, "Next actor: Operator, decision waiting" while an exception is pending, "Closed with accepted proof" when RESOLVED. The `latest_decision.summary` sentence sits under it in lead type, labeled "Steward's last decision" with its `Timestamp` and `actor_label`.

2. **Evidence** (main). `SectionCard` with three parts.
   - Sources: one row per `sources.items[]`: `source_role`, `ProvenanceTag`, `Timestamp` observed and `Timestamp` received side by side with distinct labels, `reported_location`, thumbnails for `evidence_ids`. Independent sources are what raise the score, so the row count is captioned "N sources, M independent points" from `issue.components.independent_sources`.
   - Official record comparison: two columns at 640 px and up. Left "Official 311 record": `facts.official_record_status`, `Timestamp` for `facts.official_completed_at`, the lookup's `source_mode` and `ProvenanceTag` from `service_records.items[]`, and the conflict state from `facts.official_conflict_state` in words: "Conflict pending, 0 points credited" or "Dispute confirmed, service match credited". Right "Newer observations": every source observed after the completion time, each with its `Timestamp`. The completion time and the newer observation times are visually aligned on the same baseline so criterion 5 is one glance.
   - Proof comparison: when `evidence.original_before_evidence_id` exists, a row of up to three `EvidenceImage` frames labeled Before, Middle and After from `evidence.history.items[]`, ordered by `submitted_at`. Each frame's caption carries `Points` for `total` against 95, the failed requirements from `unmet` in the attention pair, and "Accepted" in the resolved pair on `evidence.accepted_submission_id`. A rejected middle proof stays visible after the accepted after proof; the caption says "Superseded".

3. **Decision** (main). `DecisionCard` for `latest_decision`, with the decision type label, the summary sentence, the `Timestamp`, and evidence references as thumbnail links. Under it the score components as a `KeyValue` table from `issue.components`: image, independent sources, precise geocode, service match, persistence, then the total against 70. When a verification exists, a second table from the latest `ProofHistoryItem.components`: GPS within 30 m, after later than before, target removed, no new hazard, area clear, total against 95, then the prerequisites as a list of `GateRecord` with pass or fail words and their `unmet` reasons. Authority and scope from `facts.classification` and `facts.jurisdiction`: category, primary target, full cleanup scope, marked work area, responsibility, unknowns. The card ends with the policy result sentence built from `allowed_next` and the decision type, for example "Policy denied settlement at 90 of 95; escalated to the operator".

4. **Plan and job** (aside). `KeyValue` for `current.plan`: scope, primary target, work area, required equipment, quote as `Money`, policy version. Then `current.job`: vendor label, `StatusBadge`, quote, reservation id, "Simulated dispatch" chip. Then `current.payment` when present: `Money` with "simulated", submission and verification ids. Then `current.exception` when present: kind, status, reason code, and the link to the Inbox. Rework keeps the same plan, quote and reservation, and the card says so when the job is REWORK_REQUIRED.

5. **Timeline** (main, last). `DecisionTimeline` renders `events[]` in order, newest last, as a vertical list with a hairline spine. Each entry: `Timestamp`, `actor_label` with actor type, humanized `type` plus raw code, `StatusBadge` for `outcome` with the request-versus-saved wording from section 5, `reason_code` when present, `summary`, evidence thumbnails, `simulated` chip, and `evidence_score` when the event carries it. The first denied settlement, the operator decision, the fresh proof and the later settlement and closure all stay visible. Historical entries use the neutral pair so that a past DENIED never looks like the current state. A "Show only decisions" toggle filters to decision and outcome events; the default shows everything.

Acceptance: a reader who has never seen the code can answer the PRD questions from this page. Missing evidence, errors and loading are explicit. Status words come only from the API.

### 7.3 Operator Inbox, `/inbox`

Reads `GET /api/exceptions` and `GET /api/exceptions/{id}`. Operator persona only.

Layout at 1024 px and up: list at 4/12, detail at 8/12. Under 1024 px the list is the page; selecting an item navigates to `/inbox?exception={id}` which shows the detail with a "Back to inbox" link. The selected id is the only URL state.

List: `PageHeader` "Operator inbox" with meta "N pending, M decided". Pending items first, each a row with `StatusBadge` for kind and status, the issue location, the job id, `Points` for `total` against 95 when present, and the reason code. Decided and handled items follow in a collapsed group. Empty pending reads "No decisions waiting".

Detail for a completion exception: title from the issue location, then `KeyValue` for issue, job, submission, scope, primary target, work area. Then the failed requirement as a prominent `Notice` in the attention pair: each `unmet` item in words, and the `score_gate` sentence "90 of 95 for payment". Then before and after `EvidenceImage` side by side with `job_id` passed to the content URL. Then `findings` and `prerequisites`. Then the one action.

Action: `ActionButton` "Request completion", rendered only when `kind` is completion, `status` is PENDING and `allowed_next` contains the string `request_completion`. It posts `POST /api/exceptions/{id}/request-completion` with `submission_id` and `expected_job_revision` from `job_revision`. On OK the page shows `SavedState` "Decision saved" with the event id, then polls `GET /api/invocations/{invocation_id}` and shows "Processing resumed" with the verbatim status until COMPLETED, WAITING or ERROR. The button disables while a request is pending and after success. On 409 the page re-reads the exception and shows "This item changed since you opened it" while keeping the view. Actionable API errors keep their reason code text.

Detail for authority, no_vendor and budget exceptions: the saved reason code, scope, and the current limits from `GET /api/budget` when the kind is budget. No action button. The text says the exception is recorded for the operator and names what would unblock it.

There is never a Pay, Approve or Close button on this surface.

### 7.4 Crew Form, `/crew` and `/crew/jobs/:jobId`

Crew persona only. `/crew` reads `GET /api/crew/jobs` and lists the vendor's jobs as cards with location, scope, `Money`, `StatusBadge`, "Awaiting operator decision" when `pending_exception_status` is PENDING, and a link to the job. Empty reads "No jobs assigned to this vendor".

`/crew/jobs/:jobId` reads `GET /api/jobs/{id}`. Mobile-first: single column, 16 px gutter, 44 px minimum touch targets, and a primary action bar fixed to the bottom of the viewport under 768 px that holds the current step's one button.

Job card at top: `PageHeader` title is the location; eyebrow "Job {id}"; meta `StatusBadge`, `Money` for `price_cents` with "simulated", policy version. `KeyValue` for scope, work area, primary target, required equipment, crew count. Proof requirements as a checklist from `proof_requirements` in words: check in on site, before photo, fresh after photo, same scene, target removed, no new hazard, area clear.

Stepper with four steps, each a `SectionCard` that unlocks in order and shows its saved timestamp once done:

1. **Accept.** `ActionButton` "Accept job" posts `POST /api/jobs/{id}/accept` with the expected revision. Shows `accepted_at` after.
2. **Check in.** Latitude, longitude and accuracy fields. When the browser offers geolocation the fields fill from it with a "Use my location" button; they remain editable. In sandbox mode only, a secondary button "Use dispatch coordinates, demo" fills them from `dispatch_location` and the form states that the check-in is a demo claim. Posts `POST /api/jobs/{id}/check-in`. Shows `checked_in_at` and the recorded location after.
3. **Proof.** File inputs for Before and After, with `datetime-local` inputs for each observation time. Before is required on the first submission and hidden on a rework submission, where the page says the original before photo is kept and shows it. Selected files stay in component state; the page lists their names so a failed upload keeps them and the retry reuses the same idempotency key. Posts `multipart/form-data` to `POST /api/jobs/{id}/proof` with `before`, `after` and `metadata` JSON, the expected revision, and shows "Received, submission {id}" on 202. Then polls `GET /api/jobs/{id}/proofs/{submission_id}/receipt` and shows the verbatim processing status. When the job read reports VERIFIED, REWORK_REQUIRED or PAID, step 4 fills.
4. **Result.** From the job read and, when the crew can see it, the latest proof item: `Points` against 95, the failed requirements, and `rework_instructions` verbatim in an attention `Notice` with the previous after photo beside it. A rework submission reuses step 3 with only the After input. "Awaiting operator decision" replaces the form while `pending_exception_status` is PENDING; the server rejects new completions anyway.

Failed upload: `ErrorNotice` names the missing or rejected item from `unmet` or the validation details, and the form keeps every value.

Acceptance: each vendor sees only its own jobs, a retried submission returns the existing result, and rework keeps the before photo and the $72 quote.

### 7.5 Resident intake, `/report`

Resident, crew or operator persona; the server requires a selected actor. With no persona the page shows the session notice and the switcher above a disabled form. Reads nothing on load except the session.

Form, single column, 560 px max: 

- Description, textarea, required.
- Location, text, required, with helper text "Street address or nearest intersection. Addresses outside the demo set are saved but cannot be located yet."
- When did you see it, `datetime-local`, optional, with a checkbox "I don't know" that clears and disables the field. Unknown stays unknown; the page never fills the current time.
- Photo, file, optional, JPEG or PNG. The B13 driver's corroborating resident report for criterion 3 sends description, location and observed time only, so no bundled demo photo is needed and none is shipped.
- Nothing about jurisdiction, service code, vendor, price or urgency is asked.

Submit posts `multipart/form-data` to `POST /api/signals` with `description`, `location`, optional `observed_at` in ISO UTC, optional `image`. On 202 the form is replaced by a receipt card: "Report saved", `receipt_id`, `Timestamp` received, and `SavedState` polling `GET /api/signals/{id}/receipt` with the verbatim processing status until COMPLETED, WAITING or ERROR. If the receipt's reason code says the address was not located, the card says the report was received but could not yet be located. There is no status page and no other reporter's data. Errors keep the form state.

## 8. Data flow and state

- Session store: one module holding the last `DemoSessionView`; the frame and pages subscribe. `switch(personaId)` posts, re-reads, and rejects with the API reason on failure.
- Reads: `read<T>(path)` unwraps `ToolResult`, returns `data`, throws `ApiError` on a non-OK outcome or transport failure. Pages keep the last good data visible and labeled "as of" its fetch time when a refresh fails.
- Mutations: `mutate<T>(path, body, {expectedRevision})` adds `X-Steward-Request: 1`, `Idempotency-Key`, and `X-Steward-Expected-Revision` when given. `upload<T>(path, formData, opts)` does the same for multipart. One idempotency key per logical submission is held in component state until the submission succeeds or the user starts a new one.
- Polling: `pollUntil(fn, isTerminal, {intervalMs: 1500, maxMs: 60000, backoff: 1.5})`. Pages decide terminal states. When exhausted the page says processing is still saved and offers manual refresh.
- Board refresh: interval of 20 s gated by `document.visibilityState`.
- Theme: `steward-theme` in `localStorage` is the only stored value. Read inline in `index.html` before first paint.

## 9. Error handling

The P1 table stands. Additions:

| Situation | Behavior |
|---|---|
| Image content 404 or 403 | `EvidenceImage` shows a bordered placeholder with "Image unavailable" and the evidence id; the page continues. |
| Session read fails | Frame shows `ErrorNotice` in the header area with retry; Report remains usable. |
| Persona not allowed for a page | Page body is a `Notice` naming the required persona and containing the switcher. |
| Map tiles fail | `Notice` inside the map frame; list unaffected. |
| Polling exhausted | `SavedState` shows the last verbatim status and a Refresh button; no invented completion. |

## 10. Accessibility

- Every control has a visible label. Placeholder text is never the label.
- Focus ring is `--focus`, 2 px, 2 px offset, on every interactive element including list rows that navigate.
- The flow completes by keyboard: persona switch, navigation, inbox selection, request completion, crew accept, check in, file selection, submit, report.
- Color is never the only signal: badges carry words, the budget bar has labeled segments, markers have labels and list rows.
- Reduced motion honored. Text zoom to 200 percent does not clip.
- Crew Form and Report verified at 360 px; Issue Detail and Board verified at 360, 768, 1024 and 1440.
- Images have alt text built from role and time; decorative glyphs are `aria-hidden`.

## 11. Testing and verification

- `npm run typecheck`, `npm run build` and `npm run test` pass before any page is integrated.
- Vitest with Testing Library: client envelope and error mapping; idempotency key reuse across a retried submission; persona switcher re-reads the session and preserves the selection on failure; theme toggle stores only the theme; each page renders pending, error and empty states with accessible names; labels map every enum value; `Points` and `Money` formatting; Inbox never renders an action when the exception is not a pending completion; Crew stepper unlocks in order; Report never sends `observed_at` when unknown is checked.
- Python: `tests/test_static_frontend.py` as in the P1 spec.
- Contrast: a small script over the token table prints the ratio of every fg-on-bg pair in both themes; all must reach 4.5:1 or the token changes.
- Manual, in the browser against the walked database, with screenshots retained under `docs/evaluations/`: the sixteen criteria mapped to surfaces in the P1 design preflight; keyboard-only run of the flow; dark theme; 360 px crew and report; tile failure.

## 12. Build staging for today

Times are Chicago, approximate, with the 7 PM cutoff and a 5 PM internal target.

| Stage | Window | Work | Gate |
|---|---:|---|---|
| Frame (P1) | 11:00 to 12:45 | Lead: scaffold, tokens, fonts, primitives, client, session, labels, router, static serving, OpenAPI export and types, walked database. | typecheck, build, unit tests, static test, both themes render, contrast script passes. |
| Pages (P2 to P6) | 12:45 to 15:15 | Five subagents in parallel, disjoint files, each with this spec, the P1 report and the walked database. Lead reviews and integrates in order: Issue Detail, Board, Inbox, Crew, Report. | Each page: typecheck, tests, pending and error and empty states, screenshots at 360 and 1280. |
| Polish | 15:15 to 16:30 | Lead: Issue Detail and Board composition, dark theme pass, keyboard pass, evidence sizing, copy, motion. | Sixteen-criterion walk in the browser with screenshots. |
| Ship | 16:30 to 17:00 | Build, static serving check, README and BUILD_PLAN updates, commit. | Clean build served from FastAPI at `/`. |

If the page stage runs long, the order of integration is the order of demo importance: Issue Detail and Board ship polished; Inbox, Crew and Report ship working. Nothing ships that shows a status the API did not return.

## 13. Out of scope

Hosting, AgentCore, a resident status page, notifications, search, filtering beyond the timeline toggle, any operator action other than Request completion, editing of any saved record, and any component library.
