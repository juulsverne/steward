# Steward

**Autonomous neighborhood operations. Steward manages reality, not tickets.**

Steward turns scattered community signals into verified physical resolutions. It investigates evidence, reconciles contradictory service records, dispatches approved supplemental providers within explicit policy, and verifies completion before simulated settlement. It brings neighborhood operators the exceptions that need human judgment.

Built for the **Good Neighbor Agents** track of the AWS Agents for Humans Hackathon. One Strands agent on Amazon Bedrock chooses what to do next through typed HTTP tools; a FastAPI service owns policy, scores, prices, budget, verification and settlement in SQLite; a trusted Bedrock vision call inspects photos and returns findings that code scores. The design is in [ARCHITECTURE.md](docs/ARCHITECTURE.md) and [architecture.png](architecture.png).

## Status, September 14, 2026

**Try it:** [Open Steward](https://d1uke66gfefpu4.cloudfront.net), select **District operator (seeded)**, and open **1530 S Michigan Ave**. Inspect the before/after evidence, failed middle proof, policy results and simulated settlement. The hosted case is already completed; use Inbox's handled items and the assigned crew persona to explore its history. No AWS account is needed to view the hosted sandbox. For a fresh run, follow the setup below and the [step-by-step testing guide](docs/JUDGING.md).

**Done and verified locally.** The full couch journey runs end to end with real Bedrock inference: the sixteen-step acceptance passed through the API in two independently seeded live runs (Sonnet text and vision, `us-west-2`; B13 receipt in [BUILD_PLAN.md](docs/BUILD_PLAN.md#b13-completion-receipt--september-14)), and the same journey was driven again on September 14 and read back on the operations UI — Board, Issue Detail, Operator Inbox, Crew Form and Resident intake — with screenshots per criterion in [the UI walk](docs/evaluations/2026-09-14-ui-walk.md). The clean-install candidate `57e7e27` passed 706 offline tests ([R1 receipt](docs/evaluations/2026-09-14-clean-install.md)); the twelve-comparison vision check is 12/12 ([vision spike](docs/evaluations/2026-09-13-vision-spike.md)); the model screen is in [MODEL_SELECTION.md](docs/MODEL_SELECTION.md).

**Hosted.** Hosted for judging on EC2 + CloudFront (deployed September 14; acceptance evidence: docs/evaluations/2026-09-14-hosted-acceptance.md). Public URL: `https://d1uke66gfefpu4.cloudfront.net` — one EC2 `t3.small` in `us-west-2` with a retained EBS volume for SQLite and images, private S3 backups, nginx + uvicorn and the in-process Strands runtime, behind CloudFront; the decision is in [HOSTING_DECISION.md](docs/HOSTING_DECISION.md). The hosted candidate `57e7e27` passed criteria 1–15 and retained its resolved state across service restart and instance reboot. Hosted criterion 16, instance replacement and backup restoration remain unverified. The reviewed UI from `2f31548` is now deployed; backend code and dependencies remain identical to `57e7e27`. See the [UI release receipt](docs/evaluations/2026-09-14-ui-release.md). AgentCore Runtime, Observability and Gateway are **not deployed**.

**Not done.** The twenty-two-scenario internal evaluation ([EVALUATION.md](docs/EVALUATION.md)) has not run, so no evaluation counts are published. The [clean-install proof](docs/evaluations/2026-09-14-clean-install.md) is integrated. P7 remains open: driver-based acceptance and screenshots do not prove every step was performed through the browser. Judging access is the hosted URL, with clone-and-run using your own AWS Bedrock access as the fallback ([SUBMISSION.md](docs/SUBMISSION.md)).

**What the demo is.** A driven live run: the agent and vision calls are real Bedrock calls; the district, authority, budget, providers, addresses, reporter identities, community feed and the 311 record are seeded fixtures; the five photos are synthetic images with published prompts ([provenance](data/images/PROVENANCE.md)); dispatch and settlement are simulated. No real money or municipal work is authorized. Labels travel with the records and are shown on the screens.

The competition proof is one couch: wait at evidence score 65; corroborate at 85; dispute a completed service record when newer physical evidence disagrees; dispatch an authorized $72 cleanup; block payment at verification score 90; resume after operator-requested rework; verify at 100; simulate payment and resolve. [DEMO.md](docs/DEMO.md) lists the sixteen criteria and the recording script.

## Run it yourself

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js **22.22.2+ in the 22.x line or 24.15+ in the 24.x line** with npm, the AWS CLI, and your own AWS account with Amazon Bedrock access to `global.anthropic.claude-sonnet-4-6`. The client uses `us-west-2`. Live runs incur inference costs; viewing the hosted case does not require your AWS credentials. Commands below use Bash (Git Bash on Windows, or a macOS/Linux terminal). Start the API in one terminal and run the driver in a second terminal from the repository root.

### 1. Install

```bash
git clone https://github.com/juulsverne/steward.git && cd steward
uv sync --locked --extra dev --extra web
cd frontend && npm ci && npm run build && cd ..
mkdir -p .steward
cp .env.example .env
```

`npm ci` is the locked, reproducible install (`frontend/package-lock.json` is committed). The frontend build lands in `frontend/dist`, which the API serves at `/`.

### 2. Configure

Copy `.env.example` to `.env` (it is gitignored) and set:

| Setting | Value |
|---|---|
| `AWS_PROFILE`, `AWS_REGION` | your authenticated profile and `us-west-2` |
| `BEDROCK_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` (leave `BEDROCK_TEXT_MODEL_ID` and `BEDROCK_VISION_MODEL_ID` blank; both fall back to it) |
| `STEWARD_SESSION_SECRET`, `STEWARD_SERVICE_TOKEN` | two different values, each from `python -c "import secrets; print(secrets.token_hex(32))"`; the API refuses blank, equal or placeholder values and never generates them for you |
| `STEWARD_STORE_PATH` | `.steward/steward.sqlite3` (create the `.steward` directory yourself) |
| `STEWARD_ORIGIN`, `STEWARD_LOCAL_HTTP` | `http://localhost:8000`, `true` |
| `STEWARD_RUNTIME_ENABLED` | `true` to run the agent; `false` keeps the API a read/write sandbox with no Bedrock calls |
| `STEWARD_FRONTEND_DIST` | `frontend/dist` |

Authenticate (`aws login --profile <profile>`, or `aws configure` with long-lived keys), then prove the same credential path the server uses:

```bash
uv run --no-sync python -m agent.bedrock_check
```

It must print a successful tool result and final model reply. `aws login` issues short-lived tokens that botocore refreshes through the sign-in endpoint of the profile's own region; Steward resolves credentials there and binds only the Bedrock client to `AWS_REGION` (`agent.aws_session.region_session`). If the preflight reports `CreateOAuth2Token ... authorization grant is invalid`, run `aws login` again. Keep credentials out of source control.

### 3. Seed and start

Seed a fresh named database before the first start; without it the Board is empty (no issue, $0 budget, no marker):

```bash
uv run --no-sync python -m agent.seed --db .steward/steward.sqlite3
uv run --no-sync uvicorn agent.server:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

The seed writes the first labeled feed signal and photo (a 65-point candidate), the uncredited completed 311 fixture, three fictional providers and a $500.00 simulated budget, plus one pending invocation. With `STEWARD_RUNTIME_ENABLED=true` the API's startup scan runs that invocation immediately: one agent invocation (which may make multiple model calls), and the issue becomes MONITORING at 65. Open `http://localhost:8000/`, pick a persona in the header (Operator, a vendor's Crew, or Resident; it is a labeled sandbox, not authentication), and watch the Board and Issue Detail.

### 4. Run the couch journey

With the API running, drive the remaining resident, crew and operator actions through the same HTTP API the screens use:

```bash
uv run --no-sync python -m agent.demo --base-url http://localhost:8000 --out .steward/run.json --wait-seconds 240
```

It takes about three minutes, prints one line per criterion, and writes every API response and agent trace to the artifact. Refresh Issue Detail, the Inbox, the Crew Form and the Board as it goes; the end state is a RESOLVED issue, one PAID job at $72.00 (simulated), $428.00 available. Run one Bedrock workload at a time.

The same journey can be walked by hand: the Report form submits the second resident report, the Crew Form accepts, checks in (a button fills the dispatch coordinates) and uploads `data/images/middle.jpg` then `data/images/after.jpg`, and the Inbox offers **Request completion** on the failed-proof exception. The verified end-to-end evidence today is the driver; the manual path is covered by the frontend tests and the walk's read-only screens, not by a recorded hand-driven run.

### 5. Reset and rerun

Stop the API, then reset the same marked store and start again:

```bash
uv run --no-sync python -m agent.seed --db .steward/steward.sqlite3 --reset
```

Reset refuses unmarked files and never touches `.env`. For an isolated, reproducible acceptance run on a private port (seed, serve on 8001, drive, stop, keep logs under `.steward/b13/`), use `bash scripts/acceptance_run.sh <tag> 8001`; pass a previous artifact as the third argument to close criterion 16 by comparison. Details in [DEMO.md](docs/DEMO.md#live-acceptance-procedure-b13-api-gate).

### If something fails

| Symptom | What it means | Do |
|---|---|---|
| API exits at startup naming a `STEWARD_*` setting | a secret is blank, equal to the other, or a placeholder; or `.steward` does not exist | fix `.env`, create the directory, restart |
| `bedrock_check` fails with `authorization grant is invalid` | the `aws login` token expired | `aws login` again, rerun the preflight |
| `AccessDeniedException` from Bedrock | the account lacks model access for the profile ID | enable the model in the Bedrock console for `us-west-2` |
| An invocation ends `AGENT_EXECUTION_FAILED` with `ThrottlingException` | a second Bedrock workload ran at the same time; SDK retries are disabled on purpose | stop the other workload, reset, rerun |
| The driver stops on `TOOL_REQUEST_FAILED` or times out | a transient tool/network failure inside the live run (seen once on September 14) | reset and rerun; do not edit the database |
| `port 8000 already serves /health` from the acceptance script | another server owns the port | choose another port or stop it |
| Screens load but every page shows the persona notice | no persona cookie yet | pick a persona in the header |
| Issue Detail stays at 65 with no decision | the runtime is disabled | set `STEWARD_RUNTIME_ENABLED=true` and restart |

Interrupted runs are safe to resume: pending work, claims and effects are journaled, and a restarted API resumes or fails them without duplicating a job, reservation or payment ([API.md](docs/API.md#durable-processing-and-recovery-b12)).

## Offline checks

No AWS credentials are needed for these:

```bash
uv run --no-sync pytest -q
uv run --no-sync ruff check .
uv run --no-sync python scripts/check_docs.py
uv run --no-sync python -m agent.foundation --db .steward/foundation.sqlite3   # 65/65/85/100 scoring harness
cd frontend && npm run typecheck && npm test
```

The foundation harness prints **OFFLINE FOUNDATION CHECK** and proves scoring and persistence only; it is not the agent. `python -m agent.vision_spike --images data/images --repeats 3` reruns the live twelve-comparison vision check (costs inference). Development with hot reload: add `STEWARD_DEVELOPMENT_ORIGINS=http://localhost:5173` to `.env`, start the API, then `npm run dev` in `frontend/` and open `http://localhost:5173`. After changing API models run `uv run --no-sync python scripts/export_openapi.py` and `npm run types`.

## Build documents

- [Documentation index: what each document is and when to read it](docs/README.md)
- [Product requirements: goals, users, stories, agent behavior, data/API and quality](docs/PRD.md)
- [Architecture, data, tools, policy, and deployment contract](docs/ARCHITECTURE.md)
- [API identity boundary, endpoints, tool transport, recovery](docs/API.md)
- [Build guide: complete scope, task order, ownership, verification receipts](docs/BUILD_PLAN.md)
- [Sixteen acceptance criteria and the recording script](docs/DEMO.md)
- [Internal evaluation protocol (not yet run)](docs/EVALUATION.md)
- [Model choices: each step, costs, live comparison and qualification gates](docs/MODEL_SELECTION.md)
- [Hosting decision (EC2 + CloudFront, deployed September 14)](docs/HOSTING_DECISION.md)
- [Submission checklist and judging access](docs/SUBMISSION.md)
- [Post-competition company vision](docs/VISION.md)
- [Coding-agent instructions](AGENTS.md)

## Project layout

```text
src/agent/          One flat package: config, aws_session, server (FastAPI), store (SQLite),
                      policy, scoring, verification, vision, tools/ (HTTP tools and Strands
                      session), runtime (invocations, claims, journal), seed, demo (driver),
                      cli, foundation, bedrock_check, vision_spike
frontend/           React/Vite screens: Board, Issue Detail, Inbox, Crew Form, Resident intake
tests/              Offline tests: scoring, store, policy, API, tools, runtime, recovery
data/               Seeded fixtures, five synthetic images with provenance, policy manifest
docs/               Specifications, decisions, dated evidence (docs/README.md is the index)
docs/evaluations/   Vision spike report, model-screen export, UI walk and screenshots
scripts/            Acceptance runner, link checker, OpenAPI/model-screen exporters, preflight
```

Next: record the video from [DEMO.md](docs/DEMO.md), publish the final reviewed source and save the submission (owner actions in [SUBMISSION.md](docs/SUBMISSION.md)); keep the hosted instance up through October 8; freeze the submitted code and materials through the winner announcement. P8 evaluation and AgentCore work remain future scope. Product thresholds, exclusions and labels do not change to make any of that easier.

## Demo boundaries and license

Vendors, rates, budget, district authority, addresses, community feed and service records are seeded fixtures; they do not establish real authority or a live operational ledger. Dispatch and settlement are simulated. The images are synthetic and carry their exact prompts. No real money or municipal work is authorized by this demo.

MIT; see [LICENSE](LICENSE). The repository incorporates the generic Strands/Bedrock starter it was scaffolded from (its first commit); everything else was written for this project. All assets needed for the submitted functionality have documented provenance ([data/README.md](data/README.md)).
