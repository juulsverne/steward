# Document review — September 13, 2026

This review reconciles Fable's handoff with the checkout. It is not evidence that the couch acceptance flow works. Scope remains [PRD.md](PRD.md); [ARCHITECTURE.md](ARCHITECTURE.md) defines the implementation contract; [DEMO.md](DEMO.md) supplies the sixteen acceptance criteria; [BUILD_PLAN.md](BUILD_PLAN.md) records gates and observed results.

## Recovered work

On branch `tier-1a`, commits `e16b880`, `3adb968`, `688a108`, and `4e1fccf` implement the service-record rule, persistence bonus, transactional dispute gate, and offline harness. Baseline recheck: **57 tests passed**, Ruff clean. Fable's separate image-utility commit `360245d` was recovered from `tier-1a-images` as `36b047e`. The untracked `.claude/` directory and local SQLite artifacts are unrelated retained work.

The dated foundation plan is historical; its immediate service-match rule was superseded. The Tier 1A plan and handoff ledger were stale about completion. The Tier 1B-i plan is a draft, not implemented API behavior. README and build checkpoints must reflect actual runs rather than unchecked plan text.

## Corrections for Tier 1A

| Finding | Resolution |
|---|---|
| Vision created another Strands `Agent` | Inspect images with one bounded Bedrock Converse request using the same configured Sonnet; return validated findings. Only the orchestration loop is an agent. |
| Spike exited successfully on model errors or a clear image that never passed | Pass requires all requested runs, no errors, expected findings, expected prerequisites/payment eligibility, and exact 90/100 positive-case scores. Zero runs is invalid. |
| Clear rework image had no prior-completion comparison | Compare `after` against the earlier `middle` submission. Compare recycled `reused` against `middle` and `after`. Never put `before` in this set. Record any false reuse as a blocking fixture result. |
| Unknown scoring findings were missing from the prerequisite gate | Any unresolved nullable finding blocks acceptance; arithmetic remains diagnostic. |
| Bedrock check only inspected a requested tool name | Require a matching successful tool result and a final model response. Bound the model cycle count and retries; retain failure artifacts. |
| Spike hardcoded GPS/time booleans and omitted prompt/usage | Use explicitly seeded coordinates and timestamps, derive distance/order, record prompt version, image digests, structured output, usage, and failures. |
| Setup compared inference-profile IDs against foundation-model IDs | Inspect the configured inference profile separately; only real inference proves access. Preserve the selected model. |
| Pydantic was only transitive | Declare the directly imported package; do not add another runtime framework. |

AWS references checked for these corrections: [Converse API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html), [inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-use.html), [model access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html). On this PC the only configured AWS profile was `default`; its session was expired. The user subsequently refreshed login; the real Strands check and all twelve vision comparisons passed. See VISION_SPIKE.md for retained results. Tier 1B policy/fixtures then started; the combined suite is 129 passing tests, with Ruff clean.

## Documents and remaining gates

| Document | Assessment |
|---|---|
| `AGENTS.md`, `PRD.md` | One agent, deterministic authority, persistence, and locked scope remain the controlling requirements. |
| `ARCHITECTURE.md` | Local SQLite matches the foundation. Hosting durability has the separate blocker below. |
| `DEMO.md` | Keep all sixteen criteria open until actual live API/UI evidence exists; offline tests close none. |
| `BUILD_PLAN.md`, `README.md`, `data/README.md` | Update current checkpoints and image provenance as work is verified. Move full policy/vendor/address fixtures into Tier 1B where their implementation is planned. |
| `EVALUATION.md` | Twenty-two scenarios, no claimed results. Repeats and comparison remain as specified here. |
| `SUBMISSION.md` | Release checklist remains open. Account registration, public access, rights, video, and submission are not inferred from local code. |
| `VISION.md` | Future commercial work stays outside the critical path. |
| Local `MODEL-ROUTING-PLAN.md` | Historical, outside V1. Replace the broken scope link with PRD; access observations remain dated. |
| Local `AGENT-ENGINEERING-CHECKLIST.md` | Advisory only: remove stale document names, twenty-case wording, mandatory extra eval repeats, and lower priority assigned to in-scope hosting. No Jaeger/cache/extra-model prerequisite is added. |
| Local `MAC-REMOTE.md` | Historical machine setup, not a current remote checkout audit. No Mac synchronization or service changes performed in this continuation. |
| Local plans and `.superpowers` ledger | Retain handoff evidence and record continuation status; do not treat expected outputs as observed results. |

## Tier 3 blocker: App Runner storage

The target's statement that SQLite resets only on redeploy is unsupported. AWS explicitly does not guarantee local filesystem persistence beyond a single request; instance replacement, scaling, and pause/resume can lose or split state. A reset script cannot preserve an in-flight operator wait or settlement ledger. [AWS App Runner development contract](https://docs.aws.amazon.com/apprunner/latest/dg/develop.html).

This is a hosting-contract conflict, not a reason to redesign the local couch. Keep the local SQLite build. Before Tier 3, select and document a persistent state owner compatible with the required host, or approve a stateful hosting adjustment; then verify cross-request/restart persistence. An App Runner deployment alone must not close this gate.

## Build continuation

1. Completed Tier 1A utilities, synthetic image assets, bounded Bedrock check, strict verification and spike runner.
2. Verified live Bedrock and four pairings × three after AWS login; all twelve expected outcomes passed and the earlier login failure remains retained.
3. Started Tier 1B-i with tested pure policy and seeded fixtures. Next: transactional state/API, then Strands HTTP tools and event invocation. Review actor binding, denial events, proof races, dependency declarations and resume contracts before executing those remaining draft tasks.
4. Pass sixteen steps through the API before surfaces; pass UI flow before hosting. Resolve the hosting durability conflict at the hosting gate.

## End-to-end build-guide review — September 13

Reviewed checkout `dd6c61e` and replaced the short tier checklist in [BUILD_PLAN.md](BUILD_PLAN.md) with a complete guide for learning and handoff. Each task explains what is built, why, its dependencies/connections, implementation files, construction steps and inspectable completion evidence. The guide includes plain-language AWS service roles, data/workflow/build graphs, trigger-specific context, all presentation/hosting/optional/release work, and PRD/demo coverage tables. Historical checkpoints and decisions are retained.

Fresh verification: `uv run --no-sync pytest -q` returned **129 passed in 2.15s**; `uv run --no-sync ruff check .` returned **All checks passed**. The installed environment required access outside the restricted shell. Source inspection confirms `core.py` still has the starter prompt/registry, `server.py` only the starter health/ask routes, and `store.py` only the schema-1 foundation. The retained September 13 preflight and vision artifacts have passed results; they were inspected, not rerun. This review did not change application code, call Bedrock, audit the Mac, push, or deploy.

| Finding | Explicit build owner |
|---|---|
| Receipt must survive unresolved location/matching; current store immediately links | B1/B3/B4: unlinked signal persistence and later validated matching |
| Jobs, actor events, evidence submissions, ledger, decisions and invocation recovery are absent | B1–B9/B12: persistent records, API permissions and transactional behavior |
| Pure policy/vision helpers are not mutation-boundary enforcement | B5/B7/B9/B10: current-state gates on real HTTP operations |
| Agent instructions, HTTP tools and per-trigger context are absent | B10–B12: one domain agent, context contracts, bounded event processing and traces |
| API criteria 5/15 precede screens | B13 verifies response data; P7 separately verifies actual UI comparison and Board |
| Private engineering notes are incomplete/stale and cannot be a public build prerequisite | Public guide carries the complete handoff and maps every PRD requirement/demo criterion |
| PRD vision open-item wording and architecture threshold-choice wording lag verified code/docs | Guide identifies the dated 12/12 spike and locked 30 m threshold; no scope/number changes |
| Hosted records and uploaded image bytes need durable ownership; accepted events need recoverable processing | H1 decision/proof before H2–H6 deployment integration |

The local implementation is ready to continue at B1. The guide does not claim the workflow is already wired, the evaluation has run, or hosted persistence is resolved. App Runner storage documentation was rechecked and still confirms the existing conflict; no replacement architecture was silently selected.

## PRD format and build-context review — September 13

Compared Steward's PRD with four locally available project PRDs, reading their structure and representative requirements, user stories, quality, data and acceptance sections. This was a document comparison, not an implementation audit of those projects. No private project content was copied into Steward.

| Reference | Pattern applied here | Limit |
|---|---|---|
| Vibe Modeling | Document control, user goals, numbered stories with Given/When/Then acceptance, explicit NFRs and links to authoritative data/API documents | Its platform scope and operational targets do not transfer to a one-couch hackathon |
| Date Website Agent | Actor-specific journeys, defaults, receipt-before-success behavior, privacy and accessible mobile interaction requirements | Steward keeps its own sandbox permissions and existing surfaces |
| ElijahOS WebMCP | Concise user/agent stories, typed contracts and separate implementation/test/deployment evidence | Retrospective release PRD; its completion claims say nothing about Steward |
| Xorva archived PRD | Persona-to-capability mapping and clear separation of built, partial and planned work | Explicitly historical/superseded inventory; no status, enterprise controls or market claims reused |

The v3 PRD already had a strong couch narrative, exact policy arithmetic, actors, exclusions and agent stopping rules. Its weakness was discoverability and uneven detail: user goals and acceptance examples were implicit, while most data/API/recovery/quality contracts required searching the much longer build guide. PRD v3.1 makes those contracts visible without moving the implementation task list into the PRD.

| Gap or ambiguity | Resolution |
|---|---|
| Product purpose and success were mostly a demo narrative | Added problem/value framing and G-01–05 observable goals |
| Permission matrix did not state what each actor needed | Added primary operator, crew, resident and service jobs to be done |
| PR-01–14 were short behavior labels | Preserved IDs; added US-01–10 Given/When/Then examples linked to requirements and acceptance |
| Data/API information scattered across architecture and build tasks | Added a logical record dictionary, lifecycle/retention summary and caller contracts; exact schemas/routes remain with their owners |
| Quality requirements were distributed across task cards | Added NFR-01–11 with existing build owners: durability, concurrent retries, authority, uploads, privacy, bounded work, responsiveness, accessibility, traces, reproducibility and parity |
| Success, component tests and evaluation could be conflated | Added a measurement table distinguishing sixteen acceptance criteria, twenty-two scenarios and twelve vision inspections |
| Seeded budget and score cap were implicit in the PRD | Made existing $500 budget/$428 available balance and 100-point evidence cap explicit; no policy change |
| Vision status and geocode wording were stale | Linked the dated passed fixture spike; locked 30 m threshold matches code/policy |
| Required fixture lookup included unsupported general rate-limit claims | Removed hardcoded provider quota claims; O1 must verify current limits before enabling live access |
| Hosting target could be read as permission to persist only in App Runner | Made the existing H1 durable-state decision explicit; no host/database adaptation selected |

Retained all four tiers, exclusions, policy values, PR IDs, sixteen DEMO criteria and twenty-two EVALUATION cases. The document version is 3.1; runtime policy stays `south-loop-v3`. README navigation and the build guide's coverage map now point to the expanded context. AWS's [App Runner storage contract](https://docs.aws.amazon.com/apprunner/latest/dg/develop.html) was rechecked for the open hosting decision.

Before the PRD edits, the requested integration committed the pending guide as `e11538c`, fast-forwarded local `main` to `tier-1a`, and merged `tier-1a-images` as `f3b6de3`. Git confirmed the image patch was already present via its earlier cherry-pick; dependency conflicts retained the newer Pydantic declaration/lockfile. The merge tree is identical to `e11538c`. Fresh verification used the installed environment: `.venv/Scripts/python.exe -m pytest -q` returned **129 passed in 2.23s**, and `.venv/Scripts/ruff.exe check .` returned **All checks passed**. The first `uv` invocation was blocked by restricted cache access; the Python test run required access outside the restricted shell. Local Claude settings were excluded. No push, deployment, Mac synchronization, new inference, evaluation run or acceptance completion occurred.

Documentation verification: `git diff --check` passed; all **45 relative file links** across the five edited documents and all PRD table-of-contents anchors resolve. The PRD retains **14 original PR IDs**, adds **10 explanatory stories** and **11 cross-cutting NFRs**, and the acceptance/evaluation files remain unchanged at **16 criteria / 22 cases**. Application source, tests, policy data and dependency files are unchanged by this PRD review. Both requested branches are ancestors of local `main`.
