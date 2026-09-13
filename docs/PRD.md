# Steward — product requirements

**Autonomous neighborhood operations. Steward manages reality, not tickets.**

Status: expanded V1 build specification, September 12, 2026. Independently reviewed by Fable 5.1; findings and editorial decisions are recorded in [PRD_REVIEW.md](PRD_REVIEW.md). This describes the intended product, not implemented functionality or validated customer research. Cara's canonical September 11 plan governs scope. The release deadline is September 14 at 5 PM Pacific / 7 PM Chicago; execution gates remain in [BUILD_PLAN.md](BUILD_PLAN.md).

## 1. Product definition

Steward is an operating layer for physical community maintenance. A participating organization supplies a geographic area, an operating policy, a budget, approved providers, and explicit authority. Steward turns authorized signals into investigated physical issues, decides what can be done, coordinates permitted work, and checks whether the condition actually changed.

The operator's delegation is: “Handle routine work inside these rules, and bring me the decisions you cannot make.” The product must earn that delegation by making restraint, action, and exceptions understandable. Its unit of responsibility is an unresolved physical condition, not a message, service request, or contractor task.

The competition version proves this with a dumped couch in the South Loop Demo District. It uses real agent execution and verification against seeded district/provider data, with simulated dispatch and settlement. It does not establish real district authority or perform municipal work.

### Why this product should exist

The working hypothesis is that communities already produce useful reports, but resolving them requires coordination across disconnected systems. A resident sees a couch; a community channel discusses it; a government record claims completion; a district operator finds a contractor; the contractor submits a photo; someone still has to establish whether the sidewalk is clear.

The information and the responsibility can separate at each handoff. A report is not proof that work is authorized. An authorized work order is not proof of completion. A completed database record is not proof of physical resolution. Steward makes those distinctions explicit and carries the issue through the handoffs.

This is a product hypothesis from the founder's plan, not an assertion based on interviews, measured municipal performance, or validated demand. The first post-competition validation is to show an actual operator the workflow and ask what makes it impossible in practice.

### Buyer, initial deployment, and value

The initial buyer is a neighborhood organization with an existing supplemental-maintenance function: an SSA (Special Service Area), BID (Business Improvement District), campus, property district, or mixed-use development. The primary daily user is its operator. Existing approved businesses perform the work.

These organizations are a plausible starting point because the proposed delegation needs a bounded service area, spending authority, maintenance expectations, and contracted providers. Steward would complement baseline public services by coordinating supplemental work when the district is authorized to do so. No real city-versus-Steward speed or cost claim is made in V1.

| Stakeholder | Product value to demonstrate | Evidence in V1 |
|---|---|---|
| Operator | Routine coordination proceeds without approving every step | Authorized dispatch and final settlement occur without routine operator approval |
| Resident | A simple observation can contribute to resolution | Plain-language submission joins the canonical issue rather than requiring a government form |
| Crew | Scope and acceptance requirements are clear before work starts | Job includes couch/bag removal and proof requirements; rework identifies remaining debris |
| District sponsor | Spending is connected to authority and a verified outcome | The simulated $72 can be traced from plan and reservation to proof and payment |

### Before and after Steward

| Stage | Coordination problem hypothesized today | Steward's responsibility |
|---|---|---|
| Discovery | Reports arrive in multiple places | Preserve each signal and its provenance |
| Investigation | Duplicate reports and uncertain facts require interpretation | Link observations to the same physical issue when supported |
| Official lookup | Administrative state can be mistaken for physical truth | Compare the service record with current physical evidence |
| Authorization | Staff reconcile responsibility, contracts, and spending limits | Propose a plan and enforce configured authority deterministically |
| Execution | A provider's Done declaration can end the workflow too early | Keep the issue open while proof is evaluated |
| Exceptions | Staff must reconstruct context before deciding | Present the failed requirement, evidence, and permitted next action together |
| Completion | Payment and closure can lack a defensible evidence trail | Settle only when allowed and retain the resolution evidence |

## 2. Product principles

1. **Physical condition is the source of responsibility.** A couch remaining on the sidewalk keeps the issue alive even if a job or official record says completed.
2. **A signal is an observation, not an instruction to spend.** Incoming text cannot grant authority, set a price, or create a job automatically.
3. **Autonomy includes choosing to wait.** Insufficient evidence produces an explicit monitoring decision, not a fabricated answer or unnecessary dispatch.
4. **The model interprets; software authorizes.** Evidence scores, contract prices, eligibility, budgets, and settlement gates are deterministic.
5. **Human attention is reserved for exceptions.** Normal authorized progress should not require repeated approvals. Exceptions must come with enough context to decide.
6. **Verification requirements are stated before work.** Area clearance is part of the original job, not a surprise standard imposed after the couch is removed.
7. **Every claim has a source and a boundary.** Seeded authority, synthetic images, lookup fallbacks, simulated dispatch, and simulated settlement are labeled at the relevant point of use.

## 3. Product model

| Concept | Meaning | What it must not be confused with |
|---|---|---|
| Signal | An observation with source, content, reported place, and time/provenance | A job, spending approval, or independent witness merely because it has a new ID |
| Issue | Steward's canonical representation of a physical condition | A single post or government service request |
| Official record | An external system's account of a service request | Ground truth that the physical condition is gone |
| Evidence | Images, source facts, locations, times, and structured findings supporting a decision | A model confidence percentage |
| Resolution plan | Proposed service, authority, scope, provider requirements, fixed-rate quote, and verification requirements | Permission to execute before policy checks pass |
| Job | An authorized provider assignment for a particular issue and scope | The issue itself or proof that the issue is resolved |
| Operator exception | A pending decision outside current autonomous permission or adequate evidence | A routine approval step for every action |
| Settlement | The policy-authorized simulated transfer associated with a job | Independent evidence that the physical condition changed |
| Event | A durable observation, decision, action result, or human intervention | Hidden model reasoning or a scripted transcript |

Several signals can support one issue. The V1 couch has one active cleanup job; rework stays attached to that job, quote, and reservation. Distinct nearby conditions must not be merged merely because they share an address. Provider reassignment, split jobs, and multi-party contracts are not required for this release.

The seeded district configuration is a prerequisite, not an onboarding flow. It contains the demo service boundary, category rules, autonomous spending limit, verification threshold, budget, approved providers, rates, and equipment/availability facts. There is no policy editor or authority-granting chat command.

## 4. Users and responsibilities

The [user models](USER_MODELS.md) contain detailed journeys and permissions. Their implications for this product are:

- **Operator:** opens the Board to see what needs attention, enters Issue Detail to understand a decision, and uses the Inbox to handle the partial-cleanup exception. Needs evidence and consequences, not a chat session to reconstruct the case.
- **Crew lead:** opens a job scoped to the selected vendor, accepts it, checks in, and provides before/after proof. Needs explicit work scope, submission feedback, and a concrete rework instruction.
- **Resident:** reports the condition using plain language, location, and an optional image. Needs acknowledgment; full case management is not their responsibility.
- **Sponsor/buyer:** evaluates delegated operations and traceable spending using existing views. Does not receive another application, reporting suite, or V1 user-management role.

Choosing demo persona switching versus real sign-in remains open. Actor attribution is required either way. A demo role selector is not production authentication. Resident submission does not confer operator rights; a provider cannot authorize its own settlement; the agent cannot invent a human decision.

## 5. Release scope

### Required experience

One district, three seeded approved providers, one complete couch resolution, and exactly three input types:

1. A South Loop Neighbors feed labeled **Simulated opt-in community channel**.
2. A direct resident report entered through a real web form.
3. A Chicago 311/public service lookup, live where practical with a clearly labeled, sourced fixture/fallback.

The UI consists of the Operations Board, Issue Detail, Operator Inbox, and a minimal Crew Form. Resident intake can be a small form within this experience; it does not require a resident portal. Actual reasoning uses one Strands agent with Bedrock Sonnet. No extra model is needed for the diagram.

### Outside V1

No real payments, open labor marketplace, bidding, worker onboarding, insurance-verification service, procurement system, tax allocation engine, production fraud detection, full SSA integration, multi-city operation, advanced routing, preventive maintenance, learning engine, resolution-graph analytics, full community verification, Cedar, or multiple agents. No Flock, TikTok, Facebook, or X integration.

AgentCore is a deployment stretch after the required product is stable. Resident follow-up beyond a receipt and payment-exception overrides remain undecided, not release requirements. The company direction is retained in section 14 and [VISION.md](VISION.md); it does not expand the weekend backlog.

## 6. End-to-end product journey

### A. Observe and decide whether the condition is actionable

A resident's couch photo appears in the simulated feed near 1530 S Michigan Ave. Steward preserves the raw observation, source identity, reported place, and time provenance, then associates it with a candidate physical issue. Image evidence contributes 30 points, one independent source 20, and a precise geocode 15. At 65, the issue becomes MONITORING and no job or budget reservation exists.

Issue Detail explains the actual basis: “Image evidence, one independent source, and a precise location total 65 points. The actionable threshold is 70. Watching for corroboration.” Monitoring persists across invocations; V1 resumes when another event arrives and does not require perpetual polling.

A second independent resident report describes the same couch. Steward links it to the existing issue, preserving both source records. The second source raises evidence to 85 before any matching-service-record bonus. A copied post or a second message from the same author cannot manufacture independence. For the acceptance run, the two observations have explicit distinct seeded author IDs, original content, and provenance labels. The resident form submits as the selected seeded demo resident; that is not verified real-world identity. Distinct channels alone are neither necessary nor sufficient: two independent residents can use the same form. Unknown provenance is treated as unknown, not a verified new witness.

**Unresolved build constraint:** an immediately retrieved matching service record could instead raise the first signal from 65 to 80. The canonical demo's wait remains required, but restricting retrieval solely to force 65 is not an approved policy. Section 13 tracks this as a spike decision; the implementation must not conceal evidence or change arithmetic to fit the story.

### B. Reconcile official state and establish authority

Steward finds a matching service record whose status is COMPLETED. Newer physical evidence shows the couch still present. Issue Detail presents the official completion time, the observation/capture time, and their provenance together. Steward records an official-status dispute and keeps responsibility for the unresolved condition.

Received/upload time is separate from observation/capture time. A fresh upload of an old photo cannot establish that the couch remains after completion. If freshness or scene identity is uncertain, Steward preserves uncertainty and the open condition rather than claiming a proven contradiction or resolution.

A matching record contributes 15 evidence points, taking the corroborated example from 85 to 100. This supports the match/history; it does not verify resolution. Evidence sufficiency and dispatch authority remain separate questions.

For the couch, configured policy permits supplemental bulky-waste cleanup inside the demo district. City-only issues are routed externally; private or unknown responsibility is not a reason to dispatch a public provider. Safety-critical observations escalate without entering the marketplace path, regardless of the routine evidence threshold. A couch accompanied by exposed wiring or another prohibited hazard cannot be downgraded to ordinary bulky waste to pass dispatch policy; preserve the hazard observation and block autonomous cleanup pending review. V1 records routing recommendations or simulated handoffs, never fictitious contact with real services.

### C. Plan and authorize work

Steward builds a plan that the operator and selected crew can inspect:

| Plan field | Couch example |
|---|---|
| Condition | Couch and visible dumped bags obstructing the sidewalk |
| Location | 1530 S Michigan Ave, with coordinates/provenance |
| Authority | Seeded South Loop Demo District supplemental-cleanup policy |
| Service | Bulky waste cleanup |
| Equipment/crew | Truck and two crew members |
| Scope | Remove the couch and visible dumped bags; leave the defined work area clear |
| Contract quote | $60 base + $12 large object = $72 |
| Required evidence | GPS check-in, before image, fresh after image, scene match, target removed, no new hazard, area clear |

The plan identifies the relevant work area using the before image and description. “Area clear” concerns that agreed scope, not an unrelated condition elsewhere in the neighborhood. Ambiguous scope/evidence goes to review rather than changing the contract silently.

The agent chooses among eligible South Loop Services, Windy City Maintenance, and Lakefront Clean Team using configured equipment, availability, location, workload, and performance facts. The model cannot invent a provider, insurance verification, rate, or authority. The dispatch tool rechecks eligibility, category/location authority, quote, autonomous limit, and available budget before creating the assignment.

Successful dispatch creates one job and reserves $72 once. For an initial available budget B, dispatch leaves B − $72 available; settlement converts that reservation into spending and does not subtract another $72 from available funds. Rework retains the reservation. It is labeled simulated. The normal path does not require operator approval. A denied dispatch produces a reason and next responsible actor without creating a payable job.

### D. Execute and submit proof

The selected crew sees the job amount, location, full removal scope, and proof requirements before accepting. Before evidence must establish that the contracted target is present; clean before-and-after images do not establish that this crew removed anything. If the target is absent or its presence is unclear, keep the job unpaid and surface a condition-not-found or uncertain-before-evidence exception. This is an open operator investigation hold outside the sixteen-step path. Do not automatically request removal of an absent target or imply a cancellation action is shipped. A cancellation UI/actor workflow and arrival fees are outside required V1 scope; the ledger must still behave correctly if an unpaid job is cancelled through a supported implementation path. Acceptance and check-in are explicit crew events, not claims inferred from conversational text. The crew records before evidence and later submits an after image.

Submission first means **Proof received**. It does not mean Verified, Paid, or Resolved. The same distinction holds while image inspection is running or if the model fails. Fixture GPS/capture metadata are labeled demo inputs and do not claim production attestation.

### E. Reject incomplete completion and request human judgment

In the middle image, the couch is removed but debris remains. Bedrock returns structured findings; deterministic verification assigns 30 for nearby GPS, 10 for timestamp order, 40 for target removal, 10 for no new hazard, and zero for area clearance: 90 out of 100. The payment policy requires 95.

The required demonstration includes a settlement authorization request that the action tool denies. No payment occurs. Steward records the failure and creates one operator exception containing the scope, before/after images, findings, score components, and unmet area-clear requirement.

The operator chooses **Request completion**. That choice records an event and ends the pending decision. A new agent invocation loads the issue/job context and requests rework. The crew sees “Remove the remaining dumped bags/debris in the marked work area and submit fresh proof.” The same $72 job continues; there is no second dispatch charge or reservation.

Manual inspection is an alternative hold for ambiguous cases; it keeps the exception open, the issue unresolved, and settlement blocked, with the operator as the next actor. The existing Request completion action may resume the job when appropriate; V1 provides no manual Verified or Paid button and no autonomous inspection service. Completing a manual inspection workflow or overriding payment is not necessary for the couch proof and must not be implied by an unimplemented button.

### F. Verify, settle, and resolve

The crew submits a fresh complete after image. The same-scene/reuse prerequisites pass and the complete set of verification checks yields 100. Steward can authorize the simulated $72 payment exactly once and close the issue based on accepted completion evidence. The board marker becomes green and the review item is no longer pending.

The timeline retains the failed first submission and human rework decision. Success must not erase the evidence of restraint. A paid job whose closure step was interrupted is distinguishable from a closed issue; retrying closure must not pay again.

## 7. Experience requirements by surface

### Operations Board — where the operator starts

The Board answers “What needs me, what is Steward handling, and what has actually been resolved?” Its hierarchy is the district identity and demo label, attention count, lifecycle overview, available budget, then map/issues. Required metrics are watching, active, needs review, and resolved. Review is an overlapping count of pending exceptions, not another lifecycle bucket to sum into total issues.

Available budget reflects reservations as well as settled spending. Reservation and payment are distinguished in Issue Detail; separate financial-dashboard cards are not required. Selecting an issue or marker opens the same canonical Issue Detail.

Zero exceptions means **No decisions waiting**, not **Everything resolved**. MONITORING remains visibly open. An external route never produces a green resolved marker. A map-loading failure must leave issue navigation and status available through the issue list. Color always has an accompanying text label.

### Issue Detail — the product's primary evidence surface

A reader should be able to answer, without interrogating a chatbot:

- What physical condition does Steward believe exists, and where?
- Which observations support it, and are they live, seeded, or synthetic?
- Why did Steward wait, act, dispute the service record, or request a person?
- Who has authority, what is the job scope, and what does the contract charge?
- What proof is available, what failed, and what happens next?

Show the current condition/status first, then the latest decision and next actor/event. Source evidence, official-record comparison, plan/job, and ordered timeline must be accessible from that view. The partial-cleanup exception places before/after proof and unmet requirements together.

Each decision entry contains a concise explanation, supporting evidence references, relevant score components, policy outcome, and actual tool result. Scores are named **Evidence points** and **Verification points**; neither is a confidence percentage. Tool requests are distinguished from successful actions. Model prose alone cannot update the UI to Paid or Resolved.

### Operator Inbox — one informed decision

Each item is tied to an issue, job, and specific proof submission. It includes the failed requirement, latest evidence, score/threshold, and allowed next action. The canonical rework action records the unmet requirement automatically; an additional note is optional.

Submission feedback distinguishes decision saved from resumed processing. Once a decision is saved, repeated clicks cannot generate another intervention. If newer proof or another decision makes the displayed item stale, the server rejects the stale action and the UI refreshes the current case. Requesting completion updates the crew's job view; email/SMS notifications are not required.

An override button must be absent or disabled unless policy explicitly grants that action and its semantics have been decided. No human button may silently change visual findings to true. Even an eventual authorized payment exception would not independently prove physical resolution.

### Crew Form — a small phone-usable work surface

Show one assigned job's location, scope, amount, state, and required evidence. Controls become available in valid lifecycle order: accept, check in, attach proof, submit. Preserve usable form state when an upload fails and explain which required item is missing. Valid receipt of proof produces an acknowledgment while verification runs.

Display rework as an instruction attached to the same job with the failed requirement and supporting image. New proof is a new submission; it does not overwrite prior proof. For the required V1 lifecycle, accept new completion submissions after check-in or after an operator has requested rework. While a completion exception awaits a decision, show “Awaiting operator decision” and disable new completion submissions; server validation enforces the same rule. Retries of an already received submission return its existing result. This is a bounded demo workflow, not a claim about future provider flexibility. Handlers enforce consistency between the selected actor context and the assigned vendor, and cannot accept a browser field as authority to mark a job paid. Under demo persona switching, that context is self-declared: the check does not authenticate the person as a real employee of that vendor. Real identity assurance depends on the unresolved sign-in choice.

### Resident intake — a low-friction observation

Require a description and reported location; an image is optional. Do not require the resident to choose jurisdiction, service code, vendor, price, or urgency score. Issue a receipt/reference only after the signal is persisted. If live geocoding is unavailable and the address is outside the seeded set, preserve the signal with unresolved location, no precise-geocode points, and no dispatch; the fixture set is not a universal address service. Keep observation/capture provenance separate from receipt time without adding a long form; unknown times remain unknown.

Incomplete input gets actionable validation. A plausible but ambiguous location becomes an unresolved input/review case rather than invented coordinates. Resident status pages and ongoing notifications remain unapproved additions. No full operator timeline or other reporter's raw identity is exposed by default.

## 8. Autonomy and human boundaries

| Situation | Steward may do | Must not do |
|---|---|---|
| Routine evidence below threshold | Record monitoring and await a new event | Dispatch or reserve funds solely because someone complains |
| Supported actionable condition | Investigate records/responsibility and propose a plan | Treat evidence points as spending authority |
| Official completion conflicts with newer evidence | Record both and continue the unresolved issue | Close solely on the official field or invent contact with the city |
| Eligible plan inside configured permission | Select an eligible vendor and request dispatch | Invent a price, provider approval, budget, or policy |
| Incomplete or ambiguous proof | Request authorization, receive denial, and surface the appropriate exception | Release payment or mark resolution based on a Done claim |
| Operator requests completion | Resume from the saved event and direct rework | Forge the decision or dispatch/pay twice |
| Accepted complete proof | Request permitted settlement and evidence-backed closure | Treat an earlier pass as current after superseding failed proof |

The architecture owns the precise scoring and action-gate implementation. These are observable product boundaries. See [ARCHITECTURE.md](ARCHITECTURE.md) and [AGENT_CONTRACT.md](AGENT_CONTRACT.md).

## 9. Exceptions, reliability, and evidence limits

| Condition | User-visible behavior | Preserved invariant |
|---|---|---|
| Duplicate/reposted signal | Evidence linked with provenance; no independent-source bonus | Multiple records do not manufacture independent witnesses |
| Uncertain issue match | Keep observations distinguishable and record uncertainty | Nearby separate conditions do not silently merge |
| Missing/ambiguous geocode | Explain uncertainty or request review | No invented precise-location points or district authority |
| 311 lookup failure | Clearly label unavailable/live/fixture result | Failure is not evidence of completion or nonexistence |
| Old/unknown-time photo | Show time provenance and unresolved freshness | Upload time cannot prove a fresh physical contradiction |
| No eligible vendor or insufficient budget | Record dispatch denial and an operator exception | No job/reservation beyond authority; no V1 bidding flow |
| Target absent/uncertain in before proof | Hold the unpaid job and request review | Do not pay for a removal that the submitted evidence does not establish |
| Mixed cleanup and prohibited hazard | Preserve the hazard and escalate | A benign category cannot bypass the more restrictive observation |
| Job cancelled before settlement | Record cancellation and release its reservation once | Cancellation creates no payment; no new cancellation UI is required |
| Wrong scene, suspected reuse, or unknown vision finding | Mark proof unsuitable/uncertain and request review | A high score cannot bypass proof prerequisites |
| Model failure or malformed output | Keep evidence, expose a recoverable processing failure | No fabricated findings, payment, or resolution |
| Stale proof/decision or repeated request | Reject stale mutation or return the already-recorded result | Latest relevant evidence governs; effects occur once |
| Restart during human wait | Reload the persisted case and pending decision | Continuation does not depend on a live chat session |
| Payment succeeds but closure is interrupted | Show the paid job and unresolved finalization; retry closure | Settlement cannot repeat |
| Manual inspection chosen | Visible hold with operator as next actor | No false promise of an automated inspection workflow |

V1 verification evaluates provider-supplied proof and consistency checks. It is not an independent site inspection or a guarantee that a condition will never recur.

pHash is a reuse check, not proof of scene identity. Compare each new completion image with the before/reference evidence and prior stored images for that issue/job; suspicious matches require review. Referencing an existing baseline in a later inspection is not uploading new proof. Crops, near-identical scenes, manipulated metadata, and rephotographed content remain limitations to expose in the spike. Comparing a new submission with prior accepted input is different from retrying the same submission after a network failure: an idempotent retry is not a second piece of evidence. Fresh rework must be tied to the later work attempt, not merely a timestamp later than the original before image. V1 provenance is limited and must be stated honestly.

After resolution, new reports remain signals to investigate; do not silently merge them into a closed issue and discard them. V1 may preserve an ambiguous post-resolution report for operator review. Automatic reopening, recurrence linking, and another dispatch/payment cycle are outside the required proof.

An invocation has a bounded retry/tool budget. A denied action is not retried indefinitely without changed facts. Policy checks and their mutations use current stored state; two requests arriving together cannot both spend the same reservation or settle the same job. This is required for the simulated workflow, not a new distributed-systems platform.

## 10. Functional requirements and traceability

IDs are retained from the original PRD so implementation references remain stable. Narrative sections above define the experience; this table provides acceptance anchors.

| ID | Required behavior | Demo acceptance steps |
|---|---|---|
| PR-01 | Persist direct report, source provenance, server signal ID/receipt time, and separate observation/capture facts | 3, 16 |
| PR-02 | Ingest explicitly simulated community feed observations | 1 |
| PR-03 | Link corroborating observations without false independence or false merges | 1–3 |
| PR-04 | Compute explainable evidence components and persist an intentional watch decision | 2–3 |
| PR-05 | Compare matching official status with newer physical evidence and retain the unresolved issue | 4–5 |
| PR-06 | Build scoped contract plan, select eligible vendor, gate dispatch, and reserve once | 6–7 |
| PR-07 | Persist valid crew acceptance/check-in and job-linked proof | 8–9 |
| PR-08 | Inspect proof with structured findings, deterministic checks, and prerequisite gates | 9, 12 |
| PR-09 | Deny inadequate settlement, persist exception, and resume after real operator rework decision | 10–11 |
| PR-10 | Verify fresh completion and release one simulated settlement | 12–13 |
| PR-11 | Close on accepted completion and reflect the outcome/budget on the Board | 14–15 |
| PR-12 | Expose evidence, concise decisions, policy results, and actual tool actions throughout | 1–15 |
| PR-13 | Reset the demo dataset and reproduce the full workflow with truthful labels and no hidden database edits | 16 |

UI vocabulary is deliberate: Watching maps to MONITORING; Request completion records an operator decision that leads to REWORK_REQUIRED; Proof means a crew submission, while Evidence includes all supporting sources. An exception is pending human attention, not itself a physical-issue status transition. A payment exception leaves an issue RESOLUTION_ACTIVE; official-record disputes remain timeline facts. The alternate ESCALATED and DISPUTED states are scoped in ARCHITECTURE and are not substitutes for those two couch events. “Next expected event” names the next actor action, not a promised scheduler or notification.

The sixteen criteria in [DEMO.md](DEMO.md) remain the release contract. This PRD does not add a second competing checklist or declare any criterion complete.

## 11. Success measures and validation

**Product proof:** one condition passes all sixteen steps, including the three mandatory judgments: watch at 65; dispute official completion with supported fresh evidence; deny settlement at 90/95, then settle after rework at 100. A human participates in the required exception, not every ordinary transition.

**Reliability proof:** meaningful negative cases cover prohibited dispatch, insufficient budget, false source independence, wrong scene/reuse, invalid proof timing/location, stale decisions, and repeated settlement. A restart between partial proof and human response must preserve the case. The clean-install run must reproduce the documented flow without manual database repair.

**Fixture reproducibility:** the acceptance run uses an explicit labeled demo-data mode with a fixed completed-service record and dated evidence assets. Store a manifest identifying source mode, seeded author IDs, observation/capture times and their provenance, official completion time, image roles, and policy version. Fixtures may be chosen from the start in demo mode; do not claim a live lookup failed to justify them. A live-data run reports actual results and need not reproduce the scripted couch facts. This stabilizes data, not tool order or agent decisions.

**Agent proof:** retain a live Strands trace showing evidence-dependent tool choices and actual results. A seeded event replay or deterministic test alone does not prove live agent behavior. The policy must also reject a disallowed action when its tool is called directly.

**Evaluation:** use the twenty-case internal protocol in [EVALUATION.md](EVALUATION.md). Report routing accuracy, false merge rate, incorrect autonomous-action rate, and unnecessary escalation with counts and denominators. Compare proposals separately from executed effects; blocked unauthorized proposals are not successful executions. No reliability percentage or model win is promised before measurement.

**Experience walkthrough:** a tester should be able to identify why Steward waited, why it disputed closure, what the crew failed to finish, what the operator selected, and why payment eventually became permitted using the UI alone. A missing explanation is a product defect even if the backend states are correct.

Do not turn the seeded one-job outcome into a claim about customer savings, municipal speed, deployment readiness, or real-world verification accuracy.

## 12. Truth labels and release artifacts

| Type | What the submission may claim |
|---|---|
| Real, once implemented and verified | Strands loop, Bedrock inference/vision, tool choices, evidence scores, policy enforcement, persistence, UI inputs, actor events, vendor matching, internal evaluation |
| Seeded/demo | District area/authority/budget, approved vendors/rates/availability, community feed, sample identities, demo addresses and service-record fixtures |
| Synthetic, if used | Generated test images, with asset provenance and documented intended conditions |
| Simulated effect | Contractor/municipal dispatch, contractual relationships, settlement, procurement |
| Live when available | Geocoding and public service lookup, identified per result rather than by a blanket claim |

The public MIT repository must contain the source/assets and instructions needed for the submitted functionality, an accurate README, architecture diagram, and a reproducible demo. The public video is at most five minutes. Detailed release tasks and judging access remain in [SUBMISSION.md](SUBMISSION.md). AgentCore and optional content never precede a stable required submission.

## 13. Open decisions and technical gates

| Decision/gate | Current position | Blocks |
|---|---|---|
| First-signal 65 versus early matching-record bonus | Unresolved; inspect live tool behavior, preserve arithmetic and evidence access, record the chosen resolution | Mandatory watch demonstration |
| Vision distinguishes middle/after/unrelated/reused | Must be tested with actual Bedrock outputs; uncertain cases require review | Automatic verification claim and final pass demo |
| District boundary and geocode precision threshold | Seed and document explicitly; do not imply an actual SSA grant of authority | Deterministic location eligibility |
| Evidence/identity fixture manifest | Define source-author IDs and capture/observation provenance; do not count anonymous requests as known witnesses | Honest corroboration, contradiction, and verification demo |
| User access | Demo role switching proposed, real sign-in undecided | Final interactive/judging access design; not terminal/API build |
| Operator payment exception | Not enabled by default; requires explicit permission and defined closure semantics | Optional override path, not required rework |
| Resident follow-up | Receipt required; status page proposed but unapproved | Optional follow-up experience |

Unanswered choices are not approvals. Resolve routine implementation parameters in the build documentation; ask Cara only for product/authority choices that cannot be inferred. No unresolved choice permits silently changing thresholds, scope, or truth labels.

## 14. Product direction after the proof

The larger vision is the same delegation across more authorized signals, public systems, physical sensors, provider networks, and funding arrangements. A future resolution graph would connect conditions, interventions, cost, time, evidence, rework, and durable outcomes. These are potential commercial assets, not weekend modules.

The next step is workflow discovery with an actual neighborhood operator, followed by one design partner and one real resolved issue. Approved local contractors come first; workforce intermediaries and civic micro-work remain later possibilities. New commercial work can live in a private platform while the competition implementation remains open source.

Steward succeeds at this stage if a judge can watch one messy neighborhood problem become a defensible verified outcome—and can see precisely where the agent waited, acted, and stopped at its authority boundary.
