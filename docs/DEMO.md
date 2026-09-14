# Couch acceptance and demo runbook

Status: **API gate passed September 14, 2026** — criteria 1–15 in run 16 and all sixteen in the independently reseeded compare run 20 (`.steward/b13/run16-acceptance.json`, `.steward/b13/run20-acceptance.json`); the UI gate (P7) is not passed. An acceptance run must retain an event trace, resulting state, and actual model/tool outputs. Deterministic unit tests or prerecorded events alone do not prove a live Strands run.

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

## Live acceptance procedure (B13 API gate)

One command seeds an isolated store, starts the API with the runtime dispatcher on a private port, drives `python -m agent.demo` and stops that server; nothing touches the default `.steward/steward.sqlite3`:

```bash
uv run --no-sync python -m agent.bedrock_check            # same credential path as the server
bash scripts/acceptance_run.sh run-a 8001                 # first run: criteria 1-15, 16 pending
bash scripts/acceptance_run.sh run-b 8001 .steward/b13/run-a-acceptance.json   # independent reseed, closes 16
```

Run one Bedrock workload at a time: the runtime disables SDK retries for honest attempt accounting, so a `ThrottlingException` caused by a concurrent vision spike or second acceptance run ends that invocation as `AGENT_EXECUTION_FAILED` (observed in run 15). Each run keeps `.steward/b13/<tag>-acceptance.json` (per-step API responses, every invocation's model/tool observations, usage and versions), `<tag>-server.log`, `<tag>-demo.log`, `<tag>-seed.log` and `<tag>.sqlite3`. Fixture: seed `south-loop-demo-b3`, image manifest `86b7f711a397c8404b3fa11e7a9ba47d3a3972f46e27b02d22746b8df4d59bed`, policy `south-loop-v3`. Models: `global.anthropic.claude-sonnet-4-6` for text and vision in `us-west-2` (credentials refresh in the profile's own region, see README). Versions: prompt `steward-investigator-v2`, tools `steward-http-tools-v2`, intake prompt `d7593b85983eb362`, intake schema `a547a431f79dbddf`, completion vision prompt `cea02b88fbad2ce3`, completion findings schema `6d1d3b188972ac46`.

The intake photo contract now defines `visible_hazards` as specialist safety hazards and `unknowns` as scope-blocking gaps only; the couch fixture inspects to no hazards and no unknowns, and the supplemental `mixed-hazard.jpg` still reports the loose cable as a hazard (`.steward/b13/intake-negative-mixed-hazard.json`). The completion contract likewise defines `no_new_hazard` as a hazard introduced by the work, so leftover bags reduce `area_clear` (score 90) without also failing the hazard check; see the vision spike report (docs/evaluations/2026-09-13-vision-spike.md) for the requalification.

## Run artifacts still to fill

- Setup used on September 14 (Windows, worktree `codex/steward-build`): `uv run --no-sync python -m agent.seed --db .steward/ui.sqlite3`; API `STEWARD_STORE_PATH=.steward/ui.sqlite3 STEWARD_DEVELOPMENT_ORIGINS=http://localhost:5173 STEWARD_RUNTIME_ENABLED=true uv run --no-sync uvicorn agent.server:app --port 8000 --host 127.0.0.1`; driver `uv run --no-sync python -m agent.demo --base-url http://localhost:8000 --out .steward/ui-run.json --wait-seconds 240`; UI `cd frontend && npm install && npm run build`, then open `http://localhost:8000/`.
- Model `global.anthropic.claude-sonnet-4-6` for text and vision, region from `.env`; policy version `south-loop-v3`; fixture scenario `baseline`; seed version `south-loop-demo-b3`.
- Event trace and run artifact: `.steward/ui-run.json` (run 14:06 to 14:08 CDT, criteria 1 to 15 passed) and `.steward/walk4-run.json` (second seeded run at 14:42 CDT with `--compare`, all sixteen passed).
- UI walk with screenshots and pass/fail per criterion: `docs/evaluations/2026-09-14-ui-walk.md`.
- Clean-install result: not yet recorded. Public video URL and judging URL: not yet recorded.
