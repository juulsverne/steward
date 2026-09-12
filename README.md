# Steward

**Autonomous neighborhood operations. Steward manages reality, not tickets.**

Steward turns scattered community signals into verified physical resolutions. It investigates evidence, reconciles contradictory service records, dispatches approved supplemental providers within explicit policy, and verifies completion before simulated settlement. It brings neighborhood operators the exceptions that need human judgment.

Built for the **Good Neighbor Agents** track of the AWS Agents for Humans Hackathon.

## Status

The canonical V1 plan is locked. This repository currently contains a generic Python Strands/Bedrock agent, terminal entrypoint, FastAPI/SSE endpoint, and starter tests. The Steward couch workflow, persistence, policy tools, vision verification, and operations UI are **not implemented yet**. Installed dependencies alone do not establish working AWS access.

The competition proof is one couch: wait at evidence score 65; corroborate at 85; dispute a completed service record when newer physical evidence disagrees; dispatch an authorized $72 cleanup; block payment at verification score 90; resume after operator-requested rework; verify at 100; simulate payment and resolve.

## Locked build documents

- [Canonical V1 and exclusions](docs/STEWARD.md)
- [Product requirements](docs/PRD.md)
- [User models and permissions](docs/USER_MODELS.md)
- [Agent behavior contract](docs/AGENT_CONTRACT.md)
- [Architecture, data, tools, and policy contract](docs/ARCHITECTURE.md)
- [Deadline build plan and gates](docs/BUILD_PLAN.md)
- [Sixteen acceptance criteria and demo script](docs/DEMO.md)
- [Internal evaluation protocol](docs/EVALUATION.md)
- [Submission checklist](docs/SUBMISSION.md)
- [Post-competition company vision](docs/VISION.md)
- [Coding-agent instructions](AGENTS.md)

Deadline: Monday, September 14, 2026 at **5 PM Pacific / 7 PM Chicago**. Internal submission target is two hours earlier. One Strands agent, Bedrock Sonnet, deterministic policy; AgentCore is optional after the core is stable.

## Run the existing starter

Requires Python 3.11+, uv, and AWS credentials with access to the configured Bedrock model. Inspect `.env.example` for configuration. Keep credentials out of source control.

```bash
uv sync --extra dev --extra web
cp .env.example .env
# Configure .env and AWS credentials for your environment.
uv run agent
```

For the starter HTTP endpoint:

```bash
uv run uvicorn agent.server:app --reload
curl -N -X POST localhost:8000/ask -H 'content-type: application/json' \
  -d '{"prompt":"what time is it?"}'
```

Starter checks:

```bash
uv run pytest
uv run ruff check .
```

These commands run the starter, not the planned Steward demo. Clean-install verification and demo reset/seed commands will be added as implementation lands.

## Project layout

```text
src/agent/       Existing Strands agent, configuration, CLI, API, tools
 tests/         Starter tests; extend with meaningful policy/workflow checks
 docs/          Locked specifications, acceptance, evaluation, submission
 scripts/       Existing environment/preflight helpers
```

Planned additions include models/policy/persistence under the existing Python package, `data/` fixtures, `evals/`, a small `web/` UI, and an exported architecture diagram. Do not rename the package merely to match a conceptual tree.

## Demo boundaries and license

Vendors, rates, budget, district authority, community feed, and fallback records are seeded. Dispatch and settlement are simulated. Live versus fixture inputs and generated imagery will be labeled. No real money or municipal work is authorized by this demo.

MIT; see [LICENSE](LICENSE). Copyright attribution is still a starter placeholder and must be completed before public submission. All assets needed for the submitted functionality must have publishable provenance and usage rights.
