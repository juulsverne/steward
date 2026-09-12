# Couch acceptance and demo runbook

Status: specification; no steps verified yet. An acceptance run must retain an event trace, resulting state, and actual model/tool outputs. Deterministic unit tests or prerecorded events alone do not prove a live Strands run.

## Sixteen acceptance criteria

| # | Input/action | Required observable outcome |
|---|---|---|
| 1 | Feed signal with image and precise seeded/live geocode | Signal persisted and linked to candidate couch issue |
| 2 | Steward investigates first signal | MONITORING; 65/70; explicit decision to wait; no dispatch |
| 3 | Independent resident report arrives | Same issue corroborated; 85 points before service lookup |
| 4 | Steward looks up public service record | Matching COMPLETED record shown with source mode and timestamps |
| 5 | Newer physical evidence contradicts closure | Official status disputed event; issue remains unresolved |
| 6 | Steward determines authority and builds plan | Demo district/category/budget policy permits supplemental cleanup; $72 contract quote |
| 7 | Steward selects eligible approved provider | Job and budget reservation persisted once; simulated dispatch labeled |
| 8 | Vendor accepts and checks in | ASSIGNED then CHECKED_IN with recorded location and before evidence |
| 9 | Crew submits middle proof | Same scene, couch removed, no new hazard, debris remains; score 90 |
| 10 | Agent requests settlement | Tool denies 90/95; zero payment; operator exception persisted |
| 11 | Operator requests completion | Decision event persisted; new invocation resumes; REWORK_REQUIRED |
| 12 | Crew submits fresh after proof | Scene/reuse prerequisites pass; clear area; verification 100; VERIFIED |
| 13 | Steward requests settlement again | Exactly one simulated $72 payment; PAID |
| 14 | Steward closes the issue | RESOLVED with accepted proof and resolved_at |
| 15 | Board updates | Green map marker and correct resolved/attention/budget counts |
| 16 | Reset and rerun documented flow | Same required judgments visible, no hidden manual database edits |

A blocked payment attempt is deliberate evidence of policy enforcement. The denied tool must leave payment state unchanged and give the agent an actionable reason. The agent subsequently escalates to the operator.

## Negative cases required before recording

- Unrelated scene, reused photo, invalid timestamp, distant GPS, and unknown vision findings never auto-settle.
- Electrical/hazardous work never dispatches; city-only responsibility routes externally.
- Duplicate sources do not create independent corroboration or duplicate issues/jobs.
- Insufficient budget, ineligible provider, and over-limit quote deny dispatch.
- Retried events/payments do not duplicate effects; official Completed alone never closes an issue.

## Recording script — maximum 5 minutes

| Time | Show |
|---|---|
| 0:00–0:30 | Problem and buyer: neighborhood districts need verified resolution from scattered reports |
| 0:30–1:00 | One Strands agent, Bedrock, evidence tools, persisted state, deterministic policy |
| 1:00–3:45 | Couch: wait → corroborate → dispute official closure → authorized dispatch → partial proof → blocked payment → operator rework → full proof → simulated settlement → green map |
| 3:45–4:20 | Actual internal evaluation counts and limitations |
| 4:20–5:00 | Approved-provider starting point, future community operating layer; “Steward manages reality, not tickets.” |

Target a final cut around 4:45 to allow margin. Show evidence and concise decisions, not private chain-of-thought. Clearly label seeded service records, synthetic/demo assets, simulated feed, and SIMULATED SETTLEMENT. Do not narrate a replay as live inference.

## Run artifacts to fill after implementation

- Exact setup/reset/seed/start commands and fixture version.
- Model ID/region, policy version, event trace path, run date, pass/fail per step.
- A clean-install result and any known fallback behavior.
- Public video URL, screenshots, and accessible judging URL/test-build instructions.
