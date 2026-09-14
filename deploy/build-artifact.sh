#!/bin/bash
# Package the exact commit for the instance and upload it to the private artifact prefix.
#   steward-<commit>.tar.gz        git archive of the commit (no .git, no ignored files)
#   frontend-dist-<commit>.tar.gz  the SPA built in an isolated archive of that commit
#   deploy-bundle-<commit>.tar.gz  that commit's deploy/ directory
# Usage (from the repository root; npm and Node required):
#   deploy/build-artifact.sh <commit> [bucket] [--prepare-only]
set -euo pipefail
COMMIT="$(git rev-parse --verify "${1:?commit required}^{commit}")"
BUCKET="${2:-steward-hackathon-589354718907}"
OUT="${ARTIFACT_OUT:-$(mktemp -d)}"
MODE="${3:-}"
if [ -n "$MODE" ] && [ "$MODE" != --prepare-only ]; then exit 2; fi
# Do not export AWS_REGION: an `aws login` profile refreshes its token in the profile's own region
# (see README "Run the live Tier 1A checks"); pass --region per command instead.
export AWS_PROFILE="${AWS_PROFILE:-default}" AWS_PAGER=""
REGION=us-west-2

mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git archive --format=tar.gz -o "$OUT/steward-$COMMIT.tar.gz" "$COMMIT"
tar -xzf "$OUT/steward-$COMMIT.tar.gz" -C "$WORK"
test -d "$WORK/deploy"
test -f "$WORK/frontend/package-lock.json"
( cd "$WORK/frontend" && npm ci && npm run build )
test -f "$WORK/frontend/dist/index.html"
tar -czf "$OUT/frontend-dist-$COMMIT.tar.gz" -C "$WORK" frontend/dist
tar -czf "$OUT/deploy-bundle-$COMMIT.tar.gz" -C "$WORK" deploy
( cd "$OUT" && sha256sum "steward-$COMMIT.tar.gz" "frontend-dist-$COMMIT.tar.gz" "deploy-bundle-$COMMIT.tar.gz" | tee "artifacts-$COMMIT.sha256" )
if [ "$MODE" != --prepare-only ]; then
  for FILE in "steward-$COMMIT.tar.gz" "frontend-dist-$COMMIT.tar.gz" "deploy-bundle-$COMMIT.tar.gz" "artifacts-$COMMIT.sha256"; do
    aws s3 cp --region "$REGION" "$OUT/$FILE" "s3://$BUCKET/artifacts/$COMMIT/$FILE" --only-show-errors
  done
fi
