# Steward

**Autonomous neighborhood operations. Steward manages reality, not tickets.**

Steward turns scattered community signals into verified physical resolutions. It investigates evidence, reconciles contradictory service records, dispatches approved supplemental providers within explicit policy, and verifies completion before simulated settlement. It brings neighborhood operators the exceptions that need human judgment.

Built for the **Good Neighbor Agents** track of the AWS Agents for Humans Hackathon.

## Status

The hackathon scope is locked in [PRD.md](docs/PRD.md). This public **Steward OSS** reference implementation is being built to prove one couch resolution; the future private commercial platform is described separately in [VISION.md](docs/VISION.md).

Implemented: the generic Strands/Bedrock starter; SQLite signals, issue links, scoring and audit events; the persisted 65 → 65 → 85 → 100 service-record/dispute sequence; five labeled synthetic images; image fingerprints; strict verification gates; a bounded Strands preflight and single-call Bedrock vision spike runner. The full Steward agent workflow, dispatch/payment policy tools, and operations UI are **not implemented yet**. After AWS login, the live Strands round trip and all twelve vision comparisons passed on September 13. Tier 1B has started with a pure policy module and seeded district/vendor/address fixtures; policy is not yet wired into mutation endpoints. See [vision readiness](docs/VISION_SPIKE.md) and [document review](docs/DOCUMENT_REVIEW.md).

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

The first image digest identifies the actual synthetic `data/images/before.jpg`; geocode accuracy and source observations remain **seeded metadata**. The harness performs no photo analysis or live geocoding. See [fixture provenance and limitations](data/README.md). This harness does not satisfy the sixteen-step live-agent acceptance run.

Verified September 13: `uv run --no-sync pytest -q` — **129 passed**; `uv run --no-sync ruff check .` — **All checks passed**. Tests cover service-record/persistence scoring, source independence, restart/retry and transactional behavior, image reuse, strict verification, model-response validation, and spike failure gates. The foundation rerun retained six events and totals 65/65/85/100. This used the existing local Python environment; clean-install acceptance remains open.

## Run the live Tier 1A checks

Use your authenticated AWS profile (`aws login --profile default` refreshes the PC profile used for the verified run). Set `AWS_PROFILE` to that profile if a different value is in your environment or `.env`; never overwrite existing configuration blindly. Then run:

```powershell
uv run --no-sync python -m agent.bedrock_check
# Continue only after the round-trip check passes:
uv run --no-sync python -m agent.vision_spike --images data/images --repeats 3
```

The preflight requires a successful tool result and final model reply. The spike requires twelve expected outcomes, including partial score 90, complete score 100, and scene/reuse rejection. It uses the same configured Sonnet through Converse without constructing another agent. Results and failures are retained under `.steward/`; [VISION_SPIKE.md](docs/VISION_SPIKE.md) reports actual status. These commands do not dispatch, pay, or resolve an issue.

## Project layout

```text
src/agent/      Strands starter, store/scoring, image and vision helpers, verification, spike
tests/          Offline foundation, image, model-contract and verification checks
data/           Labeled foundation fixtures, synthetic images and scoring-policy manifest
docs/           Locked specifications, acceptance, evaluation, submission
scripts/        Existing environment/preflight helpers
```

Next: wire the tested policy module into transactional jobs/reservations/settlement, then build the event API and HTTP agent tools. Evaluation, UI and hosting follow the existing gates. The App Runner persistence conflict is recorded in [ARCHITECTURE.md](docs/ARCHITECTURE.md); it must be resolved before hosting.

## Demo boundaries and license

Vendors, rates, budget, district authority, addresses, community feed and service records are seeded fixtures; they do not establish real authority or a live operational ledger. Dispatch and settlement will be simulated. Generated images carry synthetic provenance and exact prompts. No real money or municipal work is authorized by this demo.

MIT; see [LICENSE](LICENSE). Copyright attribution is still a starter placeholder and must be completed before public submission. All assets needed for the submitted functionality must have publishable provenance and usage rights.
