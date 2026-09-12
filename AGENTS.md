# Steward build instructions

Read `docs/STEWARD.md`, `docs/BUILD_PLAN.md`, and `docs/ARCHITECTURE.md` before implementation. Read `docs/DEMO.md` for acceptance criteria. These implement Cara's canonical September 11 plan; do not redesign the product before the ugly couch works.

- Build one Strands agent using Bedrock Sonnet. No multiple-agent runtime.
- Follow the locked V1 and exclusions. New ideas go to the post-competition vision, never the critical path. Reopen the thesis only for evidence of fundamental impossibility; record the evidence first.
- Models interpret evidence and choose actions. Deterministic code owns scores, authority, contract prices, budgets, verification gates, and simulated settlement.
- Persist state across invocations. Tools must enforce policy at the mutation boundary, including when called outside the agent.
- Show evidence, structured findings, decisions, and policy results; never expose hidden chain-of-thought.
- Label seeded inputs, fallbacks, and simulated dispatch/settlement honestly. Do not claim planned work is implemented or fabricate evaluation results.
- Finish the sixteen demo criteria before adding product. AgentCore is optional and cut if Saturday's end-to-end gate fails. Monday is feature freeze and submission.
- Preserve the existing Python package layout unless a concrete implementation need requires a change.

## Personal delegation preferences

When Cara asks to delegate to Claude, Fable, or another Claude model, use `/Users/cara/.local/bin/claude -p`. Pass a requested model and effort explicitly (for example, `--model claude-fable-5 --effort medium`). Do not substitute Codex subagents or another mechanism unless explicitly requested. If the CLI is unavailable or fails to start, report that instead of silently falling back.
