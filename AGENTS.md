# Steward build instructions

Read `docs/PRD.md` (scope authority: scope, actors, journey, agent behavior, requirements), `docs/ARCHITECTURE.md` (code and deployment contract), `docs/DEMO.md` (acceptance criteria), and `docs/BUILD_PLAN.md` (tiers and gates) before implementation. Do not redesign the product before the ugly couch works.

- Build one Strands agent using Bedrock Sonnet. No multiple-agent runtime.
- Follow the locked V1 and exclusions. New ideas go to the post-competition vision, never the critical path. Reopen the thesis only for evidence of fundamental impossibility; record the evidence first.
- Models interpret evidence and choose actions. Deterministic code owns scores, authority, contract prices, budgets, verification gates, and simulated settlement.
- Persist state across invocations. Tools must enforce policy at the mutation boundary, including when called outside the agent.
- Show evidence, structured findings, decisions, and policy results; never expose hidden chain-of-thought.
- Label seeded inputs, fallbacks, and simulated dispatch/settlement honestly. Do not claim planned work is implemented or fabricate evaluation results.
- Finish the sixteen demo criteria through the API before building surfaces, and through the UI before deploying. Follow the four-tier build order in the PRD: core proof, presentation, AgentCore and App Runner hosting, optional flags. Nothing is cut; lower tiers slip. Monday is feature freeze and submission.
- Agent tools are HTTP clients of the FastAPI service, which owns SQLite and enforces policy at every mutation. Keep one tool implementation for local and AgentCore runs.
- Preserve the existing Python package layout unless a concrete implementation need requires a change.
