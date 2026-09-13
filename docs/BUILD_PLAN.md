# Build plan

Deadline: **Monday, September 14, 2026, 5 PM Pacific / 7 PM Chicago**. Use the absolute deadline; the original roughly 68-hour estimate is not a rolling allowance. Internal submission target: **Monday 3 PM Pacific / 5 PM Chicago**, leaving two hours of buffer.

The hackathon scope is one couch, defined in [PRD.md](PRD.md); the larger platform stays in VISION.md. The foundation slice is complete (checkpoint below). Work proceeds in the tiers below; no frontend before the core proof passes through the API. Completion evidence is recorded here rather than inferred from planned tasks.

## Build order — September 13

Each tier starts only after the previous tier passes. Nothing is cut; lower tiers slip if time runs out.

1. **Core proof.** AWS credentials and `.env` configured; Bedrock Sonnet round trip through Strands; scoring change for the service-record and persistence rules (test-first); five synthetic demo images and the vision spike; plans/providers/jobs, transactional dispatch/reservation, crew proof, operator resume, simulated settlement; HTTP tools against the local API; all sixteen [DEMO.md](DEMO.md) steps through the API with real Bedrock.
2. **Presentation.** React/Vite surfaces (Board, Issue Detail, Inbox, Crew Form, resident intake, persona switcher) served as static files by FastAPI; the twenty-two [evaluation](EVALUATION.md) scenarios through Steward with published counts; README, architecture diagram, video.
3. **AgentCore and hosting.** Agent on AgentCore Runtime with Observability; FastAPI + static frontend + SQLite container on App Runner with a public judging URL; then Gateway. Gateway is the first item to slip.
4. **If time remains.** Live 311 lookup behind a flag, Amazon Location geocoding behind a flag, plain-Sonnet evaluation arm.

## Verified foundation checkpoint — September 12

- [x] Validated observation records with separate UTC observation/receipt timestamps and explicit provenance.
- [x] Explainable evidence scoring and conservative duplicate/source-lineage checks. (The September 12 behavior of crediting any service match immediately is superseded by the September 13 service-record rule in PRD.md; that scoring change is the first tier-1 coding task.)
- [x] SQLite signals/issues/source links/events, atomic state/audit writes, retry conflicts, concurrent duplicate handling, and restart persistence.
- [x] Offline fixture command: `.steward/foundation-20260912.sqlite3` contains two seeded signals, four actual events, and score 85 after first recording 65 and reopening the connection. The artifact is local/ignored.
- [x] `uv run --no-sync pytest -q`: **32 passed**. `uv run --no-sync ruff check .`: **All checks passed**.

This checkpoint used the existing local Python 3.13 environment. It is not a clean install, AWS readiness check, evaluation run, or completed couch demo. No remote checkout, provider configuration, push, or deployment was changed.

## Tier 1a — Bedrock access, fixtures, vision spike

- [ ] Configure AWS credentials and `.env`; confirm Bedrock Sonnet inference and a real Strands tool round trip; record model ID/region and result.
- [ ] Implement the service-record and persistence scoring rules test-first; update the foundation harness and fixture record to carry status and completion time.
- [ ] Extend existing package with models, SQLite schema, data fixtures, deterministic policy and scoring.
- [ ] Seed district boundary/budget, three vendors/rates, ten demo addresses, two independent couch signals, and a completed-service fixture with honest provenance.
- [ ] Obtain usable `before.jpg`, `middle.jpg`, `after.jpg`, `unrelated.jpg`, `reused.jpg`; retain asset rights/provenance.
- [ ] Run the vision spike before building around its output; record findings in `docs/VISION_SPIKE.md` when run.

Vision spike protocol: compare before→middle (target removed, debris remains), before→after (target removed, clear), before→unrelated (scene mismatch), and before→reused (reuse rejected by hash). Include GPS distance, timestamp order, pHash, model ID, prompt, raw structured outputs, and observed failures. Repeat each pairing three times as a small stability check, not a benchmark. Any false automatic acceptance blocks unattended verification for that case. Freeze fixtures only after review.

Fallback decision tonight: ambiguous or unreliable findings trigger manual inspection. Preserve real model outputs and show the limitation. A manual-only result does not satisfy the automatic 100-point demo criterion; mark that gap honestly and use the remaining time to repair it. Vision uncertainty does not authorize fake success or a new product thesis.

## Tier 1b — ugly couch works

- [ ] Implement perception/state tools as HTTP clients of the API and agent-driven decisions.
- [ ] Implement policy-gated provider dispatch, budget reservation, and simulated settlement.
- [ ] Persist event/resume through crew proof and operator rework.
- [ ] Pass every step in `DEMO.md` using terminal/API output.
- [ ] Verify duplicate requests cannot dispatch/pay twice and prohibited work cannot dispatch.

**Gate:** all sixteen steps reproducible through the API before tier 2 starts. If this slips, tiers 2 and 3 slip with it; nothing is cut. Reduce presentation complexity before removing required behavior.

## Tier 2a — make decisions visible

- [ ] React/Vite app in `frontend/`, built to static files served by FastAPI; persona switcher labeled sandbox.
- [ ] Operations Board with Leaflet map and budget.
- [ ] Issue Detail with source evidence, score components, policy decisions, and tool events; highest polish priority.
- [ ] Operator Inbox (Request completion only), minimal Crew Form, resident intake form.
- [ ] Run the same acceptance flow through the UI.

## Tier 2b — evidence and submission artifacts

- [ ] Run the small internal evaluation in `EVALUATION.md`; publish counts and failures.
- [ ] Update README to actual setup/run/reset commands and observed behavior.
- [ ] Export implementation-accurate architecture diagram.
- [ ] Audit public source/assets/provenance and finish MIT copyright attribution.
- [ ] Complete submission description, judging access instructions, and recording script.

## Tier 3 — AgentCore and hosting

After tier 2 is stable: deploy the agent to AgentCore Runtime with Observability, ship the FastAPI + static frontend + SQLite container to App Runner, publish the judging URL, then add the Gateway OpenAPI target. Gateway is the first item to slip. Record the actual commands and results here. Optional blog content stays behind the stable submission gate.

## Monday — freeze, reproduce, record, submit

- [ ] Morning feature freeze; fixes only.
- [ ] Clean install from scratch with documented credentials/configuration; run acceptance and negative cases.
- [ ] Record public demo under five minutes, take screenshots, finish Devpost.
- [ ] Submit by internal target; verify public links and saved submission before the hard deadline.
- [ ] No new feature coding Monday afternoon.

## Decision log

| Date | Decision | Reason |
|---|---|---|
| Sep 11 | Scope locked to one couch | Prove one complete resolution before adding product |
| Sep 11 | Preserve Python package; default SQLite | Existing starter supports a small reliable implementation |
| Sep 11 | Same-scene/reuse prerequisites separate from score | A high arithmetic score cannot validate unrelated or recycled evidence |
| Sep 11 | Service match may raise 85 to 100 | Keep score arithmetic consistent while disputing official resolution |
| Sep 12 | Public OSS proof and private platform boundary reaffirmed | The hackathon repository ships everything its submitted behavior needs; commercial layers stay in VISION.md |
| Sep 12 | Foundation command directly supplies fixture facts and keeps CANDIDATE | Exercise real storage/scoring without inventing a model-selected match or monitoring decision |
| Sep 12 | Provisional precise-geocode threshold 30m | Explicit demo parameter; real geocode/authority and fixture spike remain open |
| Sep 13 | PRD v3 is the single scope authority; the separate scope, actor, and agent-behavior docs are folded in; working notes leave the public repo | One buildable spec |
| Sep 13 | Service-record rule: OPEN credits 15 now, COMPLETED credits 0 until two newer observations confirm the dispute; lookup runs on every signal | Preserves the 65 wait honestly and lets an open city record rescue a lone reporter |
| Sep 13 | Persistence bonus of 10, once, for a same-reporter fresh observation at least 24 hours later | A single persistent reporter can reach 75 |
| Sep 13 | Four-tier build order; nothing cut, lower tiers slip | AgentCore stays in scope without cutting required behavior |
| Sep 13 | React/Vite frontend served as static files by FastAPI; App Runner hosting; AgentCore Runtime + Observability + Gateway; agent tools are HTTP clients of the API | One container, one policy authority, one tool implementation |
| Sep 13 | Demo persona switcher (sandbox), single Inbox action (Request completion), five synthetic labeled images | Smallest honest surfaces for the sixteen steps |

Append evidence-backed implementation decisions here. Do not use this log to reopen company ideation.
