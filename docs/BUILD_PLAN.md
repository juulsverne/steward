# Build plan — locked September 11

Deadline: **Monday, September 14, 2026, 5 PM Pacific / 7 PM Chicago**. Use the absolute deadline; the original roughly 68-hour estimate is not a rolling allowance. Internal submission target: **Monday 3 PM Pacific / 5 PM Chicago**, leaving two hours of buffer.

Current status: generic Strands starter exists; Steward-specific functionality and live AWS access have not been verified in this documentation pass. All gates below remain open. No pretty frontend before the foundations and vision spike.

## Friday night — foundations and vision decision

- [ ] Confirm Bedrock Sonnet inference and a real Strands tool round trip; record model ID/region and result.
- [ ] Extend existing package with models, SQLite schema, data fixtures, deterministic policy and scoring.
- [ ] Seed district boundary/budget, three vendors/rates, ten demo addresses, two independent couch signals, and a completed-service fixture with honest provenance.
- [ ] Obtain usable `before.jpg`, `middle.jpg`, `after.jpg`, `unrelated.jpg`, `reused.jpg`; retain asset rights/provenance.
- [ ] Run the vision spike before building around its output; record findings in `docs/VISION_SPIKE.md` when run.

Vision spike protocol: compare before→middle (target removed, debris remains), before→after (target removed, clear), before→unrelated (scene mismatch), and before→reused (reuse rejected by hash). Include GPS distance, timestamp order, pHash, model ID, prompt, raw structured outputs, and observed failures. Repeat each pairing three times as a small stability check, not a benchmark. Any false automatic acceptance blocks unattended verification for that case. Freeze fixtures only after review.

Fallback decision tonight: ambiguous or unreliable findings trigger manual inspection. Preserve real model outputs and show the limitation. A manual-only result does not satisfy the automatic 100-point demo criterion; mark that gap honestly and use the remaining time to repair it. Vision uncertainty does not authorize fake success or a new product thesis.

## Saturday — ugly couch works

- [ ] Implement perception/state tools and agent-driven decisions.
- [ ] Implement policy-gated provider dispatch, budget reservation, and simulated settlement.
- [ ] Persist event/resume through crew proof and operator rework.
- [ ] Pass every step in `DEMO.md` using terminal/API output.
- [ ] Verify duplicate requests cannot dispatch/pay twice and prohibited work cannot dispatch.

**Gate:** all sixteen steps reproducible by Saturday night. If this fails, AgentCore is automatically cut. Continue the couch critical path; reduce presentation complexity before removing required behavior.

## Sunday morning — make decisions visible

- [ ] Operations Board with map and budget.
- [ ] Issue Detail with source evidence, score components, policy decisions, and tool events; highest polish priority.
- [ ] Operator Inbox and minimal Crew Form.
- [ ] Run the same acceptance flow through the UI.

## Sunday afternoon — evidence and submission artifacts

- [ ] Run the small internal evaluation in `EVALUATION.md`; publish counts and failures.
- [ ] Update README to actual setup/run/reset commands and observed behavior.
- [ ] Export implementation-accurate architecture diagram.
- [ ] Audit public source/assets/provenance and finish MIT copyright attribution.
- [ ] Complete submission description, judging access instructions, and recording script.

## Sunday evening — conditional deployment stretch

Only after acceptance, UI, evaluation, and required artifacts are stable: consider AgentCore/observability. Otherwise skip. Optional blog content is also behind the stable submission gate, with no three-post quota.

## Monday — freeze, reproduce, record, submit

- [ ] Morning feature freeze; fixes only.
- [ ] Clean install from scratch with documented credentials/configuration; run acceptance and negative cases.
- [ ] Record public demo under five minutes, take screenshots, finish Devpost.
- [ ] Submit by internal target; verify public links and saved submission before the hard deadline.
- [ ] No new feature coding Monday afternoon.

## Decision log

| Date | Decision | Reason |
|---|---|---|
| Sep 11 | Canonical scope locked | Cara's plan; prove one couch before adding product |
| Sep 11 | Preserve Python package; default SQLite | Existing starter supports a small reliable implementation |
| Sep 11 | Same-scene/reuse prerequisites separate from score | A high arithmetic score cannot validate unrelated or recycled evidence |
| Sep 11 | Service match may raise 85 to 100 | Keep score arithmetic consistent while disputing official resolution |

Append evidence-backed implementation decisions here. Do not use this log to reopen company ideation.
