#!/bin/bash
# Steward hosted judging topology: shutdown and teardown runbook. NOT run on September 14, 2026.
# Judging access must stay up through October 8, 2026 (docs/SUBMISSION.md); run nothing here
# before October 9, 2026 00:00 Pacific, and only as part of the owner-approved shutdown plan.
#
# Two levels:
#   pause    stop the instance (compute stops billing; EBS 30 GiB ~$2.40/month and the public
#            IPv4 address ~$3.65/month keep billing; CloudFront/S3 stay live)
#   destroy  final backup, then delete everything except the S3 bucket retention window
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-default}" AWS_PAGER=""
REGION=us-west-2
INSTANCE_ID=i-0b3030bce260538ea
DATA_VOLUME=vol-0f35f7df1813d0b4e
EIP_ALLOC=eipalloc-0c09e7e3ad520748a
SG_ID=sg-0d4fa4cac4804a5fe
CF_ID=E35BM8K25UCHPV
BUCKET=steward-hackathon-589354718907
MODE="${1:-}"

case "$MODE" in
pause)
  aws ec2 stop-instances --region $REGION --instance-ids $INSTANCE_ID
  aws ec2 wait instance-stopped --region $REGION --instance-ids $INSTANCE_ID
  echo "paused: start again with: aws ec2 start-instances --region $REGION --instance-ids $INSTANCE_ID (EIP stays associated)"
  ;;
destroy)
  # 1. Fence application writes and scheduled backups, then retain the final snapshot.
  # Any failure leaves the instance/volume intact with the service stopped for inspection.
  CMD="$(aws ssm send-command --region $REGION --instance-ids $INSTANCE_ID --document-name AWS-RunShellScript \
        --parameters 'commands=["set -e","systemctl stop steward","systemctl stop steward-backup.timer steward-backup.service","sudo -u steward env STEWARD_BACKUP_BUCKET='"$BUCKET"' /usr/local/bin/steward-backup.sh"]' --query Command.CommandId --output text)"
  aws ssm wait command-executed --region $REGION --command-id "$CMD" --instance-id $INSTANCE_ID
  STATUS="$(aws ssm get-command-invocation --region $REGION --command-id "$CMD" --instance-id $INSTANCE_ID --query Status --output text)"
  test "$STATUS" = Success
  OUTPUT="$(aws ssm get-command-invocation --region $REGION --command-id "$CMD" --instance-id $INSTANCE_ID --query StandardOutputContent --output text)"
  PREFIX="$(printf '%s\n' "$OUTPUT" | sed -n 's/^steward-backup: uploaded //p')"
  STAMP="${PREFIX#s3://$BUCKET/backups/}"
  STAMP="${STAMP%/}"
  [[ "$STAMP" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]
  test "$PREFIX" = "s3://$BUCKET/backups/$STAMP/"
  VERIFY_DIR="$(mktemp -d)"
  trap 'rm -rf "$VERIFY_DIR"' EXIT
  for FILE in "manifest-$STAMP.sha256" "steward-$STAMP.sqlite3" "images-$STAMP.tar.gz"; do
    aws s3 cp --region "$REGION" "$PREFIX$FILE" "$VERIFY_DIR/$FILE" --only-show-errors
  done
  # Require exactly these two local filenames before letting sha256sum read the manifest.
  MANIFEST="$VERIFY_DIR/manifest-$STAMP.sha256"
  test "$(wc -l < "$MANIFEST")" -eq 2
  grep -Ex "[0-9a-f]{64}  \\./steward-$STAMP\\.sqlite3" "$MANIFEST"
  grep -Ex "[0-9a-f]{64}  \\./images-$STAMP\\.tar\\.gz" "$MANIFEST"
  ( cd "$VERIFY_DIR" && sha256sum --check --strict "manifest-$STAMP.sha256" )
  # 2. Compute and network.
  aws ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID
  aws ec2 wait instance-terminated --region $REGION --instance-ids $INSTANCE_ID
  aws ec2 delete-volume --region $REGION --volume-id $DATA_VOLUME        # retained volume; only after the backup above is verified
  aws ec2 release-address --region $REGION --allocation-id $EIP_ALLOC
  aws ec2 delete-security-group --region $REGION --group-id $SG_ID
  # 3. CloudFront: disable, wait, delete.
  ETAG="$(aws cloudfront get-distribution-config --id $CF_ID --query ETag --output text)"
  aws cloudfront get-distribution-config --id $CF_ID --query DistributionConfig --output json \
    | python -c 'import json,sys; c=json.load(sys.stdin); c["Enabled"]=False; print(json.dumps(c))' > /tmp/cf-disabled.json
  aws cloudfront update-distribution --id $CF_ID --if-match "$ETAG" --distribution-config file:///tmp/cf-disabled.json > /dev/null
  aws cloudfront wait distribution-deployed --id $CF_ID
  ETAG="$(aws cloudfront get-distribution-config --id $CF_ID --query ETag --output text)"
  aws cloudfront delete-distribution --id $CF_ID --if-match "$ETAG"
  # 4. IAM.
  aws iam remove-role-from-instance-profile --instance-profile-name steward-instance-profile --role-name steward-instance-role
  aws iam delete-instance-profile --instance-profile-name steward-instance-profile
  aws iam delete-role-policy --role-name steward-instance-role --policy-name steward-instance-access
  aws iam detach-role-policy --role-name steward-instance-role --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  aws iam delete-role --role-name steward-instance-role
  echo "S3 bucket $BUCKET kept for the 30-day retention window (H1 plan). Delete all object versions, then the bucket, only when that window ends and the owner approves:"
  echo "  aws s3api list-object-versions --bucket $BUCKET ... | delete-objects ; aws s3api delete-bucket --region $REGION --bucket $BUCKET"
  ;;
*)
  echo "usage: deploy/teardown.sh pause|destroy" >&2
  exit 2
  ;;
esac
