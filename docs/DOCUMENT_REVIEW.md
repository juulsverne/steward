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
