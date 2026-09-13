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

- [x] Confirm actual Strands/Sonnet tool round trip using the authenticated default profile: two model cycles, successful current_time result, final reply, 2.678 s. `.env` is optional; settings may come from environment/profile defaults. Artifact `.steward/bedrock-check-20260913T071054517582Z.json`.
- [x] Implement service-record and persistence scoring; update the harness and fixture completion time. September 13 rerun: 65/65/85/100, six events, persisted CANDIDATE issue.
- [x] Recover image utilities from Fable's image branch; add strict verification, bounded Strands check, and single-call Sonnet inspection/spike code. Offline tests are not live gate evidence.
- [x] Obtain usable `before.jpg`, `middle.jpg`, `after.jpg`, `unrelated.jpg`, `reused.jpg`; record synthetic provenance and exact prompts in `data/images/PROVENANCE.md`. Publication rights review remains in the submission checklist.
- [x] Run real Bedrock vision: 12/12 expected outcomes; zero errors/false accepts. See [VISION_SPIKE.md](VISION_SPIKE.md) for actual counts, nulls, usage and limitations.

September 13 checkpoint: Tier 1A closed with 91 offline tests, successful real Strands tool round trip, and twelve passing image inspections on `global.anthropic.claude-sonnet-4-6` / `us-west-2`. The initial expired-login failure is retained separately. After starting Tier 1B policy/fixtures, the full suite is **129 passed**, Ruff clean. See [VISION_SPIKE.md](VISION_SPIKE.md) for exact commands, fixture checks and open gates, and [DOCUMENT_REVIEW.md](DOCUMENT_REVIEW.md) for the document reconciliation.

Vision spike protocol: compare before→middle (target removed, debris remains), before→after (target removed, clear, checked against prior middle), before→unrelated (scene mismatch), and before→reused (reuse checked against prior completions). Include seeded GPS distance, timestamp order, dHash, model ID, prompt, raw structured outputs, usage and failures. Repeat each pairing three times. Every expected field, prerequisite result and payment eligibility must match, including exact 90/100 positive scores. Errors, false accepts, missed full-cleanup acceptance, or incomplete runs fail. Freeze fixtures only after review; no benchmark claim.

Fallback decision tonight: ambiguous or unreliable findings trigger manual inspection. Preserve real model outputs and show the limitation. A manual-only result does not satisfy the automatic 100-point demo criterion; mark that gap honestly and use the remaining time to repair it. Vision uncertainty does not authorize fake success or a new product thesis.

## Tier 1b — ugly couch works

- [ ] Extend the foundation with deterministic dispatch policy, plans, jobs, proof, ledger and actor-bound event API.
- [x] Seed district boundary, $500 demo budget, three vendors/rates, ten addresses and simulated feed; preserve the two signals/service record. These are fixtures, not persisted jobs or a ledger.
- [x] Implement pure policy loading/validation, routing, $72 couch quote, provider eligibility/ranking, geometry, and dispatch/settlement predicates. Tested directly, including malformed facts and denied actions; mutation-boundary integration remains open.
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

After tier 2 is stable: resolve the App Runner persistence conflict recorded in [ARCHITECTURE.md](ARCHITECTURE.md), then deploy the agent to AgentCore Runtime with Observability, host the API/frontend with a verified persistent state owner, publish the judging URL, and add the Gateway target. The target remains App Runner pending that resolution; no replacement is silently selected. Gateway is the first item to slip. Record actual commands/results. Optional blog content stays behind the stable submission gate.

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
