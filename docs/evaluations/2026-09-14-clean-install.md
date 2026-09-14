# Clean-install proof, September 14, 2026

Status: run against two fresh local clones of `D:/dev/agents-for-humans`, made with no copied `.env`, `.venv`, `node_modules` or `.steward`. `main` (`dc541a7263de75dd0aec92f25eb1a659f04c1aa9`) does **not** contain the frontend or the P1-and-later backend work: it sits 48 commits behind `codex/steward-build`, which itself has 0 commits `main` lacks, so the two branches diverge only because `main` has not been fast-forwarded yet. The candidate actually walked here is `codex/steward-build` at `57e7e27991c3cb1abea0367cbf6fd858f63659be` ("Merge main into codex/steward-build") — the same commit the `codex/r1-freeze` worktree branched from. `main` was separately installed and checked (below) so its own state is on record.

Toolchain found on the build machine: `uv 0.11.2`, system `Python 3.11.9`, `node v24.12.0`, `npm 11.6.2`, `git 2.48.1.windows.1`.

## Setup used (candidate, `57e7e27`)

```
git clone D:/dev/agents-for-humans clean-install-candidate && cd clean-install-candidate
git checkout 57e7e27991c3cb1abea0367cbf6fd858f63659be

uv sync --extra dev --extra web                     # README form; 10s
uv sync --locked --extra dev --extra web             # CI form; also clean, 115 resolved/92 checked

uv run --no-sync ruff check .                        # All checks passed!
uv run --no-sync pytest -q                            # see result below

npm ci --prefix frontend                              # 140 packages, 0 vulnerabilities, ~7s
npm --prefix frontend run typecheck                    # tsc --noEmit, clean
npm --prefix frontend test                             # vitest run
npm --prefix frontend run build                        # tsc --noEmit && vite build -> frontend/dist

cp .env.example .env   # AWS_PROFILE=default (only profile configured on this machine);
                        # STEWARD_SESSION_SECRET / STEWARD_SERVICE_TOKEN generated fresh with
                        # secrets.token_hex(32); STEWARD_STORE_PATH=.steward/r1-clean-install.sqlite3;
                        # STEWARD_ORIGIN=http://127.0.0.1:8090

uv run --no-sync python -m agent.seed --db .steward/r1-clean-install.sqlite3 --reset
STEWARD_STORE_PATH=.steward/r1-clean-install.sqlite3 STEWARD_ORIGIN=http://127.0.0.1:8090 \
STEWARD_RUNTIME_ENABLED=false \
  uv run --no-sync uvicorn agent.server:app --host 127.0.0.1 --port 8090 --no-proxy-headers

uv run --no-sync python -m agent.bedrock_check --out .steward/r1-bedrock-check.json
```

Port 8000 and 5173 were already in use by another worker's run; a first attempt on port 8010 also
collided with an unrelated process already listening there (`HOST_FORBIDDEN` responses from that
foreign server, then a WinError 10048 bind failure) — resolved by checking `netstat -ano` and
moving to port 8090, which bound cleanly. The server was stopped after the checks below.

## Results

| Check | Result |
|---|---|
| `uv sync --extra dev --extra web` (candidate) | Clean, ~10s |
| `uv sync --locked --extra dev --extra web` (candidate, CI form) | Clean — 115 resolved, 92 checked |
| `ruff check .` (candidate) | All checks passed |
| `pytest -q` (candidate, full suite) | **706 passed**, 2 warnings, in 1066.25s (0:17:46) — both warnings are dependency deprecation notices, not failures |
| `npm ci` (frontend) | 140 packages, 0 vulnerabilities, ~7s; `EBADENGINE` warning for `jsdom@30.0.1` (wants node `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0`; machine has `24.12.0`) — did not fail the install |
| `npm run typecheck` (frontend) | Clean |
| `npm test` (frontend) | 13 files / 57 tests passed, 36.5s |
| `npm run build` (frontend) | Clean; `frontend/dist` produced (467 kB JS / 141 kB gzip, 32 kB CSS) |
| Seed | `uv run --no-sync python -m agent.seed --db .steward/r1-clean-install.sqlite3 --reset` → `baseline` scenario, `seed_version south-loop-demo-b3`, fixture manifest `86b7f711a397c8404b3fa11e7a9ba47d3a3972f46e27b02d22746b8df4d59bed`, one seeded signal at score 65 |
| Start + `/health` | `uv run --no-sync uvicorn agent.server:app --host 127.0.0.1 --port 8090` → `GET /health` → `{"outcome":"OK","reason_code":null,"data":{"ok":true},...}` |
| `/` (built SPA) | Serves the built `frontend/dist/index.html` (`<title>Steward</title>`) |
| Board renders seeded data | Confirmed interactively: persona gate → "District operator (seeded)" → Operations Board shows "South Loop Demo District", policy `south-loop-v3`, Watching 1 / Active 0 / Resolved 0, Budget available $500.00 ($0 reserved/spent), and a Leaflet map marker near the seeded address |
| Bedrock preflight (fresh, live) | `uv run --no-sync python -m agent.bedrock_check --out .steward/r1-bedrock-check.json` → `mode: live`, `model_id global.anthropic.claude-sonnet-4-6`, region `us-west-2`, `passed: true`, tool `current_time` called, `stop_reason end_turn`, latency 2.68s, 1885 total tokens |

`main` (`dc541a7`) separately: `uv sync --extra dev --extra web` clean (~7s), `ruff check .` all
checks passed, `pytest -q` — **129 passed in 9.16s** (matches the count already recorded in
`README.md`). `main` has no `frontend/` directory, so the frontend and UI checks above do not
apply to it; nothing else in this document was re-run against `main`.

## Known limits of this proof

- One Bedrock preflight call was made in total (against the candidate), per the bounded-call
  instruction; the full demo driver (`agent.demo`) and the vision spike were intentionally not run
  here — another worker's live run covers that acceptance path today.
- The Board confirmation above is an interactive check (screenshot taken during the session, not
  saved to the repository); it was not captured as a Playwright artifact under `docs/evaluations/ui/`.
- `main` was checked for its own install/lint/test health only; its frontend/UI/dispatch gap
  against the candidate is a branch-state fact recorded here, not something this document resolves.
