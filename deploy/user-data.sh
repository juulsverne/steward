#!/bin/bash
# Steward EC2 bootstrap (cloud-init user-data). Amazon Linux 2023 x86_64, t3.small.
# Placeholders (__BUCKET__, __COMMIT__, __CF_DOMAIN__) are substituted by deploy/provision.sh.
# Log: /var/log/steward-bootstrap.log (and /var/log/cloud-init-output.log). Idempotent enough to
# re-run by hand; it never reseeds an existing database and never overwrites existing secrets.
set -euxo pipefail
exec > >(tee -a /var/log/steward-bootstrap.log) 2>&1

BUCKET="__BUCKET__"
COMMIT="__COMMIT__"
CF_DOMAIN="__CF_DOMAIN__"
export AWS_DEFAULT_REGION=us-west-2
APP=/opt/steward/app
DATA=/var/lib/steward

# 1. Packages: nginx (proxy), sqlite (backup CLI). Node is not needed: the SPA is built locally.
dnf install -y nginx sqlite tar gzip

# 2. Service account (no login shell, home under /opt/steward).
id steward >/dev/null 2>&1 || useradd --system --home-dir /opt/steward --create-home --shell /sbin/nologin steward
mkdir -p /opt/steward /etc/steward "$DATA"

# 3. Retained data volume: the one disk that is not the root disk, formatted once, mounted by UUID.
ROOT_DISK="$(lsblk -no PKNAME "$(findmnt -no SOURCE /)")"
DATA_DEV=""
for _ in $(seq 1 30); do
  for dev in $(lsblk -dnpo NAME,TYPE | awk '$2=="disk"{print $1}'); do
    if [ "$(basename "$dev")" != "$ROOT_DISK" ]; then DATA_DEV="$dev"; break; fi
  done
  [ -n "$DATA_DEV" ] && break
  sleep 2
done
test -n "$DATA_DEV"
if ! blkid -s TYPE -o value "$DATA_DEV" | grep -q .; then
  mkfs.ext4 -L steward-data "$DATA_DEV"
fi
DATA_UUID="$(blkid -s UUID -o value "$DATA_DEV")"
if ! grep -q "UUID=$DATA_UUID" /etc/fstab; then
  echo "UUID=$DATA_UUID $DATA ext4 defaults,nofail,x-systemd.device-timeout=30 0 2" >> /etc/fstab
fi
systemctl daemon-reload
mountpoint -q "$DATA" || mount "$DATA"
mountpoint -q "$DATA"
chown steward:steward "$DATA"
chmod 750 "$DATA"

# 4. Code: git archive of the exact commit, the locally built SPA, and the deploy bundle.
cd /opt/steward
aws s3 cp "s3://$BUCKET/artifacts/$COMMIT/steward-$COMMIT.tar.gz" .
aws s3 cp "s3://$BUCKET/artifacts/$COMMIT/frontend-dist-$COMMIT.tar.gz" .
aws s3 cp "s3://$BUCKET/artifacts/$COMMIT/deploy-bundle-$COMMIT.tar.gz" .
rm -rf "$APP" /opt/steward/deploy
mkdir -p "$APP"
tar -xzf "steward-$COMMIT.tar.gz" -C "$APP"
tar -xzf "frontend-dist-$COMMIT.tar.gz" -C "$APP"
tar -xzf "deploy-bundle-$COMMIT.tar.gz" -C /opt/steward
echo "$COMMIT" > "$APP/COMMIT"
test -f "$APP/frontend/dist/index.html"
chown -R steward:steward /opt/steward

# 5. uv with the locked environment (README extras: dev + web), managed CPython 3.11 under /opt.
UV_ENV=(HOME=/opt/steward UV_INSTALL_DIR=/opt/steward/bin UV_PYTHON_INSTALL_DIR=/opt/steward/python UV_CACHE_DIR=/opt/steward/cache)
sudo -u steward env "${UV_ENV[@]}" bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh -s -- --no-modify-path'
UV=/opt/steward/bin/uv
sudo -u steward env "${UV_ENV[@]}" "$UV" python install 3.11
cd "$APP"
sudo -u steward env "${UV_ENV[@]}" "$UV" sync --locked --python 3.11 --extra dev --extra web
test -x "$APP/.venv/bin/uvicorn"

# 6. Environment file with two fresh independent secrets (generated here, mode 0600, never logged).
if [ ! -f /etc/steward/steward.env ]; then
  set +x
  umask 077
  CF_DOMAIN="$CF_DOMAIN" python3 - <<'PY'
import os, secrets
origin = "https://" + os.environ["CF_DOMAIN"]
lines = [
    "STEWARD_STORE_PATH=/var/lib/steward/steward.sqlite3",
    "STEWARD_IMAGE_ROOT=/var/lib/steward/images",
    "STEWARD_FIXTURE_ROOT=/opt/steward/app/data",
    "STEWARD_FRONTEND_DIST=/opt/steward/app/frontend/dist",
    f"STEWARD_ORIGIN={origin}",
    "STEWARD_LOCAL_HTTP=false",
    "STEWARD_RUNTIME_ENABLED=true",
    f"STEWARD_SESSION_SECRET={secrets.token_hex(32)}",
    f"STEWARD_SERVICE_TOKEN={secrets.token_hex(32)}",
    "AWS_REGION=us-west-2",
    "BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6",
    "AGENT_TEMPERATURE=0.3",
    "LOG_LEVEL=INFO",
]
with open("/etc/steward/steward.env", "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")
PY
  umask 022
  set -x
fi
chown root:root /etc/steward/steward.env
chmod 600 /etc/steward/steward.env
echo "STEWARD_BACKUP_BUCKET=$BUCKET" > /etc/steward/backup.env
chmod 644 /etc/steward/backup.env

# 7. Seed the demo store once (documented seed command). Never reseed an existing database.
if [ ! -f "$DATA/steward.sqlite3" ]; then
  sudo -u steward env HOME=/opt/steward "$APP/.venv/bin/python" -m agent.seed --db "$DATA/steward.sqlite3" --data "$APP/data"
fi
test -f "$DATA/steward.sqlite3"

# 8. nginx, systemd units, backup timer.
sed "s/@CF_DOMAIN@/$CF_DOMAIN/g" /opt/steward/deploy/nginx/nginx.conf > /etc/nginx/nginx.conf
grep -q "$CF_DOMAIN" /etc/nginx/nginx.conf
nginx -t
install -m 0644 /opt/steward/deploy/systemd/steward.service /etc/systemd/system/steward.service
install -m 0644 /opt/steward/deploy/systemd/steward-backup.service /etc/systemd/system/steward-backup.service
install -m 0644 /opt/steward/deploy/systemd/steward-backup.timer /etc/systemd/system/steward-backup.timer
install -m 0755 /opt/steward/deploy/steward-backup.sh /usr/local/bin/steward-backup.sh
systemctl daemon-reload
systemctl enable --now steward.service
systemctl enable --now nginx.service
systemctl enable --now steward-backup.timer

# 9. Local readiness check through nginx with the configured host, then a completion marker.
for _ in $(seq 1 30); do
  if curl -fsS -H "Host: $CF_DOMAIN" http://127.0.0.1/health | grep -q '"ok":true'; then break; fi
  sleep 2
done
curl -fsS -H "Host: $CF_DOMAIN" http://127.0.0.1/health
date -u +%Y-%m-%dT%H:%M:%SZ > /opt/steward/bootstrap-complete
echo "steward bootstrap complete"
