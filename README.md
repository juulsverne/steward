# Steward

**Autonomous neighborhood operations. Steward manages reality, not tickets.**

Steward turns scattered community signals into verified physical resolutions. It investigates evidence, reconciles contradictory service records, dispatches approved supplemental providers within explicit policy, and verifies completion before simulated settlement. It brings neighborhood operators the exceptions that need human judgment.

Built for the **Good Neighbor Agents** track of the AWS Agents for Humans Hackathon.

## Status

The hackathon scope is locked in [PRD.md](docs/PRD.md). This public **Steward OSS** reference implementation proves one couch resolution; the future private commercial platform is described separately in [VISION.md](docs/VISION.md).

Implemented: the existing generic Strands/Bedrock terminal/API starter, plus a SQLite foundation for validated signals, explicit issue links, explainable evidence scores, and append-only audit events. The offline fixture command verifies persistence across connections and scores 65 then 85. The full Steward agent workflow, dispatch/payment policy tools, vision verification, and operations UI are **not implemented yet**. Installed dependencies alone do not establish working AWS access.

The competition proof is one couch: wait at evidence score 65; corroborate at 85; dispute a completed service record when newer physical evidence disagrees; dispatch an authorized $72 cleanup; block payment at verification score 90; resume after operator-requested rework; verify at 100; simulate payment and resolve.

## Build documents

- [Hackathon build spec: scope, actors, journey, agent behavior, requirements](docs/PRD.md)
- [Architecture, data, tools, policy, and deployment contract](docs/ARCHITECTURE.md)
- [Build plan, tiers, and gates](docs/BUILD_PLAN.md)
- [Sixteen acceptance criteria and demo script](docs/DEMO.md)
- [Internal evaluation protocol](docs/EVALUATION.md)
- [Submission checklist](docs/SUBMISSION.md)
- [Post-competition company vision](docs/VISION.md)
- [Coding-agent instructions](AGENTS.md)

Deadline: Monday, September 14, 2026 at **5 PM Pacific / 7 PM Chicago**. Internal submission target is two hours earlier. One Strands agent, Bedrock Sonnet, deterministic policy. Build order: core proof through the API, then the React surfaces and evaluation, then AgentCore Runtime with App Runner hosting, then optional flags.

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

The agent/API commands still run the generic starter, not the planned Steward agent. Clean-install verification and full demo reset/seed commands remain open.

## Run the offline foundation

From the repository root, after installing the dependencies:

```bash
uv run python -m agent.foundation --db .steward/foundation.sqlite3
```

No AWS credentials are needed for this command. It prints **OFFLINE FOUNDATION CHECK**, stores the first report at 65 points, records the seeded COMPLETED service record as a pending conflict (still 65), reopens SQLite, adds an independent report to reach 85, and confirms the official-status dispute to reach 100. The issue stays CANDIDATE: a score is not a fabricated agent decision. An existing destination is refused; use a fresh database filename to repeat.

The image digest and geocode accuracy are **seeded metadata**, not actual photo analysis or live geocoding. See [fixture provenance and limitations](data/README.md). This harness does not satisfy the sixteen-step live-agent acceptance run.

Verified September 12: `uv run --no-sync pytest -q` — **32 passed**; `uv run --no-sync ruff check .` — **All checks passed**. Tests include duplicate-source handling, early service-record scoring, restart/retry behavior, concurrent duplicate delivery, transaction rollback, immutable events, and protection against overwriting an existing database.

## Project layout

```text
src/agent/      Strands starter plus models, scoring, SQLite store, offline harness
tests/          Starter and foundation behavior checks
data/           Labeled foundation fixtures and scoring-policy manifest
docs/           Locked specifications, acceptance, evaluation, submission
scripts/        Existing environment/preflight helpers
```

Next additions include policy-gated jobs/reservations/settlement, real agent tools and vision, complete fixtures, `evals/`, a small UI, and an exported architecture diagram. Preserve the existing Python package layout.

## Demo boundaries and license

Vendors, rates, budget, district authority, community feed, and fallback records are seeded. Dispatch and settlement are simulated. Live versus fixture inputs and generated imagery will be labeled. No real money or municipal work is authorized by this demo.

MIT; see [LICENSE](LICENSE). Copyright attribution is still a starter placeholder and must be completed before public submission. All assets needed for the submitted functionality must have publishable provenance and usage rights.
