# Steward

**Autonomous neighborhood operations. Steward manages reality, not tickets.**

Steward turns scattered community signals into verified physical resolutions. It investigates evidence, reconciles contradictory service records, dispatches approved supplemental providers within explicit policy, and verifies completion before simulated settlement. It brings neighborhood operators the exceptions that need human judgment.

Built for the **Good Neighbor Agents** track of the AWS Agents for Humans Hackathon.

## Status

The hackathon scope is locked in [PRD.md](docs/PRD.md). This public **Steward OSS** reference implementation is being built to prove one couch resolution; the future private commercial platform is described separately in [VISION.md](docs/VISION.md).

Implemented: the generic Strands/Bedrock starter; SQLite signals, issue links, scoring and audit events; the persisted 65 → 65 → 85 → 100 service-record/dispute sequence; five labeled synthetic images; image fingerprints; strict verification gates; a bounded Strands preflight and single-call Bedrock vision spike runner. The full Steward agent workflow now runs end to end through the API: on September 14 the sixteen-step couch acceptance passed live with real Sonnet text and vision in two independently seeded runs (see [DEMO.md](docs/DEMO.md) and the B13 receipt in [BUILD_PLAN.md](docs/BUILD_PLAN.md)). The operations UI is **not implemented yet**. After AWS login, the live Strands round trip and all twelve vision comparisons passed on September 13. Tier 1B has started with a pure policy module and seeded district/vendor/address fixtures; policy is not yet wired into mutation endpoints. See [vision readiness](docs/VISION_SPIKE.md) and [document review](docs/DOCUMENT_REVIEW.md).

The competition proof is one couch: wait at evidence score 65; corroborate at 85; dispute a completed service record when newer physical evidence disagrees; dispatch an authorized $72 cleanup; block payment at verification score 90; resume after operator-requested rework; verify at 100; simulate payment and resolve.

## Build documents

- [Product requirements: goals, users, stories, agent behavior, data/API and quality](docs/PRD.md)
- [Architecture, data, tools, policy, and deployment contract](docs/ARCHITECTURE.md)
- [Build guide: complete scope, task order, coding-agent models, ownership and verification](docs/BUILD_PLAN.md)
- [Sixteen acceptance criteria and demo script](docs/DEMO.md)
- [Internal evaluation protocol](docs/EVALUATION.md)
- [Model choices: each step, costs, live comparison and qualification gates](docs/MODEL_SELECTION.md)
- [Submission checklist](docs/SUBMISSION.md)
- [Post-competition company vision](docs/VISION.md)
- [Coding-agent instructions](AGENTS.md)

Deadline: Monday, September 14, 2026 at **5 PM Pacific / 7 PM Chicago**. Internal submission target is two hours earlier. One Strands agent, evaluated Bedrock models, deterministic policy. Sonnet remains the current default; cheaper text candidates passed a basic tool screen, but the tested cheaper vision candidates failed the partial-cleanup case. Separate role configuration is implemented; domain qualification remains open. Build order: core proof through the API, then the React surfaces and evaluation, then AgentCore Runtime with App Runner hosting, then optional flags.

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

## Run the operations UI

Build once, then the API serves it at `/`:

    cd frontend && npm install && npm run build && cd ..
    uv run --no-sync uvicorn agent.server:app --port 8000

The built UI is served only when the API is started from the environment (`ApiSettings.from_env`, the default for `agent.server:app`) or when `frontend_dist` is set explicitly; constructing `ApiSettings` directly (as tests and scripts do) never mounts it unless asked.

Development with hot reload runs Vite on port 5173 and proxies `/api` to the API. Add `STEWARD_DEVELOPMENT_ORIGINS=http://localhost:5173` to `.env`, start the API as above, then in `frontend/` run `npm run dev` and open `http://localhost:5173` (not 127.0.0.1). After changing API models run `uv run --no-sync python scripts/export_openapi.py` and `npm run types`.

## Run the offline foundation

From the repository root, after installing the dependencies:

```bash
uv run python -m agent.foundation --db .steward/foundation.sqlite3
```

No AWS credentials are needed for this command. It prints **OFFLINE FOUNDATION CHECK**, stores the first report at 65 points, records the seeded COMPLETED service record as a pending conflict (still 65), reopens SQLite, adds an independent report to reach 85, and confirms the official-status dispute to reach 100. The issue stays CANDIDATE: a score is not a fabricated agent decision. An existing destination is refused; use a fresh database filename to repeat.

The first image digest identifies the actual synthetic `data/images/before.jpg`; geocode accuracy and source observations remain **seeded metadata**. The harness performs no photo analysis or live geocoding. See [fixture provenance and limitations](data/README.md). This harness does not satisfy the sixteen-step live-agent acceptance run.

Verified September 13: `uv run --no-sync pytest -q` — **129 passed**; `uv run --no-sync ruff check .` — **All checks passed**. Tests cover service-record/persistence scoring, source independence, restart/retry and transactional behavior, image reuse, strict verification, model-response validation, and spike failure gates. The foundation rerun retained six events and totals 65/65/85/100. This used the existing local Python environment; clean-install acceptance remains open.

## Run the live Tier 1A checks

Use your authenticated AWS profile (`aws login --profile default` refreshes the PC profile used for the verified run). Set `AWS_PROFILE` to that profile if a different value is in your environment or `.env`; never overwrite existing configuration blindly.

`aws login` issues fifteen-minute access tokens that botocore refreshes through the sign-in endpoint of the session that resolved them. A session pinned to the Bedrock region (`us-west-2`) asks the wrong sign-in endpoint and fails with `CreateOAuth2Token ... authorization grant is invalid`, even though `aws sts get-caller-identity` still succeeds from the CLI. Steward therefore resolves credentials with the profile's own region and only binds the Bedrock client to `AWS_REGION` (`agent.aws_session.region_session`); the preflight below uses the same path, so a passing preflight now proves the refresh path the server uses. If the preflight itself reports that error, run `aws login` again. Then run:

```powershell
uv run --no-sync python -m agent.bedrock_check
# Continue only after the round-trip check passes:
uv run --no-sync python -m agent.vision_spike --images data/images --repeats 3
```

The preflight requires a successful tool result and final model reply. The spike requires twelve expected outcomes, including partial score 90, complete score 100, and scene/reuse rejection. The preflight resolves `BEDROCK_TEXT_MODEL_ID`; the spike resolves `BEDROCK_VISION_MODEL_ID`; each falls back to `BEDROCK_MODEL_ID` and then Sonnet. Leave both role overrides blank for the default run. For candidate comparisons, use the role-explicit commands in [MODEL_SELECTION.md](docs/MODEL_SELECTION.md#7-reproduce-the-current-screen). Results and failures are retained under `.steward/`; [VISION_SPIKE.md](docs/VISION_SPIKE.md) reports the Sonnet qualification, and [MODEL_SELECTION.md](docs/MODEL_SELECTION.md) records the later multi-model component screen. These commands do not dispatch, pay, or resolve an issue.

## Project layout

```text
src/agent/      Strands starter, store/scoring, image and vision helpers, verification, spike
tests/          Offline foundation, image, model-contract and verification checks
data/           Labeled foundation fixtures, synthetic images and scoring-policy manifest
docs/           Locked specifications, acceptance, evaluation, submission
scripts/        Existing environment/preflight helpers
```

Next: verify the foundation, prepare H1's early storage/cost recommendation, use M0's completed role-setting boundary and build B1's complete records, then follow the backend/agent tasks through the API gate. UI, evaluation and hosting follow the recorded dependencies. [BUILD_PLAN section 12](docs/BUILD_PLAN.md#12-handoff-and-delegation-how-someone-else-builds-from-this-guide) assigns coding sub-agents, models, shared ownership and review gates. Hosted-storage implementation remains conditional on the recorded architecture decision and deployment authorization.

## Demo boundaries and license

Vendors, rates, budget, district authority, addresses, community feed and service records are seeded fixtures; they do not establish real authority or a live operational ledger. Dispatch and settlement will be simulated. Generated images carry synthetic provenance and exact prompts. No real money or municipal work is authorized by this demo.

MIT; see [LICENSE](LICENSE). Copyright attribution is still a starter placeholder and must be completed before public submission. All assets needed for the submitted functionality must have publishable provenance and usage rights.
