# Clean-install proof, September 14, 2026

Status: run against two fresh local clones of `D:/dev/agents-for-humans`, made with no copied `.env`, `.venv`, `node_modules` or `.steward`. At clone time, `main` (`dc541a7263de75dd0aec92f25eb1a659f04c1aa9`) did **not** contain the frontend or the P1-and-later backend work — it sat 48 commits behind `codex/steward-build`, which itself had 0 commits `main` lacked, so the two branches diverged only because `main` had not been fast-forwarded yet; that gap is exactly why the literal-`main` proof below has no frontend/UI/seed/start results. The candidate actually walked here is `codex/steward-build` at `57e7e27991c3cb1abea0367cbf6fd858f63659be` ("Merge main into codex/steward-build") — the same commit the `codex/r1-freeze` worktree branched from. **The lead fast-forwarded `main` to `57e7e27991c3cb1abea0367cbf6fd858f63659be` and pushed it to origin at 15:58 CDT**, so `main` now equals the candidate; the two result sets below stay labeled by the commit each was actually run against (`57e7e27` vs the then-stale `dc541a7`) rather than by branch name.

Acceptance walk (16/16 criteria, `agent.demo` driver): see [docs/evaluations/2026-09-14-ui-walk.md](2026-09-14-ui-walk.md).

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

`.github/workflows/checks.yml` runs exactly the "CI form" commands shown above (`uv sync --locked
...` through the frontend build, now including `npm test`); it has not itself been executed on
GitHub Actions from this environment — no push was made from here.

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

`main` (`dc541a7`, its state at clone time — `main` now equals `57e7e27` after the lead's
fast-forward) separately: `uv sync --extra dev --extra web` clean (~7s), `ruff check .` all
checks passed, `pytest -q` — **129 passed in 9.16s** (matches the count already recorded in
`README.md`). `main` at that time had no `frontend/` directory, so the frontend and UI checks
above did not apply to it; nothing else in this document was re-run against pre-fast-forward
`main`. The `uv sync --locked` row above is the same install `.github/workflows/checks.yml` runs
in CI; that workflow file itself still has not been executed on GitHub Actions from here.

## R1 card gate states

- Freeze scope; record candidate commit, versions and gates — recorded above (candidate/`main`
  now both `57e7e27`); freezing scope itself is the lead's call, not this proof's.
- Fresh checkout, locked install, offline tests/lint, frontend build, fresh Bedrock access check —
  done (results table above).
- Follow only documented seed/start/reset commands; retain commands and results — done; the seed
  command used is currently documented only informally in this repo (see the full report,
  `R1-clean-install-report.md`, for the exact README wording proposed).
- Offline PR-check workflow (Ruff, pytest, then locked `npm ci`/typecheck/test/build) — done
  (`.github/workflows/checks.yml`); still not run on GitHub Actions from this environment.

## Known limits of this proof

- One Bedrock preflight call was made in total (against the candidate), per the bounded-call
  instruction; the full demo driver (`agent.demo`) and the vision spike were intentionally not run
  here — another worker's live run covers that acceptance path today.
- The Board confirmation above is an interactive check (screenshot taken during the session, not
  saved to the repository); it was not captured as a Playwright artifact under `docs/evaluations/ui/`.
- `main` was checked for its own install/lint/test health only, at its pre-fast-forward commit
  `dc541a7`; the frontend/UI/dispatch gap that existed then was closed by the lead's fast-forward
  to `57e7e27` at 15:58 CDT (recorded above), not by anything in this document.
