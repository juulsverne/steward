#!/bin/bash
# Package the exact commit for the instance and upload it to the private artifact prefix.
#   steward-<commit>.tar.gz        git archive of the commit (no .git, no ignored files)
#   frontend-dist-<commit>.tar.gz  the SPA built locally from that commit (frontend/dist)
#   deploy-bundle-<commit>.tar.gz  this deploy/ directory (units, nginx, backup script)
# Usage (from the repository root, after `cd frontend && npm ci && npm run build`):
#   deploy/build-artifact.sh <commit> [bucket]
set -euo pipefail
COMMIT="${1:?commit (short SHA) required}"
BUCKET="${2:-steward-hackathon-589354718907}"
OUT="${ARTIFACT_OUT:-$(mktemp -d)}"
# Do not export AWS_REGION: an `aws login` profile refreshes its token in the profile's own region
# (see README "Run the live Tier 1A checks"); pass --region per command instead.
export AWS_PROFILE="${AWS_PROFILE:-default}" AWS_PAGER=""
REGION=us-west-2

git rev-parse --verify "$COMMIT^{commit}" >/dev/null
test -f frontend/dist/index.html
git archive --format=tar.gz -o "$OUT/steward-$COMMIT.tar.gz" "$COMMIT"
tar -czf "$OUT/frontend-dist-$COMMIT.tar.gz" frontend/dist
tar -czf "$OUT/deploy-bundle-$COMMIT.tar.gz" deploy
( cd "$OUT" && sha256sum "steward-$COMMIT.tar.gz" "frontend-dist-$COMMIT.tar.gz" "deploy-bundle-$COMMIT.tar.gz" | tee "artifacts-$COMMIT.sha256" )
aws s3 cp --region "$REGION" "$OUT/" "s3://$BUCKET/artifacts/$COMMIT/" --recursive --only-show-errors
aws s3 ls --region "$REGION" "s3://$BUCKET/artifacts/$COMMIT/"
