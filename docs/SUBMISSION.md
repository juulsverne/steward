# Submission checklist

**Deadline: September 14, 2026, 5 PM Pacific / 7 PM Chicago.** Track: **Good Neighbor Agents**. Requirements were checked against the [official rules](https://agentsforhumans.devpost.com/rules) on September 11, 2026. Strands is required; AgentCore is optional under the rules and tier 3 in our [build order](PRD.md#45-build-order). Build gates live in [BUILD_PLAN.md](BUILD_PLAN.md).

State of this checklist as of September 14 finish review: the materials below are written and committed, and GitHub confirms the repository is public. Video publication and Devpost submission remain owner actions without completion evidence. Nothing here invents a link.

## Project description (paste into Devpost)

**Steward — autonomous neighborhood operations. Steward manages reality, not tickets.**

A neighborhood operator hears about the same dumped couch three times: a community post, a resident report, and a city 311 record that says the job is done. Steward turns those scattered signals into one verified physical resolution. It links observations to one issue, scores the evidence with fixed rules, looks up the official record, and — when a closed record disagrees with newer photos — disputes it instead of trusting it. Within the district's written policy and budget it dispatches an approved provider, and it pays (simulated) only after a fresh photo proves the sidewalk is clear. The one decision code cannot make, it hands to a person with the evidence attached.

**What it does, on one couch.** The first photo and a precise location score 65 evidence points; 70 is needed. The 311 lookup returns a *completed* record, which earns nothing, so Steward records the conflict and waits, stating what would unlock action. A second independent resident report raises the score to 85; two observations newer than the city's completion time confirm the dispute and the score reaches 100. Policy permits supplemental bulky-waste cleanup, code computes a $72 quote ($60 base + $12 large object), and the dispatch tool creates one job and reserves $72 once. The crew accepts, checks in, and submits a photo: couch gone, bags left. Bedrock vision returns structured findings; code scores 90 against the 95 required, the settlement tool denies payment and changes nothing, and Steward opens one exception for the operator. The operator's only action is *Request completion*; the agent resumes with a rework instruction on the same job and the same quote. Fresh proof passes the scene and reuse prerequisites, scores 100, exactly one simulated $72 settlement occurs, and the issue resolves. The Board's marker turns green; the denied attempt and the human decision stay in the timeline.

**How it is built.** One Strands agent on Amazon Bedrock (`global.anthropic.claude-sonnet-4-6`, `us-west-2`) reads the saved case and chooses its next tool: find related signals, search 311, classify, determine jurisdiction, plan, list vendors, dispatch, inspect, settle, close, escalate, or explicitly wait. Every tool is an HTTP call into a FastAPI service that owns SQLite state and enforces policy at every mutation — evidence points, authority, quotes, the budget ledger in integer cents, verification gates, idempotent settlement. The agent never opens the database and cannot set a score, a price, a budget or a human action. Photo inspection is a trusted server-side Bedrock vision call whose findings code scores; the model interprets, code decides. Five screens (Operations Board, Issue Detail, Operator Inbox, Crew Form, Resident intake) read the persisted records and show every label: live, seeded, synthetic, simulated. The design contract is in `docs/ARCHITECTURE.md` and `architecture.png`.

**Who it is for.** District operators (business improvement districts, neighborhood associations, community-benefit organizations) who already pay approved providers for supplemental cleanup and who today reconcile reports, records and crew photos by hand. Residents report without knowing jurisdiction or contractor categories. Crews see exactly what remains after a rejection.

**What was proven and what was not.** The sixteen-step couch acceptance passed live through the API in two independently seeded runs on September 14 with real Bedrock text and vision, and its rendered states were inspected afterward (`docs/DEMO.md`, `docs/evaluations/2026-09-14-ui-walk.md`). 706 offline tests passed on clean-install candidate `57e7e27`; a twelve-comparison vision check scored 12/12. The twenty-two-scenario internal evaluation has **not** run, so no accuracy or reliability figure is claimed. Hosted for judging on EC2 + CloudFront (deployed September 14; acceptance evidence: docs/evaluations/2026-09-14-hosted-acceptance.md). The hosted candidate `57e7e27` passed criteria 1–15 and service restart/reboot checks. Hosted criterion 16, instance replacement and backup restoration remain unverified; the UI from `2f31548` is now deployed with the same backend; see [release receipt](evaluations/2026-09-14-ui-release.md). AgentCore Runtime, Observability and Gateway are not deployed. The district, budget, providers, addresses, reporter identities, community feed and 311 record are seeded fixtures; the photos are synthetic images generated for this project with published prompts; dispatch and settlement are simulated. No real money or municipal work is involved.

## Judging access

**Primary: the hosted system.** Hosted for judging on EC2 + CloudFront (deployed September 14; acceptance evidence: docs/evaluations/2026-09-14-hosted-acceptance.md). Public URL: `https://d1uke66gfefpu4.cloudfront.net` — one EC2 `t3.small` in `us-west-2` with a retained EBS data volume for SQLite and images, private S3 backups, nginx + uvicorn, the in-process Strands runtime, behind CloudFront. It serves `/health` and the Board; pick a persona in the header (a labeled sandbox, not authentication) and walk the Board, Issue Detail, Inbox, Crew Form and Report screens. The hosted acceptance run and the restart/reboot durability proof are recorded by the hosting worker in `docs/evaluations/2026-09-14-hosted-acceptance.md`, with the decision in [HOSTING_DECISION.md](HOSTING_DECISION.md); this checklist does not claim their result. The rules ask for free, unrestricted access through October 8; the owner keeps the instance up through that date.

**Fallback: clone and run.** The documented path in [README.md](RUNNING.md#run-it-yourself): clone the repository, `uv sync --locked --extra dev --extra web`, build the frontend, put two generated secrets and your own AWS profile in `.env`, seed, start the API with `STEWARD_RUNTIME_ENABLED=true`, and run `python -m agent.demo`. It requires the judge's own AWS account with Bedrock access to `global.anthropic.claude-sonnet-4-6` and costs a few dollars of inference per full run. Everything else (screens, tests, the offline scoring harness, the seeded state) runs without AWS.

## What is implemented and what is not

| Area | State |
|---|---|
| One Strands agent with typed HTTP tools, bounded invocations, journaled claims/retries/resume | Implemented, verified live (B10–B13) |
| FastAPI policy owner: scoring, authority, quotes, ledger, verification gates, idempotent settlement, closure, cancellation | Implemented; 706-test clean-install suite on `57e7e27` |
| Trusted Bedrock vision inspection for intake and completion proof | Implemented; 12/12 spike, requalified September 14 |
| Five screens with persona sandbox, light/dark themes, 360 px layouts, keyboard access | P1–P6 implemented; rendered-state UI walk recorded; P7 browser repeat open |
| Sixteen-step acceptance | API repeat passed; rendered UI states inspected; complete browser-driven P7 repeat remains open |
| Reset/reseed and reproducible isolated acceptance runs (`scripts/acceptance_run.sh`) | Implemented |
| Synthetic images with prompts and fingerprints; supplemental evaluation images | Implemented and documented |
| Twenty-two-scenario internal evaluation (`python -m agent.evaluate`) | **Not run; command not built (P8)** |
| Plain-model comparison arm | Not built (tier 4) |
| AgentCore Runtime / Observability / Gateway | **Not deployed** (tier 3); the agent runs in-process next to the API, locally and on the hosted instance |
| Hosted API and screens with a public judging URL | Hosted for judging on EC2 + CloudFront (deployed September 14; acceptance evidence: docs/evaluations/2026-09-14-hosted-acceptance.md); decision in [HOSTING_DECISION.md](HOSTING_DECISION.md) |
| Live Chicago 311 lookup, Amazon Location geocoding | Not built (tier 4, flags); seeded fixtures are used |
| Clean-install proof from a fresh clone with recorded commands | Passed on candidate `57e7e27`; [706-test clean-install receipt](evaluations/2026-09-14-clean-install.md) |
| Real payments, identity verification, policy editor, multiple agents | Excluded by design (PRD 4.6) |

## Required release work

- [x] Detectable MIT license with a named copyright holder ([LICENSE](../LICENSE)).
- [x] README with setup, run, reset, demo and recovery instructions ([README.md](../README.md)).
- [x] Architecture diagram matching the implementation: `architecture.png` (source `docs/architecture.svg`), deployed EC2/CloudFront distinguished from unbuilt AgentCore components.
- [x] Project description explaining functionality, audience and value (above).
- [x] Recording script for a demo of at most five minutes ([DEMO.md](DEMO.md#recording-script--maximum-5-minutes)).
- [x] Disclosure of incorporated pre-existing work and third-party rights (below).
- [x] Devpost draft created; AWS Builder ID verified on the owner's profile and saved. Final submission remains pending.
- [x] **Repository visibility:** GitHub API verified `private: false` on September 14 for `https://github.com/juulsverne/steward`. Final source/assets/instructions and signed-out judging access still require the final candidate check.
- [ ] **Owner:** record the video from the script, upload it to YouTube or Vimeo as public, and test the link signed out.
- [ ] **Owner:** judging access — paste the hosted URL and the clone-and-run fallback from above; keep the instance running through October 8.
- [ ] **Owner:** save the Devpost submission and verify it before the deadline.

## Steward release checks

- [x] All sixteen [acceptance steps](DEMO.md) pass through the API (September 14, runs 16 and 20).
- [ ] Complete browser-driven P7 run and repeat. The [walk](evaluations/2026-09-14-ui-walk.md) covers rendered states; criteria 2/16 use driver evidence and criterion 11 uses tests.
- [x] Negative policy/verification cases and retry idempotency pass in the offline suite; the live run contains the real 90/95 denial.
- [x] [Clean install](evaluations/2026-09-14-clean-install.md): candidate `57e7e27`, 706 backend tests, frontend tests/typecheck/build and live preflight.
- [x] Real/seeded/synthetic/simulated labels match runtime behavior, screenshots and the recording script.
- [ ] Evaluation counts, denominators, failures and limitations — **not available; the evaluation has not run.** The video and description say so.
- [x] No secrets or credentials in the tree or history; two low-sensitivity local-path disclosures remain and are named in the rights section below, flagged for the owner.
- [ ] **Owner:** video, repository, judging access and submission links tested while signed out.
- [ ] **Owner:** Devpost submission saved and verified.

## Pre-existing work, third-party assets and rights

- The repository began from a generic Strands/Bedrock starter (`Scaffold Strands agent project`, commit `896e607`, September 11): `pyproject.toml`, `.env.example`, `scripts/preflight.ps1`, a terminal agent, a `/ask` FastAPI route (since removed) and an example tool. Everything else was written for this project during the hackathon.
- Open-source dependencies are used under their own licenses and are not vendored: Strands Agents, boto3, FastAPI, Starlette, uvicorn, Pydantic, httpx, Pillow, itsdangerous, python-multipart, pytest, Ruff (Python); React, react-router, Vite, TypeScript, vitest, Leaflet (frontend). Fonts Public Sans and Newsreader ship through `@fontsource-variable` under the SIL Open Font License.
- Map tiles are requested from `tile.openstreetmap.org` at runtime with the "Map data © OpenStreetMap contributors" caption shown under the map; nothing is cached or redistributed.
- The five demo images and six supplemental images are synthetic, generated for this project on September 13 from prompts published in [data/images/PROVENANCE.md](../data/images/PROVENANCE.md) and [data/images/supplemental/PROMPTS.md](../data/images/supplemental/PROMPTS.md); fingerprints are in the manifests. The generation tool's terms govern their use; they depict no real place, person or incident.
- All other fixtures (district, budget, providers, addresses, reporters, feed, 311 record) are invented demo data ([data/README.md](../data/README.md)). Chicago and the South Loop are used as a setting only; no municipal data or authority is claimed.
- The credential/provenance pass on September 14 grepped the tree and full history for keys, tokens and private paths. No secrets or credentials were found; `.env`, `.steward/`, local notes and worktrees are gitignored and were never committed. Two low-sensitivity local-path disclosures remain, flagged for the owner: the tracked plan file `docs/superpowers/plans/2026-09-14-frontend.md` contains the literal path `D:\devgents-for-humans\.worktrees\steward-build`, and the historical commit `2a49c02` (reachable from `main`; its files `docs/MAC-REMOTE.md` and `scripts/mac-session.sh` were removed in `c2f4497` but not purged) contains `/Users/cara/...` paths and an ssh host alias `mac-mini-tailscale`. Neither contains a credential.

## Future tiers after the submission freeze

AgentCore Runtime, Observability and Gateway are the remaining tier 3 items (the hosted judging URL is deployed); live 311, Amazon Location and the plain-model evaluation arm are tier 4. [EVALUATION.md](EVALUATION.md) defines equal model/input conditions and how any separate model arm must disclose its differences. None of these displaces the working couch, the evaluation, README, diagram or video. The AWS credit request deadline (September 11) has passed and is not an open prerequisite.

## Final links — fill when real

- Public repository: `https://github.com/juulsverne/steward` (public visibility verified September 14)
- Judging access and instructions: `https://d1uke66gfefpu4.cloudfront.net` (hosted, see above); clone-and-run fallback in [README.md](RUNNING.md#run-it-yourself)
- Public video: pending owner recording and upload
- Devpost submission: pending owner action
- Clean-install/acceptance run evidence: local acceptance in [DEMO.md](DEMO.md#run-artifacts) and the [UI walk](evaluations/2026-09-14-ui-walk.md); hosted acceptance in `docs/evaluations/2026-09-14-hosted-acceptance.md` (written by the hosting worker); clean install in the [R1 report](evaluations/2026-09-14-clean-install.md)
