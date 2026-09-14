#!/bin/bash
# Consistent Steward backup: SQLite online backup (.backup) + integrity check + image tarball,
# uploaded under s3://$STEWARD_BACKUP_BUCKET/backups/<UTC stamp>/ with a SHA-256 manifest.
# Runs as the steward user from steward-backup.timer; STEWARD_BACKUP_BUCKET comes from /etc/steward/backup.env.
set -euo pipefail

DATA_DIR=/var/lib/steward
DB="$DATA_DIR/steward.sqlite3"
BUCKET="${STEWARD_BACKUP_BUCKET:?STEWARD_BACKUP_BUCKET is required}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d "$DATA_DIR/.backup.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

test -f "$DB"
sqlite3 "$DB" ".backup '$WORK/steward-$STAMP.sqlite3'"
sqlite3 "$WORK/steward-$STAMP.sqlite3" "PRAGMA integrity_check;" | grep -qx ok
if [ -d "$DATA_DIR/images" ]; then
  tar -C "$DATA_DIR" -czf "$WORK/images-$STAMP.tar.gz" images
fi
( cd "$WORK" && sha256sum ./* > "manifest-$STAMP.sha256" )
aws s3 cp "$WORK/" "s3://$BUCKET/backups/$STAMP/" --recursive --only-show-errors
echo "steward-backup: uploaded s3://$BUCKET/backups/$STAMP/"
