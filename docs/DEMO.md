# Couch acceptance and demo runbook

Status: specification; no steps verified yet. An acceptance run must retain an event trace, resulting state, and actual model/tool outputs. Deterministic unit tests or prerecorded events alone do not prove a live Strands run.

Foundation checkpoint, September 13: `uv run python -m agent.foundation --db .steward/foundation.sqlite3` verifies 65/65/85/100 scoring with a database reopen and six actual events. The first signal now references a real synthetic asset; links/geocode remain supplied fixture metadata. All five images and offline verification/spike code exist. Live Strands preflight and twelve vision inspections now pass (see [the vision spike report](evaluations/2026-09-13-vision-spike.md)). Real couch agent decisions and financial/crew/operator behavior remain open. This is **not** the acceptance demo and closes no criterion below.

## Sixteen acceptance criteria

| # | Input/action | Required observable outcome |
|---|---|---|
| 1 | Feed signal with image and precise seeded/live geocode | Signal persisted and linked to candidate couch issue |
| 2 | Steward investigates first signal | 65/70; 311 lookup returns a COMPLETED record with source mode and timestamps; conflict recorded, 0 credited; MONITORING with an explicit wait and unlock conditions; no dispatch |
| 3 | Independent resident report arrives | Same issue corroborated; 85 points |
| 4 | Dispute confirmed | Two observations newer than the official completion; official-status-disputed event; service record credited; 100 |
| 5 | Official closure and newer evidence shown together | Issue Detail shows completion time, observation times, and provenance side by side; issue remains unresolved |
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

- Unrelated scene, reused completion photo, invalid timestamp, distant GPS, unknown vision findings, and a target absent/uncertain in before evidence never auto-settle.
- Electrical/hazardous work never dispatches, including mixed couch-and-hazard observations; city-only responsibility routes externally.
- Duplicate sources do not create independent corroboration or duplicate issues/jobs.
- Insufficient budget, ineligible provider, and over-limit quote deny dispatch.
- Retried events/payments do not duplicate effects; stale operator decisions fail without mutation; new completion uploads wait for a pending operator decision; official Completed alone never closes an issue.
- Rework keeps the same quote/reservation; cancellation of an unpaid job releases its reservation once; payment followed by interrupted closure does not cause another payment on retry.
- An OPEN 311 record on a lone signal makes it actionable at 80; a COMPLETED record alone never adds points; the persistence bonus is credited at most once per issue.

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
