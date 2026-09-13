#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"
repo="$(cd "$(dirname "$0")/.." && pwd)"
session=agents-for-humans
if ! tmux has-session -t "=$session" 2>/dev/null; then
  tmux new-session -d -s "$session" -n work -c "$repo" \
    -e AWS_PROFILE=agents-for-humans -e AWS_REGION=us-west-2
  tmux new-window -d -t "$session" -n keepawake /usr/bin/caffeinate -i
fi
if [[ "${1:-}" == --detach ]]; then
  tmux list-windows -t "=$session"
else
  exec tmux attach-session -t "=$session"
fi
