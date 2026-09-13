# Steward — hackathon build spec (v3)

**Autonomous neighborhood operations. Steward manages reality, not tickets.**

Status: build specification for the AWS Agents for Humans hackathon, Good Neighbor Agents track. Deadline Monday, September 14, 2026, 5 PM Pacific / 7 PM Chicago; internal target two hours earlier. This document is the scope authority for the hackathon build. [ARCHITECTURE.md](ARCHITECTURE.md) is the code contract, [DEMO.md](DEMO.md) the acceptance criteria, [BUILD_PLAN.md](BUILD_PLAN.md) the sequencing, [EVALUATION.md](EVALUATION.md) the evaluation protocol, [SUBMISSION.md](SUBMISSION.md) the release checklist, and [VISION.md](VISION.md) everything after the hackathon. This document describes intended behavior; the README reports what is implemented.

## 1. What we are building

Steward is an autonomous neighborhood operations agent. A district supplies a service area, an operating policy, a budget, approved providers, and explicit authority. Steward listens to authorized community signals and public service data, investigates whether a physical issue exists, reconciles conflicting evidence, determines responsibility, dispatches approved providers when policy allows, verifies that the condition actually changed, and settles (simulated) only on accepted proof. It brings the operator the decisions it cannot make. Its unit of responsibility is an unresolved physical condition, not a message, a ticket, or a contractor task.

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

**Evidence points** are deterministic and computed from stored facts. Actionable at 70.

| Fact | Points |
|---|---:|
| Image evidence | 30 |
| Independent sources | 20 each, capped at 2 |
| Precise geocode (within 30 m) | 15 |
| Matching service record | 15, per the rule below |
| Condition persists | 10, once per issue |

**Service record rule.** The 311 lookup runs once per new signal linked to an issue and is cached per issue. An OPEN or IN_PROGRESS matching record corroborates existence and is credited immediately. A COMPLETED matching record is a competing claim, not corroboration: it is credited 0 and recorded as a pending conflict until two independent observations newer than its completion time confirm the dispute, at which point it is credited. No match is 0. One unverified photo does not overrule the city's closed record; two do.

**Persistence rule.** The same reporter re-observing the same issue with a fresh image at least 24 hours after their previous observation adds 10 points, once. A lone persistent reporter reaches 75 and Steward acts.

Rate limits are not a concern at one lookup per signal. Open311 defaults to roughly 10 requests per minute without a key, and the Socrata data portal allows 1,000 per hour with a free app token.

**Contract.** Bulky waste is $60 base + $12 large object = $72. The model selects the service; code computes the price. The autonomous dispatch limit is $100. Dispatch reserves the quote once; settlement consumes it once; cancellation of an unpaid job releases it once.

**Verification points** are deterministic checks over Bedrock's structured findings. Automatic payment at 95.

| Check | Points |
|---|---:|
| GPS check-in within 30 m of the job | 30 |
| After image later than before image | 10 |
| Target removed | 40 |
| No new hazard | 10 |
| Area clear | 10 |

Prerequisites before any score counts: target present in the before image, same scene, no image reuse, no unresolved unknown findings. Partial cleanup scores 90; complete cleanup scores 100.

### 4.3 Surfaces

- **Operations Board**: district identity and demo label, attention count, watching/active/review/resolved counts, available budget, Leaflet map with OpenStreetMap tiles.
- **Issue Detail**: source evidence, official-record comparison, plan and job, ordered decision timeline. Highest polish.
- **Operator Inbox**: pending exceptions with one action, **Request completion**.
- **Crew Form**: one job; accept, check in, attach proof, submit; rework instruction.
- **Resident intake**: a small form inside the app; description and location required, image optional.

A persona switcher in the header selects Operator, Crew (per vendor), or Resident. It is a labeled sandbox, not authentication. The server binds every event to the selected actor context.

### 4.4 Stack and deployment

- One Strands agent on Amazon Bedrock Sonnet, with Bedrock vision for image inspection. No second agent or model.
- A FastAPI service owns SQLite state, enforces policy at every mutation, and serves the built React/Vite frontend as static files, in one container on AWS App Runner.
- The agent runs on Amazon Bedrock AgentCore Runtime with AgentCore Observability (traces to CloudWatch). Agent tools are HTTP clients of the API, always: localhost in development, the App Runner URL with a service token in deployment. AgentCore Gateway exposes the same API operations as MCP tools once Runtime works.
- Seeded geocoding: the ten addresses ship with coordinates. Live geocoding behind a flag is tier 4.

### 4.5 Build order

Each tier starts only after the previous tier passes. Nothing below is cut; lower tiers slip if time runs out.

1. **Core proof**: all sixteen [acceptance steps](DEMO.md) pass locally through the API with real Bedrock, the fixture 311 record, and seeded coordinates.
2. **Presentation**: the four surfaces plus resident intake and persona switcher; the [evaluation](EVALUATION.md) scenarios run through Steward with published counts; README, architecture diagram, video.
3. **AgentCore and hosting**: agent on AgentCore Runtime with Observability, UI and API on App Runner with a public judging URL, then Gateway. Gateway is the first item to slip.
4. **If time remains**: live 311 lookup behind a flag, Amazon Location geocoding behind a flag, plain-Sonnet comparison arm of the evaluation.

### 4.6 Exclusions

No real payments, open labor marketplace, bidding, worker onboarding, insurance-verification service, procurement, tax allocation, production fraud detection, full SSA integration, multi-city operation, advanced routing, preventive maintenance, learning engine, resolution-graph analytics, full community verification, Cedar, multiple agents, Flock, TikTok, Facebook, X, resident status page, or operator payment override. Once the sixteen steps pass through the UI, stop adding product.

## 5. Actors and permissions

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

The API validates and persists triggers; only reasoning-bearing events invoke the agent. Context comes from the database, never from a browser-supplied transcript.

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

## 11. Definition of done

- All sixteen steps pass through the UI, plus the negative cases in DEMO.md, on a clean install with documented commands.
- A live Strands trace shows evidence-dependent tool choices; a replay or unit test alone does not count. Calling a mutation endpoint directly with a disallowed action is denied.
- The evaluation scenarios run through Steward and publish counts with denominators, failures, and limitations.
- A tester can explain from the UI alone why Steward waited, why it disputed the closure, what the crew failed to finish, what the operator chose, and why payment became permitted. A missing explanation is a defect.
- Labels (live, seeded, synthetic, simulated) match runtime behavior, screenshots, and narration. No customer-savings, municipal-speed, or accuracy claims.

## 12. Truth labels

| Real, once implemented and verified | Seeded / demo | Synthetic | Simulated |
|---|---|---|---|
| Strands loop and tool choice, Bedrock inference and vision, deterministic scoring and policy, persistence, actor events, vendor matching, UI, evaluation, AgentCore deployment | District area, authority, budget, vendors and rates, community feed, reporter identities, ten addresses and coordinates, 311 record | Generated demo images, with provenance | Municipal and contractor dispatch, contractual relationships, settlement, procurement |

Replays never masquerade as live inference. Public assets carry provenance and usage rights.

## 13. Open items

| Item | Position | Blocks |
|---|---|---|
| Vision spike | Run before/middle/after/unrelated/reused pairs three times each against real Bedrock output; any false automatic acceptance blocks unattended verification for that case | Automatic 100-point verification claim |
| App Runner and AgentCore specifics | Container build, service token, Runtime entrypoint, Observability wiring, Gateway OpenAPI target; decide during tier 3 and record the actual commands | Tier 3 |
| Tier-4 flags | Live 311, Amazon Location, plain-Sonnet evaluation arm; only after tier 3 | Nothing required |

Routine parameters are decided in the build documentation with evidence. No open item permits changing thresholds, scope, or labels silently.
