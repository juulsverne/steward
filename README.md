# Agents for Humans

> An AI agent built with the [Strands Agents SDK](https://strandsagents.com) for the
> [AWS Agents for Humans Hackathon](https://agentsforhumans.devpost.com/).

**TODO: replace this section with your pitch — what the agent does, who it's for,
and why it matters.** Those three points are explicitly what the judges score on
Presentation, so write them here first and reuse the wording in your demo video.

- **Track:** Everyday Agents / Professional Agents / Good Neighbor Agents *(pick one)*
- **What it does:** …
- **Who it's for:** …
- **Why it matters:** …

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). A diagram is a **required**
submission artifact.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (or plain `pip` + `venv`)
- An AWS account with **Amazon Bedrock model access enabled** for Claude Sonnet
  in your chosen region
- AWS CLI v2, configured (`aws configure --profile agents-for-humans`)

## Setup

```bash
# 1. Install dependencies (creates .venv automatically)
uv sync --extra dev --extra web

# 2. Configure credentials
cp .env.example .env        # then edit .env
aws configure --profile agents-for-humans

# 3. Verify AWS + Bedrock access before you build anything
powershell -ExecutionPolicy Bypass -File scriptspreflight.ps1
```

## Run

```bash
# Interactive terminal agent
uv run agent

# Web server (streams over SSE) — the basis for a live demo link
uv run uvicorn agent.server:app --reload
curl -N -X POST localhost:8000/ask -H 'content-type: application/json' \
  -d '{"prompt":"what time is it?"}'
```

## Test

```bash
uv run pytest
uv run ruff check .
```

## Project layout

```
src/agent/
  config.py       Environment-driven settings
  core.py         Agent construction — SYSTEM_PROMPT lives here
  cli.py          Interactive terminal entrypoint
  server.py       FastAPI + SSE streaming, for a live demo
  tools/          Tools the agent can call
    example.py    Worked example of the @tool pattern — replace with yours
tests/            pytest suite
docs/             Architecture diagram + submission checklist
scripts/          AWS preflight check
```

## Deploying to Amazon Bedrock AgentCore (optional)

Not required, but the rules state it *"is a smart architectural choice and will
strengthen your Technical Implementation score."*

```bash
uv sync --extra agentcore
uv run agentcore configure --entrypoint src/agent/core.py
uv run agentcore launch
```

## License

MIT — see [LICENSE](LICENSE). *(The rules require an MIT or Apache license visible
in the repo's About section — set this in the GitHub sidebar too.)*
