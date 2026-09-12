# User models and permissions

Status: behavioral models inferred from the canonical plan, not customer research. Do not invent names, demographics, interview quotes, or validated demand. Role access and resident visibility await Cara's choices in [PRD.md](PRD.md).

## District operator

**Context:** responsible for supplemental maintenance within a bounded district, working with a budget and existing contractors. Primary need is confidence in delegated outcomes and focused exception handling.

**Questions:** What needs me now? Why did Steward act or wait? Is this ours to handle? What is the evidence? What happens if I request completion?

**Journey:** open Board → see one exception → inspect evidence and unmet requirement → request completion → leave Steward to resume → see final verified resolution.

**Minimum information:** issue/location, current condition, official contradiction, authority, contract amount, vendor, before/after proof, structured findings, policy failure, and action consequence.

**Trust failure:** being asked to approve every normal step; silently paid incomplete work; a completed ticket portrayed as a verified clean sidewalk.

## Approved-provider crew lead

**Context:** completing an already contracted cleanup with appropriate crew/equipment. The V1 crew lead represents the selected vendor; there is no recruiting, bidding, onboarding, or payroll workflow.

**Questions:** Where do I go? What exactly is included? What proof do I need? Why was completion rejected? What must I fix?

**Journey:** open assigned job → accept → check in → capture before proof → upload after proof → see submitted/under review → receive rework requirement → upload fresh completion proof → see verified and simulated settlement.

**Minimum information:** assignment, address/map, contract amount, removal scope, required proof, lifecycle status, and concrete rework instruction.

**Trust failure:** vague “AI rejected” messaging or changing acceptance requirements after work. Area clearance is part of the original plan, not a surprise after the couch is removed.

## Resident / signal author

**Context:** sees a physical condition and has limited patience for administrative forms. Submitting a signal does not confer spending authority and does not guarantee a dispatch.

**Questions:** Did my report arrive? Is someone investigating? Has the physical issue been resolved?

**Journey:** describe condition/location and optionally add photo → receive receipt → follow status if that option is chosen.

**Minimum information:** clear input feedback, receipt/reference, and honest status. Do not expose another reporter's raw identity, internal decision privileges, or unrestricted operations controls through a resident page.

**Trust failure:** repeated forms, no acknowledgment, or “resolved” when the couch is still present. Full resident dispute/verification is outside required V1 scope.

## District sponsor / buyer

**Context:** funds the supplemental-service layer and is accountable for authority and spending. Uses the operator's existing views in V1.

**Questions:** What was authorized? What did it cost? What proof supports completion? How much budget is committed versus spent?

No separate sponsor login, reporting suite, procurement workflow, or budget-editing UI is required.

## Permission contract

| Capability | Resident | Assigned crew | Operator | Steward service |
|---|---|---|---|---|
| Submit a resident signal | Yes | Through the same reporting input | Through the same input if needed | Ingest authorized sources |
| See receipt/status | Submission receipt; follow-up visibility pending | Own assignment | District issues | Required context |
| Inspect full internal timeline | No by default | Job-relevant facts | Yes | Yes |
| Accept/check in/submit proof | No | Assigned job only | No | Validate and process |
| Request completion/manual review | No | No | Pending exception only | Create/escalate exception |
| Choose and dispatch provider | No | No | Not a required manual V1 action | Policy-gated |
| Verify proof | No | No | Request manual inspection; no implemented override assumed | Model findings plus deterministic checks |
| Authorize simulated settlement | No | No | Exception override undecided | Policy-gated |
| Resolve issue | No | No | No manual closure required | Policy-gated on accepted completion |
| Change policy/rates/budget | No | No | No configuration UI in V1 | No model-controlled changes |

Switching demo personas, if chosen, changes the acting role; it does not grant crew permissions to the operator role. A payment exception, if later enabled, does not by itself prove physical resolution. The developer seeds configuration outside the product flow. A role label is not a production authentication mechanism. If demo role switching is chosen, all personas represent sandbox actors and the interface must say so; public visitors must not be represented as authenticated district staff.

## Minimal actor representation

Use `actor_id`, `actor_type` (`resident`, `crew`, `operator`, `service`), display label, and optional `vendor_id`/`district_id` in the demo context and audit records. This is a proposed contract, not a requirement for a new accounts database.

Server handlers bind crew/operator events to an actor context. The model cannot create operator decisions, forge a check-in, or claim a resident identity. If real sign-in is chosen, bind actor context to the authenticated session; never trust a browser-supplied role as authorization.

For seeded corroboration, use stable source-author IDs and preserve repost lineage. A signal ID identifies a record, not an independent witness; two channels may carry the same author or copied observation. Unknown or anonymous identity does not establish independence merely because a second HTTP request arrived. Demo source identities demonstrate the rule; they do not solve real-world identity fraud.
