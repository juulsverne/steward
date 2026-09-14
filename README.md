# Steward

**Autonomous neighborhood operations. Steward manages reality, not tickets.**

Steward turns scattered community signals into verified physical resolutions. It investigates evidence, reconciles contradictory service records, dispatches approved supplemental providers within explicit policy, and verifies completion before simulated settlement. It brings neighborhood operators the exceptions that need human judgment.

Built for the **Good Neighbor Agents** track of the AWS Agents for Humans Hackathon. One Strands agent on Amazon Bedrock chooses what to do next through typed HTTP tools; a FastAPI service owns policy, scores, prices, budget, verification and settlement in SQLite; a trusted Bedrock vision call inspects photos and returns findings that code scores. The design is in [ARCHITECTURE.md](docs/ARCHITECTURE.md) and [architecture.png](architecture.png).

## Status, September 14, 2026

**Done and verified locally.** The full couch journey runs end to end with real Bedrock inference: the sixteen-step acceptance passed through the API in two independently seeded live runs (Sonnet text and vision, `us-west-2`; B13 receipt in [BUILD_PLAN.md](docs/BUILD_PLAN.md#b13-completion-receipt--september-14)), and the same journey was driven again on September 14 and read back on the operations UI — Board, Issue Detail, Operator Inbox, Crew Form and Resident intake — with screenshots per criterion in [the UI walk](docs/evaluations/2026-09-14-ui-walk.md). The offline suite is 703 tests; the twelve-comparison vision check is 12/12 ([vision spike](docs/evaluations/2026-09-13-vision-spike.md)); the model screen is in [MODEL_SELECTION.md](docs/MODEL_SELECTION.md).

**Not done.** The twenty-two-scenario internal evaluation ([EVALUATION.md](docs/EVALUATION.md)) has not run, so no evaluation counts are published. Nothing is hosted: AgentCore Runtime, Observability, Gateway and a public judging URL are planned, not built; the hosting recommendation in [HOSTING_DECISION.md](docs/HOSTING_DECISION.md) awaits the owner's decision. Judging access is therefore clone-and-run with your own AWS Bedrock access ([SUBMISSION.md](docs/SUBMISSION.md)). Clean-install proof from a fresh clone is being recorded separately (R1); the run below was verified on the developers' machines.

**What the demo is.** A driven live run: the agent and vision calls are real Bedrock calls; the district, authority, budget, providers, addresses, reporter identities, community feed and the 311 record are seeded fixtures; the five photos are synthetic images with published prompts ([provenance](data/images/PROVENANCE.md)); dispatch and settlement are simulated. No real money or municipal work is authorized. Labels travel with the records and are shown on the screens.

The competition proof is one couch: wait at evidence score 65; corroborate at 85; dispute a completed service record when newer physical evidence disagrees; dispatch an authorized $72 cleanup; block payment at verification score 90; resume after operator-requested rework; verify at 100; simulate payment and resolve. [DEMO.md](docs/DEMO.md) lists the sixteen criteria and the recording script.

## Run it yourself

You need: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22 or newer with npm, the AWS CLI, and an AWS account with Amazon Bedrock model access to `global.anthropic.claude-sonnet-4-6` (a cross-region inference profile; the client binds to `us-west-2`). Each full run makes five agent invocations plus the photo inspections (about 574k input tokens in the recorded run); you pay for that inference. The recorded runs were made on Windows 11 in Git Bash; nothing in the commands is Windows-specific.

### 1. Install

```bash
git clone <this repository> && cd agents-for-humans
uv sync --locked --extra dev --extra web
cd frontend && npm install && npm run build && cd ..
```

The frontend build lands in `frontend/dist`, which the API serves at `/`.

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

```bash
uv run --no-sync python -m agent.seed --db .steward/steward.sqlite3
uv run --no-sync uvicorn agent.server:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

The seed writes the first labeled feed signal and photo (a 65-point candidate), the uncredited completed 311 fixture, three fictional providers and a $500.00 simulated budget, plus one pending invocation. With `STEWARD_RUNTIME_ENABLED=true` the API's startup scan runs that invocation immediately: one real Bedrock call, and the issue becomes MONITORING at 65. Open `http://localhost:8000/`, pick a persona in the header (Operator, a vendor's Crew, or Resident; it is a labeled sandbox, not authentication), and watch the Board and Issue Detail.

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
uv run --no-sync pytest -q          # 703 passed on the B13 code
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
- [Hosting decision (recommendation, not built)](docs/HOSTING_DECISION.md)
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
tests/              Offline tests (703): scoring, store, policy, API, tools, runtime, recovery
data/               Seeded fixtures, five synthetic images with provenance, policy manifest
docs/               Specifications, decisions, dated evidence (docs/README.md is the index)
docs/evaluations/   Vision spike report, model-screen export, UI walk and screenshots
scripts/            Acceptance runner, link checker, OpenAPI/model-screen exporters, preflight
```

Next: record the video from [DEMO.md](docs/DEMO.md), publish the repository and save the submission (owner actions in [SUBMISSION.md](docs/SUBMISSION.md)); then, after the deadline, the P8 evaluation, the hosting decision and the hosted judging URL (H1–H6). Product thresholds, exclusions and labels do not change to make any of that easier.

## Demo boundaries and license

Vendors, rates, budget, district authority, addresses, community feed and service records are seeded fixtures; they do not establish real authority or a live operational ledger. Dispatch and settlement are simulated. The images are synthetic and carry their exact prompts. No real money or municipal work is authorized by this demo.

MIT; see [LICENSE](LICENSE). The repository incorporates the generic Strands/Bedrock starter it was scaffolded from (its first commit); everything else was written for this project. All assets needed for the submitted functionality have documented provenance ([data/README.md](data/README.md)).
