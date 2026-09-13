# Mac Mini development

The checkout is `/Users/cara/dev/agents-for-humans`. From Windows:

```powershell
ssh -t mac-mini-tailscale 'bash /Users/cara/dev/agents-for-humans/scripts/mac-session.sh'
```

Run `codex` or `claude` inside that terminal. Detach with Ctrl+B, then D;
reconnect with the same SSH command. The tmux session survives SSH disconnects,
and its `keepawake` window prevents idle system sleep while the session exists.
It does not restart work after a Mac reboot. Stop it with
`tmux kill-session -t agents-for-humans` when finished.

## AWS authentication

Codex and Claude are already signed in on the Mac. AWS needs a separate login:

```bash
aws login --remote --profile agents-for-humans
export AWS_PROFILE=agents-for-humans AWS_REGION=us-west-2
aws sts get-caller-identity
```

Open the URL on your laptop and paste the returned authorization code into the
Mac terminal. Credentials stay on the Mac. AWS login can expire; unattended AWS
calls may then require another login. Bedrock inference access still requires
verification after authentication.

## Installed and checked on 2026-09-11

- Codex 0.153.4 and Claude Code 2.1.207; both report authenticated.
- AWS Core 1.1.0 and AWS Agents 1.0.0 plugins enabled in both clients.
- AWS Core, AWS Knowledge, and Strands MCP connections passed Claude's health check.
- Strands MCP 0.2.9 and AWS MCP proxy 1.6.6 installed locally.
- AWS CLI 2.36.43 and AgentCore CLI 0.29.0 installed.
- Python dependencies installed from `uv.lock`, including dev, web, and AgentCore extras.
- Two pytest tests and Ruff passed on the Mac.
- tmux shell and sleep inhibitor remained running after SSH disconnected.

Run checks with `uv run --no-sync pytest` and `uv run --no-sync ruff check .`.

## Source state

The initial transfer preserved Git history at commit
`042ec6f58609f72cd1e841f0f77a3a1d9571a7cb` and the PC's uncommitted changes
to `.gitignore`, `pyproject.toml`, and `uv.lock`. Mac text files use LF line endings.
The remote-session script and this guide were added on both machines.
Private research, caches, virtual environments, and credentials were not copied.

There is no GitHub remote configured. This was a one-time setup; subsequent PC
and Mac edits do not automatically synchronize. Configure a shared Git remote
before working across both checkouts regularly.
