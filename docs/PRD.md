# Steward V1 product requirements

Status: build specification draft. Canonical scope is locked in [STEWARD.md](STEWARD.md); open interaction choices below await Cara. This document describes required behavior, not completed implementation.

## Product outcome

A neighborhood operator delegates routine supplemental maintenance within an explicit area, policy, budget, and approved-provider network. Steward investigates signals and owns the unresolved physical condition through verified completion. The operator spends attention on exceptions instead of moving every work order manually.

The weekend proof is one couch. Success means all sixteen criteria in [DEMO.md](DEMO.md) are reproducible, with three visible judgments: insufficient evidence → wait; official closure contradicted by fresh evidence → continue; inadequate cleanup → block settlement.

## Users and jobs to be done

| Actor | Job to be done | Success |
|---|---|---|
| District operator — primary user | Delegate authorized routine cleanup and handle genuine exceptions | Understand and decide the 90/95 exception without reconstructing the case |
| Approved-provider crew lead | Know what work is authorized and what proof will be accepted | Complete the $72 job and understand exactly why rework is required |
| Resident/reporter | Describe a physical problem without learning government categories | Submit plain language, location, optional photo, and receive an acknowledgment |
| District sponsor/buyer | Understand what happened to maintenance spending | Trace the simulated $72 from issue through authority, proof, and settlement |

Sponsor is a stakeholder, not a fourth application or new role-management feature. See [USER_MODELS.md](USER_MODELS.md).

## Functional requirements

| ID | Requirement | Acceptance evidence |
|---|---|---|
| PR-01 | Accept direct reports with text, reported location, and optional image; generate a signal ID and received_at server-side; preserve reported observation/capture time separately | Persisted signal; no forced category selection or automatic job creation |
| PR-02 | Ingest labeled simulated community signals and preserve source identity/provenance | Feed and resident observations remain distinguishable |
| PR-03 | Associate observations with a canonical physical issue; preserve repost provenance without awarding independent-source points | One couch issue with two independently supported sources |
| PR-04 | Calculate explainable evidence components and intentionally monitor weak evidence | 65/70 decision, no job or budget reservation |
| PR-05 | Reconcile a matched completed service record against newer physical evidence | Official state, timestamps, source mode, and dispute event visible together |
| PR-06 | Check category, district authority, provider eligibility, price, and budget before dispatch | $72 quote and successful gate; prohibited work produces no job |
| PR-07 | Let the selected provider accept, check in, and submit proof for that job | Job lifecycle and proof linked to assigned provider |
| PR-08 | Verify scene, reuse, GPS, timestamp, target removal, hazards, and area clearance | Actual structured findings; 90-point partial result cannot settle |
| PR-09 | Persist a failed-payment exception and resume on an operator decision | One pending exception; rework decision starts a new invocation |
| PR-10 | Reinspect fresh rework proof and settle only if permitted | 100-point complete result; exactly one simulated payment |
| PR-11 | Resolve only after accepted proof and permitted workflow completion | Issue resolved, board green, counts/budget consistent |
| PR-12 | Make every decision inspectable without private chain-of-thought | Evidence references, score components, concise explanation, tool and policy results |
| PR-13 | Make the demonstration resettable and honest | Fresh run reproduces acceptance; fixtures/replays/simulated effects labeled |

Canonical scoring and state definitions stay in [ARCHITECTURE.md](ARCHITECTURE.md), avoiding competing copies here.

## Surface behavior

**Operations Board.** Default view is the demo district and its outstanding conditions. Display watching, active, needs review, resolved, map, and budget. Counts must be derived from persisted state. Pending operator decisions drive the attention count; they are not an additional issue status. Review is an overlapping attention count, so it must not be summed with lifecycle counts as a total. Show available budget after reservations; label a reservation separately from simulated payment in the issue detail. Separate spent/committed dashboard cards are not required. Selecting a marker or issue opens its detail. A waiting agent is not an error.

**Issue Detail.** Show physical condition, location, current status, source evidence, official-record facts, resolution plan, job, and an ordered timeline. Separate evidence points from verification points. At the service contradiction, show the record's completion time alongside the evidence's observation/capture time and provenance. A later upload time alone does not establish that the condition persisted after official completion. At failed cleanup, place before/after evidence next to unmet requirements. Show the next responsible actor and next expected event.

**Operator Inbox.** Each item identifies the issue/job, reason attention is needed, latest proof, failed requirements, and permitted actions. Request completion records the unmet requirement as its reason and shows it to the crew; an additional operator note is optional. Manual inspection keeps the issue open and settlement blocked; V1 does not require a separate inspection application. A processed or stale decision cannot be submitted twice.

**Crew Form.** Display assigned job, $72 quote, address, couch and visible-bag removal scope, equipment expectations, and required proof before acceptance. Show check-in result and upload/processing feedback. Submission acknowledgment means proof received, not verified or paid. After rework, show the failed area-clear requirement and permit fresh proof.

**Resident report.** Plain language and location are the primary inputs; photo is optional. Missing/ambiguous location should produce an actionable validation message or review state, not an invented geocode. Return a receipt only after persistence. Post-submission visibility awaits Cara's choice.

## Failure and boundary requirements

- A lookup failure never implies no issue exists. Show live/fixture/unavailable status.
- A model timeout or malformed finding leaves the condition unresolved and does not release funds.
- Repeated form submissions and retried events cannot create duplicate dispatches, decisions, or payments.
- Disallowed transitions return a readable reason and preserve existing state.
- Unknown authority, ambiguous proof, scene mismatch, or reuse requires review without automatic settlement.
- Seeded locations and GPS inputs must not be described as verified real-world attestation.
- Text, images, and external records are evidence, never instructions granting authority to tools.

## Quality and measurement

The critical workflow must survive an agent/API restart between partial proof and the operator decision. The UI must visibly distinguish received, processing, awaiting actor, failed, and completed outcomes using persisted events. Crew interactions must fit a phone-width screen. Use text labels alongside map/status colors.

Release proof: sixteen-step run, relevant negative cases, clean install, and actual internal evaluation counts. No invented speed, confidence, or reliability targets. Provider performance/budget figures are seeded until real observations exist.

## Open choices

| Decision | Proposed default | Status |
|---|---|---|
| V1 user access | Labeled demo role switcher, no account onboarding | Asked Cara |
| Operator payment override | Omit override; request completion/manual inspection | Asked Cara |
| Resident follow-up | Receipt required; status page was proposed but is not required | Asked Cara |

Unanswered proposals are not approved requirements. Sign-in, resident status pages, and payment overrides must not hold up the terminal/API couch build. All other canonical scope exclusions remain unchanged. These interaction choices do not authorize a marketplace, full community verification, or production identity system.
