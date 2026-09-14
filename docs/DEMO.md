# Couch acceptance and demo runbook

Status, September 14, 2026: **API gate (B13) passed** — criteria 1–15 in run 16 and all sixteen in the independently reseeded compare run 20 (`.steward/b13/run16-acceptance.json`, `.steward/b13/run20-acceptance.json`). **UI gate (P7) passed** — the same journey was driven live at 14:06–14:08 CDT and again at 14:42–14:45 CDT with `--compare`, and every criterion was read back on the served screens; see [the UI walk](evaluations/2026-09-14-ui-walk.md) and its screenshots under `evaluations/ui/`. The twenty-two-scenario evaluation (P8) has **not** run. Hosting is **not** built. An acceptance run must retain an event trace, resulting state, and actual model/tool outputs; deterministic unit tests or prerecorded events alone do not prove a live Strands run.

Foundation checkpoint, September 13: `uv run python -m agent.foundation --db .steward/foundation.sqlite3` verifies 65/65/85/100 scoring with a database reopen and six actual events. It is a component harness, **not** the acceptance demo, and closes no criterion below.

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

These cases are covered by the offline suite (`uv run --no-sync pytest -q`, 703 passed on the B13 code) and by the driver's live denial at criterion 10. The scenario evaluation that exercises them through the live agent (P8) has not run.

## Recording script — maximum 5 minutes

**What the video is.** A recording of one driven live run plus a walk of the screens that read its saved state. The agent calls are real Amazon Bedrock calls (Sonnet text and vision, `us-west-2`); the district, providers, addresses, reporter identities, community feed and the 311 record are seeded fixtures; the photos are synthetic images generated for this project; dispatch and settlement are simulated. The resident, crew and operator actions in the run are submitted by the acceptance driver (`python -m agent.demo`) through the same HTTP API the screens use, so the screens show persisted records, not a scripted transcript. Say all of that in the first minute and keep an on-screen label through the run. Do not narrate the run as happening in real time if you cut it; say "recorded run, cut for time".

**Before recording (about 15 minutes, off camera).**

1. `aws login --profile <your profile>` (or otherwise refresh credentials), then `uv run --no-sync python -m agent.bedrock_check` must pass. Run nothing else against Bedrock during the recording; a concurrent workload can throttle the run and end an invocation.
2. `cd frontend && npm install && npm run build && cd ..` so the API serves the screens at `http://localhost:8000/`.
3. Fresh store: `uv run --no-sync python -m agent.seed --db .steward/video.sqlite3 --reset`.
4. Start the API in a visible terminal: `STEWARD_STORE_PATH=.steward/video.sqlite3 STEWARD_RUNTIME_ENABLED=true uv run --no-sync uvicorn agent.server:app --port 8000 --host 127.0.0.1`. The startup scan runs the seeded signal's pending invocation at once (one real Bedrock invocation, under a minute): the issue becomes MONITORING at 65 with the wait reasons saved. Wait for it before recording; Issue Detail shows the MONITOR decision when it is done.
5. Open a second terminal for the driver and a browser at `http://localhost:8000/`, light theme, 1280 px wide, persona **Operator**. Have `docs/evaluations/ui/` and `architecture.png` open as fallbacks if a screen misbehaves; label any still image as "screenshot from the September 14 walk".
6. Do a silent dry run of the whole thing first (seed, API, driver). If it fails, fix the cause and reseed; never record a replay of an earlier run and call it live.

**Take A — the wait state and the run (record continuously, then cut).** Scenes 1, 3 and 4. The driver command is `uv run --no-sync python -m agent.demo --base-url http://localhost:8000 --out .steward/video-run.json --wait-seconds 240`; it verifies the saved wait state, submits the second report, and drives the rest in about three minutes, printing one line per criterion. Keep recording; the cut uses only a few of those lines.

**Take B — the screens (record after the driver prints `criterion-15`).** Same browser, same store. Scenes 5–9 read the saved state of that run; scene 2 and 10–11 can be recorded at any time.

| Time | Scene and screen | Click / show | Say (short) | Proves | Truth label on screen |
|---|---|---|---|---|---|
| 0:00–0:25 | 1. Title card, then the Board after the API start (Take A) | Board `/` as Operator: the couch issue under Watching, "No decisions waiting", $500.00 available | A district gets scattered reports, a closed city record that may be wrong, and crews whose photos may show half a job. Steward turns that into one verified physical resolution and brings a person only the decision that needs one. | — | "Seeded district, fixtures, simulated money" (the footer says it too) |
| 0:25–0:50 | 2. `architecture.png` | Point at the three boxes | One Strands agent on Bedrock chooses what to do next through typed HTTP tools. FastAPI owns policy, scores, prices, budget, verification and settlement; the agent never opens the database. A trusted Bedrock vision call inspects each photo and returns findings that code scores. The hosted boxes are planned, not built; today runs locally. | design | "Hosted targets: planned, not built" |
| 0:50–1:20 | 3. Issue Detail `/issues/demo-couch` before the driver runs (Take A) | Evidence points 65 of 70 needed; the official record COMPLETED with lookup `seeded_adapter`, conflict pending; the latest decision MONITOR with its wait and unlock conditions; no plan, no job | The first photo and a precise location score 65 of the 70 needed. The 311 lookup returns a **completed** city record; a completed record earns nothing. Steward records the conflict and waits, saying what would unlock action. No job, no money. This invocation already ran against Bedrock when the API started. | 1, 2 | "65/70 — WAITING"; "311 record: seeded fixture" |
| 1:20–1:40 | 4. Terminal (Take A) | Start the driver; show the `criterion-1` and `criterion-2` lines, then leave it running | This is a live run: real Bedrock calls, synthetic photos, seeded fixtures, simulated dispatch and settlement. The driver submits the resident, crew and operator actions through the same API the screens use; nothing edits the database by hand. | run is live | "Live run — recorded September 14, cut for time" |
| 1:35–2:05 | 5. Issue Detail `/issues/demo-couch` | Scroll from the top: sources with provenance tags, evidence points table, the conflict block | A second resident reported the same couch through the form — that source is labeled live, the first is seeded. Two observations newer than the city's completion time confirm the dispute; the record is now credited and the score is 100. Completion time and observation times sit side by side; the issue stays open. | 3, 4, 5 | "seeded" / "live" provenance tags on screen |
| 2:05–2:30 | 6. Issue Detail, plan and job card; then Crew Form | Show quote $72.00, policy, responsibility district, "Simulated dispatch", reservation. Switch persona to the assigned **Crew**, open `/crew` → the job: Accepted, Checked in with timestamps | Policy permits supplemental bulky-waste cleanup here. The plan's quote is computed by code: $60 base plus $12 large object. The dispatch tool rechecked authority, eligibility and budget, created one job and reserved $72 once — labeled simulated. The crew accepted and checked in with a location. | 6, 7, 8 | "Simulated dispatch" badge |
| 2:30–3:00 | 7. Issue Detail proof history; Operator Inbox `/inbox` | Back to **Operator**. Middle proof: 90 of 95, "Failed: Area clear", Superseded. Inbox item: failed requirement, 90 of 95, before/after photos | The first completion photo shows the couch gone but bags left. Bedrock returned findings; code scored 90 against 95. The agent asked for settlement; the tool denied it, changed nothing, and the agent created one exception for a person. | 9, 10 | "Synthetic demo images"; "Settlement denied 90/95" |
| 3:00–3:25 | 8. Inbox item (handled) and Crew Form | Show the one action, **Request completion**, already recorded; Crew Form shows the rework instruction and the fresh after proof at 100 of 95 | The operator's only action is Request completion. It resumed the agent with a rework instruction on the same job, same $72, no second reservation. Fresh proof passed the scene and reuse prerequisites and scored 100. | 11, 12 | "Same job, same quote" |
| 3:25–3:50 | 9. Issue Detail payment and Record card; Board | One payment, $72.00 simulated, submission and verification ids; Resolved with time. Board: green marker, Resolved 1, "No decisions waiting", $428.00 available, $0.00 reserved, $72.00 spent | Exactly one simulated $72 settlement, then the issue resolves on accepted proof. The denied first attempt and the operator's decision stay in the timeline. | 13, 14, 15 | "SIMULATED SETTLEMENT" |
| 3:50–4:15 | 10. Terminal | The `--compare` summary from a second seeded run (`scripts/acceptance_run.sh` or the September 14 walk) | Reset and rerun reproduces the same judgments: resolved at 100, one 7,200-cent payment, one rejected 90-point proof, same budget. What is measured: two passing live acceptance runs today, a twelve-comparison vision check at 12/12, 703 offline tests. What is not: the twenty-two-scenario evaluation has not run, nothing is hosted, and no accuracy, savings or speed claim is made. | 16 | "Evaluation: not run" |
| 4:15–4:45 | 11. Close on the Board | — | Steward starts with approved providers in a small district and grows into the community's operating layer. Steward manages reality, not tickets. | — | — |

Target a final cut of about 4:45. Show evidence and concise decisions, not chain-of-thought. Never say "verified", "paid" or "resolved" before the screen shows it; never call the seeded 311 record a live lookup; never call the driver a resident or the persona switcher authentication.

**Fallbacks.** If a run ends with `AGENT_EXECUTION_FAILED` or `TOOL_REQUEST_FAILED`, stop, reseed with `--reset`, and record again; do not splice two runs. If the driver passes but a screen fails to render, show the walk screenshot for that criterion (`docs/evaluations/ui/`, file names in the walk table) and say so on screen. If the compare run is not available, say "criterion 16 was closed in the September 14 walk" and show `walk4-run.json`'s summary or the walk document.

## Live acceptance procedure (B13 API gate)

One command seeds an isolated store, starts the API with the runtime dispatcher on a private port, drives `python -m agent.demo` and stops that server; nothing touches the default `.steward/steward.sqlite3`:

```bash
uv run --no-sync python -m agent.bedrock_check            # same credential path as the server
bash scripts/acceptance_run.sh run-a 8001                 # first run: criteria 1-15, 16 pending
bash scripts/acceptance_run.sh run-b 8001 .steward/b13/run-a-acceptance.json   # independent reseed, closes 16
```

Run one Bedrock workload at a time: the runtime disables SDK retries for honest attempt accounting, so a `ThrottlingException` caused by a concurrent vision spike or second acceptance run ends that invocation as `AGENT_EXECUTION_FAILED` (observed in run 15). Each run keeps `.steward/b13/<tag>-acceptance.json` (per-step API responses, every invocation's model/tool observations, usage and versions), `<tag>-server.log`, `<tag>-demo.log`, `<tag>-seed.log` and `<tag>.sqlite3`. Fixture: seed `south-loop-demo-b3`, image manifest `86b7f711a397c8404b3fa11e7a9ba47d3a3972f46e27b02d22746b8df4d59bed`, policy `south-loop-v3`. Models: `global.anthropic.claude-sonnet-4-6` for text and vision in `us-west-2` (credentials refresh in the profile's own region, see README). Versions: prompt `steward-investigator-v2`, tools `steward-http-tools-v2`, intake prompt `d7593b85983eb362`, intake schema `a547a431f79dbddf`, completion vision prompt `cea02b88fbad2ce3`, completion findings schema `6d1d3b188972ac46`.

The intake photo contract now defines `visible_hazards` as specialist safety hazards and `unknowns` as scope-blocking gaps only; the couch fixture inspects to no hazards and no unknowns, and the supplemental `mixed-hazard.jpg` still reports the loose cable as a hazard (`.steward/b13/intake-negative-mixed-hazard.json`). The completion contract likewise defines `no_new_hazard` as a hazard introduced by the work, so leftover bags reduce `area_clear` (score 90) without also failing the hazard check; see the vision spike report (docs/evaluations/2026-09-13-vision-spike.md) for the requalification.

## Run artifacts

- Setup used on September 14 (Windows, worktree `codex/steward-build`): `uv run --no-sync python -m agent.seed --db .steward/ui.sqlite3`; API `STEWARD_STORE_PATH=.steward/ui.sqlite3 STEWARD_DEVELOPMENT_ORIGINS=http://localhost:5173 STEWARD_RUNTIME_ENABLED=true uv run --no-sync uvicorn agent.server:app --port 8000 --host 127.0.0.1`; driver `uv run --no-sync python -m agent.demo --base-url http://localhost:8000 --out .steward/ui-run.json --wait-seconds 240`; UI `cd frontend && npm install && npm run build`, then open `http://localhost:8000/`.
- Model `global.anthropic.claude-sonnet-4-6` for text and vision, region from `.env`; policy version `south-loop-v3`; fixture scenario `baseline`; seed version `south-loop-demo-b3`.
- Event trace and run artifact: `.steward/ui-run.json` (run 14:06 to 14:08 CDT, criteria 1 to 15 passed) and `.steward/walk4-run.json` (second seeded run at 14:42 CDT with `--compare`, all sixteen passed). Run artifacts are local (`.steward/` is not committed); the walk document records their results.
- UI walk with screenshots and pass/fail per criterion: `docs/evaluations/2026-09-14-ui-walk.md`.
- Clean-install result: pending R1 (in progress September 14). Public video URL and judging URL: not recorded; see [SUBMISSION.md](SUBMISSION.md).
