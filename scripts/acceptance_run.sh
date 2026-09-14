#!/usr/bin/env bash
# Live B13 acceptance run on an isolated store and port.
#   bash scripts/acceptance_run.sh <tag> [port] [compare-artifact]
# Seeds .steward/b13/<tag>.sqlite3, starts the API with the runtime dispatcher on the
# given port, drives python -m agent.demo against it, then stops that server. Logs and
# the acceptance artifact are kept under .steward/b13/. Requires a valid AWS session
# (run `uv run --no-sync python -m agent.bedrock_check` first) and STEWARD_SERVICE_TOKEN
# in .env. Never touches another server's port or the default .steward/steward.sqlite3.
set -u
tag="${1:?usage: acceptance_run.sh <tag> [port] [compare-artifact]}"
port="${2:-8001}"
compare="${3:-}"
root=".steward/b13"
db="$root/$tag.sqlite3"
out="$root/$tag-acceptance.json"
origin="http://127.0.0.1:$port"
mkdir -p "$root"

health() {
  uv run --no-sync python -c "import urllib.request,sys
try: sys.exit(0 if urllib.request.urlopen('$origin/health', timeout=2).status == 200 else 1)
except Exception: sys.exit(1)" >/dev/null 2>&1
}

if health; then
  echo "port $port already serves /health; refusing to run against a foreign server" >&2
  exit 3
fi

uv run --no-sync python -m agent.seed --db "$db" --reset > "$root/$tag-seed.log" 2>&1 \
  || { echo "seed failed" >&2; cat "$root/$tag-seed.log" >&2; exit 2; }

STEWARD_RUNTIME_ENABLED=true STEWARD_STORE_PATH="$db" STEWARD_IMAGE_ROOT="$root/images" \
STEWARD_ORIGIN="$origin" \
  uv run --no-sync uvicorn agent.server:app --host 127.0.0.1 --port "$port" --no-proxy-headers \
  > "$root/$tag-server.log" 2>&1 &
server=$!

for _ in $(seq 1 40); do health && break; sleep 1; done
if ! health; then
  echo "server on $port never became healthy" >&2
  taskkill //PID "$server" //T //F >/dev/null 2>&1 || kill "$server" 2>/dev/null
  exit 4
fi

args=(--base-url "$origin" --out "$out" --wait-seconds 180)
[ -n "$compare" ] && args+=(--compare "$compare")
uv run --no-sync python -m agent.demo "${args[@]}" > "$root/$tag-demo.log" 2>&1
code=$?
echo "exit=$code" >> "$root/$tag-demo.log"

taskkill //PID "$server" //T //F >/dev/null 2>&1 || kill "$server" 2>/dev/null
for _ in $(seq 1 15); do health || break; sleep 1; done
echo "$tag finished exit=$code artifact=$out"
exit $code
