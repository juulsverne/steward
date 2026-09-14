# Steward — Product Requirements Document (v3.2)

**Autonomous neighborhood operations. Steward manages reality, not tickets.**

Steward turns neighborhood reports into verified cleanup, coordinating approved providers and permitting simulated payment only after accepted proof.

| Document control | Value |
|---|---|
| Status | Locked hackathon scope; intended behavior, not an implementation-complete claim |
| Version / reviewed | 3.2 / September 13, 2026 |
| Product owner | Elijah |
| Release | AWS Agents for Humans hackathon, Good Neighbor Agents track |
| Deadline | Monday, September 14, 2026, 5 PM Pacific / 7 PM Chicago; internal target two hours earlier |
| Change in this version | Owner-directed cost optimization: evaluate Bedrock models by role instead of requiring Sonnet everywhere; preserve v3.1 user stories, build contracts and all product gates |

This document is the scope authority. [ARCHITECTURE.md](ARCHITECTURE.md) owns the code and deployment contract; [DEMO.md](DEMO.md) owns the sixteen acceptance criteria and required negative cases; [BUILD_PLAN.md](BUILD_PLAN.md) owns task order, interfaces, engineering defaults and progress receipts; [EVALUATION.md](EVALUATION.md) owns the evaluation protocol; [SUBMISSION.md](SUBMISSION.md) owns release requirements. [VISION.md](VISION.md) contains post-competition ideas. The [README](../README.md) reports what is actually implemented.

**How to read this PRD.** Sections 1–5 explain purpose, scope and users; 6–9 describe journeys, screens and agent/failure behavior; 10–13 define acceptance, success, truth labels and risks; 14–16 summarize data/API contracts, quality requirements and the builder handoff. Existing section numbers and PR-01–PR-14 IDs are preserved so build references stay valid. Where a summary and its owning document diverge, reconcile them before implementing the affected behavior; do not silently weaken a product rule or acceptance gate.

**Contents:** [Product overview](#1-product-overview) · [Principles](#2-principles) · [Vocabulary](#3-vocabulary) · [Scope](#4-scope) · [Users](#5-actors-and-permissions) · [Journey](#6-the-couch-journey) · [Screens](#7-surfaces) · [Agent](#8-agent-behavior) · [Failures](#9-failure-behavior) · [Requirements and stories](#10-requirements) · [Done and success](#11-definition-of-done) · [Truth labels](#12-truth-labels) · [Risks and decisions](#13-risks-assumptions-and-open-items) · [Data and API](#14-data-lifecycle-and-api-contracts) · [Quality](#15-non-functional-requirements) · [Build handoff](#16-build-handoff-and-change-control).

## 1. Product overview

Steward is an autonomous neighborhood operations agent. A district supplies a service area, an operating policy, a budget, approved providers, and explicit authority. Steward listens to authorized community signals and public service data, investigates whether a physical issue exists, reconciles conflicting evidence, determines responsibility, dispatches approved providers when policy allows, verifies that the condition actually changed, and settles (simulated) only on accepted proof. It brings the operator the decisions it cannot make. Its unit of responsibility is an unresolved physical condition, not a message, a ticket, or a contractor task.

### 1.1 Problem and product value

A neighborhood operator receives observations from residents, community channels and service records, but must still connect them to the same physical condition, establish responsibility, arrange authorized work and check whether it was finished. A closed record can disagree with a newer photograph; a crew submission can show only partial completion. Treating either as resolution leaves the operator responsible for discovering the gap.

Steward's proposed value is continuity of responsibility from observation to verified outcome, with human attention directed to a specific unresolved decision. The hackathon tests that mechanism on a seeded case. It does not establish customer demand, operating savings, municipal performance or production reliability. Commercial positioning and expansion belong in VISION.md.

### 1.2 Goals and observable success

| Goal | What the finished proof must demonstrate | Verification owner |
|---|---|---|
| G-01 Keep one coherent case | Independent observations corroborate the couch without manufacturing witnesses or merging different nearby conditions | PR-01–05/14; DEMO 1–5 and negatives |
| G-02 Exercise bounded autonomy | Steward chooses to wait, investigate and dispatch; stored authority and budget determine whether dispatch succeeds | PR-04–06; DEMO 2–7 |
| G-03 Pay only for accepted completion | Partial proof causes a real denial; human-directed rework and fresh accepted proof permit exactly one simulated settlement | PR-07–11; DEMO 8–15 |
| G-04 Make decisions understandable | A tester can explain the wait, official dispute, failed proof, operator action and permitted payment from the UI | PR-12; DEMO 5/9–15 |
| G-05 Make the result reproducible | Saved state survives interruption; a documented reset reproduces the flow; evaluation publishes actual outcomes | PR-13; DEMO 16/negatives; EVALUATION |

These are build outcomes. They introduce no adoption targets, new analytics product or additional release checklist.

### 1.3 Hackathon proof

The hackathon proves this with one dumped couch near 1530 S Michigan Ave in the South Loop Demo District, using real agent execution and real vision against seeded district and provider data, with simulated dispatch and settlement. Three judgments must be visible:

1. **Wait.** The first signal scores 65 evidence points against an actionable threshold of 70. The 311 lookup finds a COMPLETED city record, which does not count as corroboration. Steward records the conflict and waits.
2. **Dispute.** A second independent report raises the score to 85. Two observations newer than the official completion confirm the dispute; the record is credited and the score is 100. The issue stays open despite the city's closed record.
3. **Block payment.** After authorized dispatch at $72, the crew's partial cleanup scores 90 verification points against 95 required. The settlement tool denies payment. The operator requests completion; fresh proof scores 100; one simulated $72 settlement occurs and the issue resolves.

## 2. Principles

1. Physical condition is the source of responsibility; a closed record or a Done button does not resolve a couch.
2. A signal is an observation, not an instruction to spend.
3. Autonomy includes choosing to wait, and a wait states what would unlock action.
4. The model interprets; deterministic code scores, prices, authorizes, verifies, and settles.
5. Human attention is reserved for exceptions, delivered with enough context to decide.
6. Verification requirements are stated before work starts.
7. Every claim carries its source and its label: live, seeded, synthetic, or simulated.

## 3. Vocabulary

| Term | Meaning |
|---|---|
| Signal | One observation: source, author identity, content, reported place, observation time, receipt time, provenance |
| Issue | Steward's canonical record of one physical condition; several signals can support it |
| Official record | An external system's account of a service request: status, times, source mode |
| Evidence | Images, source facts, locations, times, and structured findings behind a decision |
| Resolution plan | Proposed service, authority, scope, provider requirements, fixed quote, verification requirements |
| Job | One authorized provider assignment for one issue and scope |
| Exception | A pending human decision outside autonomous permission or adequate evidence |
| Settlement | The policy-authorized simulated transfer for a job |
| Event | A durable observation, decision, tool result, or human action in the audit timeline |

A signal is never a job, a spending approval, or an independent witness merely because it has a new ID. An official record is never ground truth about the physical condition. Evidence points and verification points are never model confidence. The V1 couch has one job; rework stays on that job, quote, and reservation.

## 4. Scope

### 4.1 Inputs

Exactly three, and every input becomes a Signal first:

1. **South Loop Neighbors feed**, labeled *Simulated opt-in community channel*, seeded from a fixture.
2. **Direct resident report** through a real web form in the app.
3. **Chicago 311 / public service lookup**, served from a labeled fixture record with source mode and timestamps. A live lookup behind a flag is tier 4.

Independent observations link to one canonical Issue. Reposts, same-author messages, identical text, and identical images are one observation. Unknown identity is unknown, not a new witness.

### 4.2 Authorized work and policy numbers

The South Loop Demo District supplies a service boundary, an operating policy, a seeded budget, ten seeded addresses with coordinates, and three approved vendors: South Loop Services, Windy City Maintenance, and Lakefront Clean Team. Provider eligibility is a fixture: approved category, service area, equipment, availability, verified-insurance flag. The agent selects among eligible providers using distance, availability, workload, and performance facts. It cannot invent a provider, a rate, an insurance status, or authority.

Autonomous categories: litter, bulky waste, approved graffiti removal. Route to the city: potholes, streetlights, traffic signals. Never dispatch: electrical, structural, hazardous material. Unknown responsibility goes to review. A mixed couch-plus-hazard observation keeps the hazard and blocks autonomous cleanup. A demo district claims no real municipal authority.

**Evidence points** are deterministic and computed from stored facts. Actionable at 70; the total is capped at 100 while the individual components remain inspectable.

| Fact | Points |
|---|---:|
| Image evidence | 30 |
| Independent sources | 20 each, capped at 2 |
| Precise geocode (within 30 m) | 15 |
| Matching service record | 15, per the rule below |
| Condition persists | 10, once per issue |

**Service record rule.** The 311 lookup runs once per new signal linked to an issue and is cached per issue. An OPEN or IN_PROGRESS matching record corroborates existence and is credited immediately. A COMPLETED matching record is a competing claim, not corroboration: it is credited 0 and recorded as a pending conflict until two independent observations newer than its completion time confirm the dispute, at which point it is credited. No match is 0. One unverified photo does not overrule the city's closed record; two do.

**Persistence rule.** The same reporter re-observing the same issue with a fresh image at least 24 hours after their previous observation adds 10 points, once. A lone persistent reporter reaches 75 and Steward acts.

The required lookup uses a fixture and has no external quota dependency. Before enabling the tier-4 live adapter, verify that provider's current access and rate limits and configure bounded requests; one lookup per signal is not a general rate-limit guarantee.

**Contract.** Bulky waste is $60 base + $12 large object = $72. The model selects the service; code computes the price. The autonomous dispatch limit is $100. Dispatch reserves the quote once; settlement consumes it once; cancellation of an unpaid job releases it once.

The seeded district budget is **$500**. Available = starting budget − outstanding reservations − settled spending. After dispatch: available $428, reserved $72, spent $0. After denied proof and rework those amounts stay unchanged. After settlement: available $428, reserved $0, spent $72. Unpaid cancellation releases the reservation and restores available $500 in this single-job example. Store all amounts as integer cents; this is a demo ledger, not a payment integration.

**Verification points** are deterministic checks over Bedrock's structured findings. Automatic payment at 95.

| Check | Points |
|---|---:|
| GPS check-in within 30 m of the job | 30 |
| After image later than before image | 10 |
| Target removed | 40 |
| No new hazard | 10 |
| Area clear | 10 |

Prerequisites before any score counts: target present in the before image, same scene, no reuse of a prior completion photo (a perceptual match against previously submitted completion photos, never against the before image), no unresolved unknown findings. Partial cleanup scores 90; complete cleanup scores 100.

### 4.3 Surfaces

- **Operations Board**: district identity and demo label, attention count, watching/active/review/resolved counts, available budget, Leaflet map with OpenStreetMap tiles.
- **Issue Detail**: source evidence, official-record comparison, plan and job, ordered decision timeline. Highest polish.
- **Operator Inbox**: pending exceptions with one action, **Request completion**.
- **Crew Form**: one job; accept, check in, attach proof, submit; rework instruction.
- **Resident intake**: a small form inside the app; description and location required, image optional.

A persona switcher in the header selects Operator, Crew (per vendor), or Resident. It is a labeled sandbox, not authentication. The server binds every event to the selected actor context.

The confirmed visual direction is professional, credible and contemporary, with both light and dark themes and light as the default. Evidence, readable decisions and usable mobile forms lead the design. BUILD_PLAN P1 owns shared styles, component interfaces and technical verification; a visual study does not constitute a working application or close the API gate.

### 4.4 Stack and deployment

- One Strands agent on Amazon Bedrock, with models selected by measured task quality and total cost. Text reasoning and image inspection may use different models; no second autonomous agent. [MODEL_SELECTION.md](MODEL_SELECTION.md) maps every workflow step to its model need, candidate costs, actual component results and promotion gates. Sonnet is the current baseline, not a permanent requirement for every call. Existing configuration still uses one model until separate role settings are implemented.
- A FastAPI service owns local SQLite state, enforces policy at every mutation, and serves the built React/Vite frontend as static files. App Runner is the hosting target, conditional on the durable-state decision in section 13; its container filesystem is not an approved durable database or image store.
- The agent runs on Amazon Bedrock AgentCore Runtime with AgentCore Observability (traces to CloudWatch). Agent tools are HTTP clients of the API, always: localhost in development, the App Runner URL with a service token in deployment. AgentCore Gateway exposes the same API operations as MCP tools once Runtime works.
- Seeded geocoding: the ten addresses ship with coordinates. Live geocoding behind a flag is tier 4.

### 4.5 Build order

Each tier starts only after the previous tier passes. Nothing below is cut; lower tiers slip if time runs out.

1. **Core proof**: all sixteen [acceptance steps](DEMO.md) pass locally through the API with real Bedrock, the fixture 311 record, and seeded coordinates.
2. **Presentation**: the four surfaces plus resident intake and persona switcher; the [evaluation](EVALUATION.md) scenarios run through Steward with published counts; README, architecture diagram, video.
3. **AgentCore and hosting**: agent on AgentCore Runtime with Observability, UI and API on App Runner with a public judging URL, then Gateway. Gateway is the first item to slip.
4. **If time remains**: live 311 lookup behind a flag, Amazon Location geocoding behind a flag, plain-model comparison arm of the evaluation using the selected text model. A separate Sonnet comparison must disclose model differences.

### 4.6 Exclusions

No real payments, open labor marketplace, bidding, worker onboarding, insurance-verification service, procurement, tax allocation, production fraud detection, full SSA integration, multi-city operation, advanced routing, preventive maintenance, learning engine, resolution-graph analytics, full community verification, Cedar, multiple agents, Flock, TikTok, Facebook, X, resident status page, or operator payment override. Once the sixteen steps pass through the UI, stop adding product.

## 5. Actors and permissions

### 5.1 Users and jobs to be done

| Actor | Need and success | V1 interaction |
|---|---|---|
| District operator — primary user | Understand unresolved conditions and decide exceptions without coordinating every routine step | Board, Issue Detail and Inbox; Request completion on a pending failed-proof exception |
| Assigned provider crew | Know the agreed scope, price and proof requirements; understand exactly what remains after rejection | Own vendor's Crew Form; accept, check in, submit proof and perform requested rework |
| Resident | Report what they observed without knowing jurisdiction, contractor categories or internal workflow | Description/location and optional image; persisted receipt, no resident tracking portal |
| Steward service | Investigate current evidence and request the next permitted action within district authority | One event-triggered agent using typed HTTP tools; code enforces every mutation |

A judge or builder reviews the same labeled sandbox experience. That is not another operational role. The personas describe intended users of the workflow; seeded identities and provider facts do not imply real customers or municipal participation.

### 5.2 Permission boundary

| Capability | Resident | Assigned crew | Operator | Steward service |
|---|---|---|---|---|
| Submit a signal | Yes | Same form | Same form | Ingest authorized sources |
| See receipt / status | Receipt | Own job | District issues | All |
| Inspect full timeline | No | Job facts only | Yes | Yes |
| Accept, check in, submit proof | No | Own job only | No | Validate and process |
| Request completion | No | No | Pending exception only | Create exception |
| Choose and dispatch provider | No | No | No | Policy-gated |
| Verify proof | No | No | No | Findings plus deterministic checks |
| Authorize simulated settlement | No | No | No | Policy-gated |
| Resolve issue | No | No | No | Policy-gated on accepted proof |
| Change policy, rates, budget | No | No | No | No |

Every event carries an actor record: `actor_id`, `actor_type` (`resident`, `crew`, `operator`, `service`), display label, and optional `vendor_id` and `district_id`. Handlers bind crew and operator events to the actor context; the crew context must match the job's vendor. A browser field is never authority. The model cannot create an operator decision, forge a check-in, or claim a resident identity. Seeded reporters have stable author IDs across channels so independence is checkable.

## 6. The couch journey

**A. Observe and decide.** A couch photo with a precise seeded address appears in the simulated feed. Steward persists the signal, links it to a candidate issue, and scores 30 + 20 + 15 = 65. The 311 lookup returns a COMPLETED record for that spot with a completion time earlier than the photo; it is shown with source mode and timestamps, credited 0, and recorded as a pending conflict. Steward records MONITORING: "Image, one independent source, and a precise location total 65 evidence points; 70 is actionable. The city marked this removed on [date]; one newer photo does not confirm otherwise. Watching for a second observation or fresh evidence." No job, no reservation. Monitoring persists across invocations and resumes on the next event.

A second resident submits the same couch through the web form under a distinct seeded identity. Steward links it: 85. Two independent observations newer than the official completion confirm the dispute; an official-status-disputed event is recorded and the record is credited: 100. Received time and observation time are stored separately; an old photo uploaded today cannot prove the couch is still there.

**B. Authority.** Policy permits supplemental bulky-waste cleanup in the district. City-only categories are routed with a recorded recommendation, never a claimed contact. Safety-critical observations escalate without entering the dispatch path.

**C. Plan and dispatch.**

| Plan field | Couch |
|---|---|
| Condition | Couch and dumped bags obstructing the sidewalk |
| Location | 1530 S Michigan Ave, seeded coordinates |
| Authority | South Loop Demo District supplemental-cleanup policy (seeded) |
| Service | Bulky waste cleanup |
| Crew and equipment | Truck, two crew |
| Scope | Remove the couch and visible bags; leave the marked work area clear |
| Quote | $60 base + $12 large object = $72 |
| Required proof | GPS check-in, before image, fresh after image, same scene, target removed, no new hazard, area clear |

The agent picks an eligible vendor. The dispatch tool rechecks eligibility, authority, quote, autonomous limit, and available budget, then creates one job and reserves $72 once, labeled simulated. No operator approval is needed on the normal path. A denial returns a reason and next actor without creating a job.

**D. Execute.** The crew sees location, scope, amount, and proof requirements before accepting. Accept and check-in are explicit crew events. Before evidence must show the couch. Submission means *Proof received*, not Verified, Paid, or Resolved.

**E. Reject and ask.** The middle image shows the couch gone and debris remaining. Bedrock returns structured findings; deterministic checks score 30 + 10 + 40 + 10 + 0 = 90. The agent requests settlement; the tool denies it at 90/95, changes nothing, and returns the unmet requirement. Steward records the denial and creates one exception holding scope, before/after images, findings, components, and the failed area-clear check.

The operator selects **Request completion**. The decision is saved once; repeated clicks do nothing; a stale decision is rejected. A new invocation loads the case and sets REWORK_REQUIRED. The crew sees: "Remove the remaining bags and debris in the marked work area and submit fresh proof." Same job, same $72, no second reservation.

**F. Verify, settle, resolve.** Fresh proof passes prerequisites and scores 100. Steward requests settlement; the tool pays $72 exactly once (simulated) and the issue resolves on accepted proof. The Board marker turns green. The timeline keeps the denied first attempt and the operator's decision. A retry of closure after payment never pays again.

## 7. Surfaces

**Visual direction.** Professional, modern civic software that a government agency could plausibly use. Support both light and dark themes, with light as the default. Emphasize readable evidence, precise hierarchy, calm status communication and a clear next action. [.impeccable.md](../.impeccable.md) records the design principles and proposed visual treatment; exact colors, typography and composition remain reviewable. A design study does not satisfy the API gate or constitute an implemented frontend.

**Operations Board.** Answers "what needs me, what is Steward handling, what is actually resolved." Review is a count of pending exceptions, not a lifecycle bucket. Available budget reflects reservations and settled spending. Zero exceptions reads "No decisions waiting", never "Everything resolved". MONITORING stays visibly open with its unlock conditions. An external route never shows a green marker. If the map fails to load, the issue list still navigates. Every color has a text label.

**Issue Detail.** Without a chatbot, a reader can answer: what condition exists and where; which observations support it and whether each is live, seeded, or synthetic; why Steward waited, acted, disputed, or asked; who has authority, what the scope is, and what the contract pays; what proof exists, what failed, and what happens next. Current status first, then latest decision and next actor. Each decision entry shows a concise explanation, evidence references, score components, policy result, and actual tool result. Tool requests are distinguished from successful actions. Model prose never updates the UI to Paid or Resolved.

**Operator Inbox.** Each item ties to an issue, a job, and a specific proof submission, and shows the failed requirement, latest evidence, score and threshold, and the one allowed action. Feedback distinguishes decision saved from processing resumed. A stale item is rejected server-side and the view refreshes.

**Crew Form.** One job: location, scope, amount, state, required evidence. Controls unlock in order: accept, check in, attach proof, submit. Failed uploads keep form state and name the missing item. Rework appears as an instruction on the same job with the failed requirement and image. New proof is a new submission; prior proof is kept. While an exception is pending, the form shows "Awaiting operator decision" and the server rejects new completions. Retries of a received submission return the existing result.

**Resident intake.** Description and location required; image optional; no jurisdiction, service code, vendor, price, or urgency asked. A receipt is issued only after the signal is persisted. An address outside the seeded set is stored with unresolved location, no geocode points, and no dispatch. Observation time is stored separately from receipt time; unknown stays unknown. No other reporter's identity is exposed.

## 8. Agent behavior

**Objective and stopping rule.** Maintain responsibility for an unresolved condition within configured authority: investigate, decide the next action, persist a concise explanation. An invocation ends at resolution, a recorded external route or escalation, a monitoring decision with no new evidence, or an explicit wait for a crew or operator event. It never loops waiting. MONITORING is persisted state that resumes on the next event, not a scheduler.

**Triggers.**

| Trigger | Context loaded | Expected judgment |
|---|---|---|
| SIGNAL_RECEIVED | Signal, candidate links, provenance, policy | New or existing condition; corroboration; lookup; monitor or proceed |
| CREW_ACCEPTED, CREW_CHECKED_IN | Job, actor | Persist the valid transition; no model call needed |
| PROOF_SUBMITTED | Job, before and latest after evidence, prior findings, policy | Inspect; request settlement or raise an exception |
| OPERATOR_DECISION | Pending exception, recorded choice, current job and evidence | Resume with the actual decision; request rework |

The API validates and persists triggers; only reasoning-bearing events invoke the agent. Context comes from the database, never from a browser-supplied transcript. A saved intake trigger may reference only a signal until matching creates or selects its issue; a pending report must not require an invented issue ID.

**Context contract.** Every reasoning run receives its trigger and invocation IDs, server-bound actor context, current state revision, relevant policy and source/observation-time provenance. When present, include the current job/quote/reservation, latest proof and findings, pending exception and actual operator decision; absent records remain absent. Include successful prior effects so recovery does not redispatch or repay. Supply concise, bounded history with explicit truncation and retrievable evidence IDs; never truncate away current failed proof or gating facts. BUILD_PLAN section 6 owns the initial context and invocation limits. No browser transcript, private scratch note or prior model conversation is required to resume.

**Decision record.** Each decision persists `issue_id`, optional `job_id`, `trigger_event_id`, `decision_type` (MONITOR, MARK_ACTIONABLE, DISPUTE_OFFICIAL_STATUS, ROUTE_EXTERNAL, REQUEST_DISPATCH, REQUEST_SETTLEMENT, REQUEST_OPERATOR, REQUEST_REWORK, RESOLVE), a concise `summary`, `evidence_ids`, score components, `policy_version`, gate results, and `next_actor` / `next_event`. Tool calls and results are captured separately under the same invocation ID. Decisions are intentions; only successful action-tool results mutate state. No hidden chain-of-thought.

**Boundaries.**

| Situation | Steward may | Steward must not |
|---|---|---|
| Evidence below 70 | Record monitoring with unlock conditions; run the 311 lookup | Dispatch or reserve funds |
| Actionable condition | Investigate responsibility and propose a plan | Treat evidence points as spending authority |
| Official completion vs newer evidence | Record both; keep the issue open; credit the record once the dispute is confirmed | Close on the official field; invent city contact |
| Eligible plan within policy | Select an eligible vendor and request dispatch | Invent price, provider, budget, or policy |
| Incomplete or ambiguous proof | Request settlement, receive denial, raise the exception | Pay or resolve on a Done claim |
| Operator requests completion | Resume from the saved event and direct rework | Forge the decision; dispatch or pay twice |
| Accepted complete proof | Request settlement and close on evidence | Treat an earlier pass as current after newer failed proof |

Scores, prices, eligibility, budget, and verification come from code over stored facts; the model cannot supply them. Dispatch and settlement re-read stored state at execution time. Crew and operator events come only from their surfaces. External routes record a recommendation, labeled simulated.

**Denials and errors.** Tools return OK, DENIED, NEEDS_REVIEW, NOT_FOUND, or ERROR with a stable reason code, unmet requirements, allowed next actions, evidence IDs, and persisted event IDs. Step 10 requires an actual denied settlement request in the timeline; a fabricated denial is a defect. Retries are bounded; a denied action is not retried without changed facts. On model or lookup failure, evidence and state are preserved and a recoverable error event is recorded.

**Input trust.** Resident posts, records, image text, filenames, and provider notes are untrusted observations. Embedded instructions to change rules, call tools, alter budgets, or release payment are ignored; tool handlers enforce authority regardless. Provenance (live, seeded, synthetic) is stored with the evidence, not left to a disclaimer.

## 9. Failure behavior

| Condition | User-visible behavior | Invariant |
|---|---|---|
| Duplicate or reposted signal | Linked with provenance; no source bonus | Records do not manufacture witnesses |
| Uncertain issue match | Observations kept distinct; uncertainty recorded | Nearby conditions do not merge silently |
| Missing or ambiguous geocode | Uncertainty explained or review requested | No invented location points or authority |
| Lone reporter, no city record | Watching, with unlock conditions shown | Waiting is explicit, not silent |
| 311 lookup unavailable | Labeled unavailable | Failure is not evidence either way |
| Old or unknown-time photo | Time provenance shown; freshness unresolved | Upload time proves nothing |
| No eligible vendor or budget | Dispatch denial and exception recorded | No job beyond authority; no bidding |
| Target absent or uncertain in before proof | Job held unpaid; review requested | No payment for unestablished removal |
| Mixed cleanup and hazard | Hazard preserved; escalated | A benign category cannot bypass the hazard |
| Unpaid job cancelled | Cancellation recorded; reservation released once | No payment; no cancellation UI required |
| Wrong scene, reuse, unknown finding | Proof marked unsuitable; review requested | Score cannot bypass prerequisites |
| Model failure or malformed output | Recoverable processing error shown | No fabricated findings or payment |
| Stale decision or repeated request | Rejected, or existing result returned | Effects happen once |
| Restart during human wait | Case and pending decision reload | No dependence on a live session |
| Payment succeeds, closure interrupted | Paid job with unresolved finalization; retry closes | Settlement never repeats |

Two requests arriving together cannot both spend one reservation or settle one job. After resolution, new reports are new signals for review, not silent merges into a closed issue.

## 10. Requirements

### 10.1 Functional requirement index

Every PR requirement below is required. The four build tiers sequence delivery; they do not turn unfinished mandatory behavior into an optional feature. The acceptance examples that follow make these requirements concrete without replacing DEMO.md.

| ID | Required behavior | Steps |
|---|---|---|
| PR-01 | Persist direct reports with provenance, server signal ID, receipt time, and separate observation time | 3, 16 |
| PR-02 | Ingest the labeled simulated community feed | 1 |
| PR-03 | Link corroborating observations without false independence or false merges | 1–3 |
| PR-04 | Compute explainable evidence components, apply the service-record rule, and persist an explicit watch decision with unlock conditions | 2–4 |
| PR-05 | Show a COMPLETED record against newer evidence, confirm the dispute on two observations, credit the record, keep the issue open | 2, 4–5 |
| PR-06 | Build the scoped plan, select an eligible vendor, gate dispatch, reserve once | 6–7 |
| PR-07 | Persist crew acceptance, check-in, and job-linked proof | 8–9 |
| PR-08 | Inspect proof with structured findings, deterministic checks, and prerequisite gates | 9, 12 |
| PR-09 | Deny inadequate settlement, persist the exception, resume after the operator's decision | 10–11 |
| PR-10 | Verify fresh completion and release one simulated settlement | 12–13 |
| PR-11 | Close on accepted completion and reflect outcome and budget on the Board | 14–15 |
| PR-12 | Expose evidence, decisions, policy results, and actual tool actions throughout | 1–15 |
| PR-13 | Reset the demo dataset and reproduce the flow with truthful labels and no hidden edits | 16 |
| PR-14 | Credit the persistence bonus once for a same-reporter fresh observation at least 24 hours later | evaluation |

UI vocabulary: Watching is MONITORING; Request completion leads to REWORK_REQUIRED; Proof is a crew submission; Evidence is everything supporting a decision. An exception is pending human attention, not an issue status. The sixteen criteria in [DEMO.md](DEMO.md) are the release contract; this document adds no second checklist.

### 10.2 User stories and acceptance examples

**US-01 — Report an observation** (resident; PR-01/02/03, DEMO 1/3/16). As a resident, I want to report the condition in ordinary words so that reporting does not require operational knowledge.

- **Given** a description and reported location, with an optional image and observation time, **when** intake succeeds, **then** the signal and receipt time are persisted before a receipt is shown. Unknown location or observation time remains unknown; later matching preserves the original signal. A failed save never looks successful. Feed ingestion preserves stable source identities and its simulated-channel label.

**US-02 — See why Steward waits** (operator; PR-04/05/12, DEMO 2). As an operator, I want an explicit waiting decision so that I can distinguish insufficient evidence from forgotten work.

- **Given** one image, one independent witness and a precise location, **when** the matching 311 record is COMPLETED, **then** the score stays 65, the conflict is pending and the issue is MONITORING with unlock conditions. No job or reservation exists. A restart reloads that wait without keeping a model session alive.

**US-03 — Reconcile conflicting evidence** (operator; PR-03/04/05/12, DEMO 3–5). As an operator, I want the city record and newer observations considered together so that an administrative closure cannot hide an unresolved couch.

- **Given** the first observation and an earlier city completion, **when** a second independent newer observation corroborates the same couch, **then** the trace shows 85 before dispute confirmation and 100 after the qualifying record is credited. Both observation times, the completion time and source labels are visible. A repost is not independent; a different nearby object is not silently merged.

**US-04 — Delegate authorized cleanup** (operator; PR-06, DEMO 6–7). As an operator, I want routine authorized work arranged within the existing contract so that I do not approve each ordinary job.

- **Given** actionable evidence, known district authority, an eligible vendor and sufficient budget, **when** Steward requests the couch plan and dispatch, **then** code prices it at $72, saves the scope/proof requirements and creates one job and one reservation. Unknown authority, mixed hazards, an ineligible vendor, insufficient budget or an over-limit quote denies dispatch. Retrying cannot create another job.

**US-05 — Submit work against a clear scope** (crew; PR-07/08, DEMO 8–9). As the assigned crew, I want proof requirements before starting so that completion is evaluated against the work I accepted.

- **Given** my vendor's job, **when** I accept, check in and submit valid evidence, **then** those actor events persist in order and the UI says Proof received while inspection runs. Another vendor cannot perform them. Upload failure preserves form inputs and explains what must be fixed; submission alone never means Verified or Paid.

**US-06 — Hold inadequate payment** (operator; PR-08/09/12, DEMO 9–10). As an operator, I want an exception grounded in the failed requirement so that I can request the remaining work.

- **Given** same-scene proof with the couch removed but debris remaining, **when** inspection yields 90 and Steward requests settlement, **then** the actual tool returns DENIED against 95, records the attempt and leaves spent $0/reserved $72. One pending exception references that exact proof and failed area-clear check. Unrelated, reused or uncertain proof cannot pass through score arithmetic.

**US-07 — Request completion and resume** (operator and crew; PR-09/10, DEMO 11–12). As an operator, I want one saved Request completion action to give the crew a specific next step.

- **Given** a current pending exception, **when** the operator chooses Request completion, **then** the decision is persisted once and a fresh invocation requests rework on the same job/quote/reservation. The crew receives the remaining-work instruction. Until the operator acts, new completion submissions are blocked; stale decisions fail and identical retries return their saved result. Fresh rework proof receives a new submission ID and does not overwrite the failed proof.

**US-08 — Resolve on accepted evidence** (operator; PR-10/11/12, DEMO 12–15). As an operator, I want the Board to show actual verified resolution and correct spending so that I can trust its status.

- **Given** current fresh proof that passes every prerequisite and scores 100, **when** settlement and closure succeed, **then** there is one simulated $72 payment, a PAID job, a RESOLVED issue with accepted evidence and a resolution time, and a green marker with a text label. Available/reserved/spent are $428/$0/$72. If closure is interrupted after payment, retry finalizes closure without another payment.

**US-09 — Act on valid lone-reporter evidence** (resident and operator; PR-04/14, EVALUATION 21–22). As a resident, I want useful fresh evidence considered even when no second resident reports.

- **Given** the single 65-point observation, **when** an OPEN matching record corroborates it, **then** it reaches 80; **when instead** the same reporter supplies a fresh image observed at least 24 hours later, **then** the once-only persistence bonus yields 75. Neither path creates another independent witness. Actionability still requires a separate authority/dispatch gate.

**US-10 — Reproduce and recover the case** (builder exercising the operator workflow; PR-13 and cross-cutting failure rules, DEMO 16/negatives). As a builder, I want to start, interrupt and repeat the documented flow so that a successful demo is inspectable.

- **Given** a named demo store and documented setup, **when** the app restarts during an operator wait or after receiving an unfinished event, **then** saved records support recovery without manual database edits. An explicit reset recreates the starting fixtures and preserves separate run evidence. Replays, retries and concurrent requests do not duplicate jobs, reservations, exceptions, decisions or payments.

## 11. Definition of done

### 11.1 Required completion evidence

- All sixteen steps pass through the UI, plus the negative cases in DEMO.md, on a clean install with documented commands.
- A live Strands trace shows evidence-dependent tool choices; a replay or unit test alone does not count. Calling a mutation endpoint directly with a disallowed action is denied.
- The evaluation scenarios run through Steward and publish counts with denominators, failures, and limitations.
- A tester can explain from the UI alone why Steward waited, why it disputed the closure, what the crew failed to finish, what the operator chose, and why payment became permitted. A missing explanation is a defect.
- Labels (live, seeded, synthetic, simulated) match runtime behavior, screenshots, and narration. No customer-savings, municipal-speed, or accuracy claims.

### 11.2 Success measures and claim boundaries

| Measure | Required report | Limit on interpretation |
|---|---|---|
| Couch acceptance | Actual pass/fail for all 16 criteria at API gate, then UI gate; retained trace, final state and reset/repeat evidence | API projections for steps 5/15 do not prove their screen rendering |
| Policy integrity | Direct-call denials and DEMO negative cases; zero duplicate/unauthorized executed financial effects in those tests | Tests prove the exercised cases, not production fraud prevention |
| Internal evaluation | All 22 frozen scenarios; the routing, merge, proposed-action and escalation metrics defined in EVALUATION.md, with numerators/denominators and executed violations separate | No invented pass-rate target, excluded failures or claim of broad reliability; comparison arm remains tier 4 |
| Comprehension | Record whether a tester can explain the five judgments in section 1.2 from the UI, and fix missing explanations | No fabricated user-study percentage |
| Operational behavior | Actual invocation/inspection latency, model/tool errors and token usage; record configuration and run versions | Measured observations, not a promised response-time or dollar-cost SLA |
| Release/access | Clean-install evidence, truthful artifacts and verified judging access under SUBMISSION.md | Local tests, a video or a provisioned service do not prove hosted acceptance |

The sixteen-step acceptance run, twenty-two-scenario evaluation and twelve-inspection vision spike have different denominators and purposes. Keep their results separate. A deterministic replay can reproduce events; model wording or tool ordering need not be byte-identical when the required judgments and policy outcomes are preserved.

## 12. Truth labels

| Real, once implemented and verified | Seeded / demo | Synthetic | Simulated |
|---|---|---|---|
| Strands loop and tool choice, Bedrock inference and vision, deterministic scoring and policy, persistence, actor events, vendor matching, UI, evaluation, AgentCore deployment | District area, authority, budget, vendors and rates, community feed, reporter identities, ten addresses and coordinates, 311 record | Generated demo images, with provenance | Municipal and contractor dispatch, contractual relationships, settlement, procurement |

Replays never masquerade as live inference. Public assets carry provenance and usage rights.

## 13. Risks, assumptions and open items

### 13.1 Assumptions and mitigations

| Assumption / risk | Required response | Build owner |
|---|---|---|
| Synthetic images and seeded identities simplify the case | Preserve source labels; test duplicates, mismatched scenes and unknown findings; publish fixture limitations | B3/B4/B7; P8/P9 |
| A bounded vision result may be wrong | Keep prerequisite gates and deterministic scores; any false automatic acceptance blocks the affected unattended-verification claim | B7; VISION_SPIKE; P8 |
| Selected Bedrock access may expire or fail | Verify live inference for the candidate run; retain failure events and recover without fabricated observations | B11/B12; R1 |
| A persona switcher can be mistaken for real identity verification | Label sandbox access; bind server sessions and enforce vendor/actor permissions; keep service credentials server-side | B2; P1; H4 |
| Accepted events or money state can be lost or replayed during interruption | Persist triggers, revisions and once-only effects; test recovery, concurrent requests and interrupted closure | B1–B12 |
| App Runner's container files cannot fulfill the hosted persistence contract | Resolve durable records, proof bytes and pending work before deploying; seed/reset is not recovery | H1–H6 |
| Time pressure encourages scope expansion or inflated completion claims | Follow the four tiers; preserve unfinished gates; move new product ideas to VISION.md | All tasks; R1/R2 |

### 13.2 Decision register

| Item | Position | Blocks |
|---|---|---|
| Vision spike | Component gate passed September 13: four before→completion pairings × three repeats, 12/12 expected outcomes, documented in [VISION_SPIKE.md](VISION_SPIKE.md). Rerun affected checks if images, model, prompt or verification logic change; prior results do not establish full workflow acceptance | No remaining blocker for the tested fixture spike; API/UI proof remains open |
| App Runner and AgentCore specifics | Hosting durability conflict recorded in [DOCUMENT_REVIEW.md](DOCUMENT_REVIEW.md): App Runner local files cannot be the durable SQLite owner. Prepare H1's concrete storage/topology and real AWS cost recommendation at kickoff, before freezing storage assumptions. Implement and prove the selected hosted arrangement after tier 2 with the owner decision and spending ceiling recorded | Early design input; tier-3 implementation |
| Model choice and cost | Initial eight-model tool screen and five-model photo screen recorded in MODEL_SELECTION.md. Cheaper text candidates are viable integrations, not qualified domain agents. Keep Sonnet for the current image prompt; build role settings and pass task/full-workflow gates before promotion | M0; B4/B7/B11–B13; P8 |
| Tier-4 flags | Live 311, Amazon Location, plain-model evaluation arm; only after tier 3 | Nothing required |

Routine parameters are decided in the build documentation with evidence. No open item permits changing thresholds, scope, or labels silently.

## 14. Data lifecycle and API contracts

### 14.1 Logical records and ownership

This is the product-level data dictionary. ARCHITECTURE owns physical fields and lifecycle values; BUILD_PLAN B1/B2/B10 owns typed schemas and endpoint contracts. The records below are requirements, not a claim that all tables exist. Keep one authoritative FastAPI/store boundary and the existing Python package.

| Record | Minimum product information | Creation / invariant |
|---|---|---|
| Signal | Source/author lineage, content, reported place, observation time, receipt time, provenance and evidence references | Intake or authorized adapter; persisted before matching; receipt does not imply corroboration |
| Issue and source links | Canonical condition/location/category, responsibility, lifecycle, source links, evidence components and resolution evidence/time | Validated matching/state operations; separate nearby conditions stay distinct when uncertain |
| Official record / lookup receipt | External record ID/status, completion and lookup times, source mode, match and conflict/dispute facts | Trusted adapter; an official-record Signal never becomes another resident witness or recursively starts lookups |
| Plan | Condition, service, authority, scope, required equipment, server-priced quote and proof requirements | Model proposes work; server derives price/eligibility from stored policy |
| Job | Issue/plan/vendor, agreed amount, status, actor events and check-in | Authorized dispatch; one couch job, with rework on the same quote |
| Evidence / proof submission | Immutable submission ID, issue/job, before/after role, image reference/digest, times/location and provenance | Validated upload/adapter; bytes must remain available whenever saved evidence references them |
| Inspection | Exact submission, structured nullable findings, prerequisite results, score components, model/prompt/policy versions | Trusted inspector; a stale inspection cannot authorize newer proof |
| Exception and operator decision | Issue/job/proof, unmet requirement, pending/handled state, actual actor choice/reason/time | Service creates exception; operator saves choice; service consumes the current choice once |
| Budget, reservation and payment | Starting budget, outstanding reservation, settled amount, job and idempotency links | Transactional policy boundary; integer cents and simulated settlement only |
| Event, decision, request receipt and invocation | Trigger/actor/entity IDs, revision, outcome/reason, evidence, safe trace references and processing status | Append-only history plus persisted processing state; intentions do not claim successful actions |

Policy, district boundary, providers, rates and addresses are versioned seed/configuration inputs. There is no policy editor. Save source facts and their uncertainties; never infer an observation timestamp from an upload timestamp. Use UTC internally and show understandable timestamps with a timezone in evidence comparisons.

### 14.2 Lifecycle and retention

The ordinary issue lifecycle is `CANDIDATE → MONITORING → ACTIONABLE → RESOLUTION_ACTIVE → RESOLVED`. The ordinary job lifecycle is `POSTED → ASSIGNED → CHECKED_IN → PROOF_SUBMITTED → VERIFIED → PAID`; requested rework returns through `REWORK_REQUIRED → PROOF_SUBMITTED`. ARCHITECTURE defines alternate states and valid transitions; these arrows do not require an unnecessary watch step for already-actionable evidence.

An official-status dispute is a fact/event, not a replacement for the issue's active lifecycle. A pending payment exception leaves the issue active and the job unpaid. Routed externally does not mean resolved. New observations after resolution become signals for review, not silent edits to the completed case. Board counts and budgets come from stored records, not model prose.

Keep failed and accepted proof, decisions and audit events through the demo run and recovery. An explicit reset affects only its named demo store and associated demo assets, never source fixtures, unrelated stores or separately retained run artifacts. No automatic retention purge, resident history portal or production records-management system is implied. Public release artifacts use publishable, labeled inputs; the sandbox is not a place to collect private resident reports.

### 14.3 API and tool interaction

| Caller / operation | Contract |
|---|---|
| Resident intake | Submit description/location and optional evidence/time; server binds reporter context and returns a durable receipt before agent processing |
| Crew events | Bound vendor/job, explicit accept/check-in/proof actions; validate transition and evidence requirements at the API |
| Operator action | Reference the exact pending exception/proof and revision; save Request completion before starting the resume invocation |
| Agent reads and proposals | Retrieve bounded case facts; submit validated classification/responsibility/plan/decision proposals; never submit authoritative scores, money or human identity |
| Agent action tools | Call the same gated HTTP operations locally and on AgentCore; server recomputes authority and returns the actual persisted result |
| UI reads | Receive role-scoped board/issue/job/exception projections and saved processing state; never query SQLite or render an invented action transcript |

All mutations carry idempotency keys; stale-sensitive operations also reference expected revision and exact submission/exception IDs. An identical retry returns the existing result; a changed payload under the same key conflicts. Business state and its audit event commit together. A denial may append an audit event while leaving the job and money unchanged. Never hold a write transaction open during Bedrock or other network calls.

Use the shared `ToolResult` outcomes in section 8: `OK`, `DENIED`, `NEEDS_REVIEW`, `NOT_FOUND`, `ERROR`, with reason, data, unmet requirements, allowed next actions and evidence/event IDs. BUILD_PLAN section 12 contains the planned endpoint map; FastAPI/OpenAPI and typed models must agree before tools/screens depend on them. API routes and HTTP status mappings are implementation contracts, not independent product policy.

## 15. Non-functional requirements

These requirements make the existing journey usable and trustworthy. They attach to current build tasks and acceptance/negative cases; they add no new product surface. Engineering defaults may be adjusted with evidence in BUILD_PLAN, while product thresholds and permissions remain locked.

| ID | Required property and verification | Build owner |
|---|---|---|
| NFR-01 Durability | Reopen the store and resume a pending operator decision or accepted unfinished event with the same evidence and ledger; migrate existing state without silently resetting it | B1/B3/B12; H1/H6; R1 |
| NFR-02 Once-only effects | Concurrent/repeated requests cannot duplicate a job, reservation, exception, operator action or payment; failed writes roll back; latest proof and revisions are checked at mutation time | B1/B5–B9/B12; DEMO negatives |
| NFR-03 Actor and service boundaries | Server binds actor/vendor/district; direct requests obey section 5. A sandbox user cannot select service identity, and the frontend contains no service token or AWS credentials | B2/B10; P1; H4/H6 |
| NFR-04 Input and image safety | Treat text/image instructions as data; validate schema and image bytes, normalize images and compute hashes server-side; reject malformed/oversize uploads and filesystem paths. B3 starts with JPEG/PNG and a documented 10 MiB upload cap | B2/B3/B7/B11 |
| NFR-05 Privacy and provenance | Expose only each role's permitted records; keep other reporter identities out of resident responses. Preserve source labels; exclude credentials and hidden chain-of-thought from prompts, traces, browser payloads and published artifacts | B2/B10–B12; P6/P9; R2 |
| NFR-06 Bounded work and cost visibility | End invocations at their stopping conditions; never loop on unchanged denials. A denial can lead to escalation in the same run. Begin with BUILD_PLAN's 12 model cycles, 40 tool calls, up to 3 transient attempts per external request and 120-second invocation deadline; the deadline bounds retries too. Record latency/usage, do not promise a dollar cost or unlimited retries | B10–B12; P8; H2/H4 |
| NFR-07 Truthful responsiveness | Save input before acknowledging it; distinguish saved, processing, waiting, failed and completed states. Show recoverable errors, preserve form input on upload failure and reject stale decisions visibly. Long model work does not hold the request's write transaction | B3/B6/B8/B12; P1–P7 |
| NFR-08 Accessible surfaces | Complete the flow by keyboard with labeled controls and visible focus; pair status colors with text. Verify crew/intake on a narrow mobile layout and preserve navigation if map tiles fail | P1–P7 |
| NFR-09 Auditability | Link each actual decision, tool result and human action to trigger/invocation/evidence IDs, policy version and current state; retain the denied attempt after successful rework | B1/B10–B12; P2/P8; H3 |
| NFR-10 Reproducibility | Record candidate commit, locked dependencies, model/region, prompt/tool/policy/fixture versions, exact commands, outputs and failed cases. Public instructions must suffice without ignored local notes | B13; P7/P8; R1/R2 |
| NFR-11 Environment parity | Keep one HTTP tool implementation and one mutation authority. Hosted persistence must retain records, proof bytes and pending work across requests and instance replacement before hosted acceptance is claimed | B10; H1–H6 |

The local prototype has no production uptime, throughput or geographic-coverage promise. Measure actual demo latency and failure behavior; do not copy performance or enterprise-security claims from another project's PRD.

## 16. Build handoff and change control

1. Read AGENTS.md, this PRD, ARCHITECTURE, DEMO and BUILD_PLAN. Check the actual branch, working tree and current implementation before choosing the first unfinished task.
2. For that task, identify its PR/story/NFR IDs, input/output contracts, mutation/actor rules and named success/failure evidence. BUILD_PLAN owns M/B/P/H/O/R task packets, coding-worker/reviewer model assignments and the full coverage map. The owner has requested delegated development once the build starts; one implementation writer owns the shared checkout at a time.
3. Preserve the four-tier sequence: sixteen outcomes through the API before surfaces, UI/evaluation/presentation before hosting, then optional flags. A unit test, spike or planned command does not close a later gate.
4. Record changed files/interfaces, actual commands/results and remaining limits in the task receipt; update README/build status only when evidence supports it. Keep requirement changes synchronized across their owning documents.
5. Resolve routine engineering choices within the existing scope and record them. New product ideas go to VISION; threshold/authority changes or the H1 hosting adjustment need an explicit recorded decision. Publishing, deployment and submission retain their separate authorization gates.

The September 13 checkpoint remains component-level: Tier 1A is verified and pure Tier 1B policy/fixtures exist; the complete event API, financial workflow, Steward prompt/tools, UI, evaluation and hosting are unfinished. At kickoff verify B0, prepare H1's early recommendation, implement M0's model-setting boundaries and continue with B1. The Mac mini is the SSH development host for persistent headless coding, separate from the AWS judging host; source handoff and remote runtime readiness must be verified independently.
