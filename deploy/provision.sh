#!/bin/bash
# Steward hosted judging topology (H1 approved decision, H4): exact AWS CLI commands as run on
# September 14, 2026 from Git Bash on Windows with `--profile default` (account 589354718907).
#
# Topology: default VPC public subnet, one security group (80 from the CloudFront origin-facing
# prefix list only, no 22), Amazon Linux 2023 t3.small (standard credits, IMDSv2 required),
# 20 GiB gp3 encrypted root + separate 10 GiB gp3 encrypted data volume (DeleteOnTermination=false),
# Elastic IP, instance role/profile (SSM, Bedrock invoke on *, S3 artifacts read / backups write,
# one CloudWatch log group), private versioned SSE-S3 TLS-only bucket, CloudFront HTTPS front
# (HTTP-only custom origin, CachingDisabled + AllViewer, redirect-to-https, 60 s origin timeout).
#
# Resource IDs from the real run are in comments; rerunning creates a second copy of everything,
# so treat this as a runbook, not an idempotent installer. Do not export AWS_REGION with an
# `aws login` profile (its token refresh needs the profile's own region); use --region per call.
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-default}" AWS_PAGER=""
REGION=us-west-2
ACCOUNT=589354718907
BUCKET=steward-hackathon-589354718907
COMMIT="${COMMIT:-57e7e27}"
VPC_ID=vpc-0766ae2ae8d7b658b            # default VPC
SUBNET_ID=subnet-01cc4e95cc7cfe51f      # default subnet, us-west-2a (the data volume lives in this AZ)
CF_PREFIX_LIST=pl-82a045eb              # com.amazonaws.global.cloudfront.origin-facing
AMI_ID="$(aws ssm get-parameter --region $REGION --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)"   # ami-03db3415e6524c5d2 on 2026-09-14
TAGS_KV='Key=Project,Value=steward Key=Owner,Value=hackathon'
cd "$(dirname "$0")/.."

# ---------------------------------------------------------------- 1. S3 bucket (private, versioned, SSE-S3, TLS-only)
aws s3api create-bucket --region $REGION --bucket $BUCKET --create-bucket-configuration LocationConstraint=$REGION --object-ownership BucketOwnerEnforced
aws s3api put-public-access-block --region $REGION --bucket $BUCKET --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --region $REGION --bucket $BUCKET --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --region $REGION --bucket $BUCKET --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":false}]}'
sed "s/__BUCKET__/$BUCKET/g" deploy/s3-bucket-policy.json > /tmp/bucket-policy.json
aws s3api put-bucket-policy --region $REGION --bucket $BUCKET --policy file:///tmp/bucket-policy.json
aws s3api put-bucket-tagging --region $REGION --bucket $BUCKET --tagging 'TagSet=[{Key=Project,Value=steward},{Key=Owner,Value=hackathon}]'

# ---------------------------------------------------------------- 2. Instance role + profile
aws iam create-role --role-name steward-instance-role --assume-role-policy-document file://deploy/iam/instance-trust-policy.json --tags $TAGS_KV
aws iam attach-role-policy --role-name steward-instance-role --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
sed -e "s/__BUCKET__/$BUCKET/g" -e "s/__ACCOUNT__/$ACCOUNT/g" deploy/iam/instance-policy.json > /tmp/instance-policy.json
aws iam put-role-policy --role-name steward-instance-role --policy-name steward-instance-access --policy-document file:///tmp/instance-policy.json
aws iam create-instance-profile --instance-profile-name steward-instance-profile --tags $TAGS_KV
aws iam add-role-to-instance-profile --instance-profile-name steward-instance-profile --role-name steward-instance-role

# ---------------------------------------------------------------- 3. Security group: 80 from CloudFront only, no 22
SG_ID="$(aws ec2 create-security-group --region $REGION --group-name steward-web --description "Steward: HTTP 80 from CloudFront origin-facing prefix list only" --vpc-id $VPC_ID --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=steward},{Key=Owner,Value=hackathon},{Key=Name,Value=steward-web}]' --query GroupId --output text)"   # sg-0d4fa4cac4804a5fe
aws ec2 authorize-security-group-ingress --region $REGION --group-id "$SG_ID" --ip-permissions "IpProtocol=tcp,FromPort=80,ToPort=80,PrefixListIds=[{PrefixListId=$CF_PREFIX_LIST,Description=CloudFront origin-facing}]"

# ---------------------------------------------------------------- 4. Elastic IP (its EC2 public DNS name is the CloudFront origin)
EIP_JSON="$(aws ec2 allocate-address --region $REGION --domain vpc --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Project,Value=steward},{Key=Owner,Value=hackathon},{Key=Name,Value=steward-web}]' --output json)"   # eipalloc-0c09e7e3ad520748a / 35.80.131.214
EIP_ALLOC="$(echo "$EIP_JSON" | python -c 'import json,sys;print(json.load(sys.stdin)["AllocationId"])')"
EIP_IP="$(echo "$EIP_JSON" | python -c 'import json,sys;print(json.load(sys.stdin)["PublicIp"])')"
ORIGIN_DOMAIN="ec2-${EIP_IP//./-}.$REGION.compute.amazonaws.com"

# ---------------------------------------------------------------- 5. CloudFront distribution (deploys in the background, ~5-10 min)
sed -e "s/__CALLER_REFERENCE__/steward-h4-$(date +%s)/" -e "s/__ORIGIN_DOMAIN__/$ORIGIN_DOMAIN/" deploy/cloudfront-distribution.json > /tmp/cf-config.json
CF_JSON="$(aws cloudfront create-distribution-with-tags --distribution-config-with-tags "{\"DistributionConfig\": $(cat /tmp/cf-config.json), \"Tags\": {\"Items\": [{\"Key\":\"Project\",\"Value\":\"steward\"},{\"Key\":\"Owner\",\"Value\":\"hackathon\"}]}}" --output json)"   # E35BM8K25UCHPV / d1uke66gfefpu4.cloudfront.net
CF_DOMAIN="$(echo "$CF_JSON" | python -c 'import json,sys;print(json.load(sys.stdin)["Distribution"]["DomainName"])')"

# ---------------------------------------------------------------- 6. Artifacts (git archive of the exact commit + locally built SPA + deploy bundle)
# Prerequisite: cd frontend && npm ci && npm run build && cd ..
ARTIFACT_OUT=.steward/artifacts deploy/build-artifact.sh "$COMMIT" "$BUCKET"

# ---------------------------------------------------------------- 7. Instance (root 20 GiB gp3 encrypted; data 10 GiB gp3 encrypted, retained)
sed -e "s/__BUCKET__/$BUCKET/g" -e "s/__COMMIT__/$COMMIT/g" -e "s/__CF_DOMAIN__/$CF_DOMAIN/g" deploy/user-data.sh > .steward/artifacts/user-data-rendered.sh
INSTANCE_ID="$(aws ec2 run-instances --region $REGION \
  --image-id "$AMI_ID" --instance-type t3.small \
  --subnet-id $SUBNET_ID --security-group-ids "$SG_ID" \
  --iam-instance-profile Name=steward-instance-profile \
  --credit-specification CpuCredits=standard \
  --metadata-options HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1 \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3","Encrypted":true,"DeleteOnTermination":true}},{"DeviceName":"/dev/xvdf","Ebs":{"VolumeSize":10,"VolumeType":"gp3","Encrypted":true,"DeleteOnTermination":false}}]' \
  --user-data file://.steward/artifacts/user-data-rendered.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Project,Value=steward},{Key=Owner,Value=hackathon},{Key=Name,Value=steward-web}]' 'ResourceType=volume,Tags=[{Key=Project,Value=steward},{Key=Owner,Value=hackathon},{Key=Name,Value=steward-web}]' \
  --query 'Instances[0].InstanceId' --output text)"   # i-0b3030bce260538ea (root vol-02a4b2ce8cc0c4829, data vol-0f35f7df1813d0b4e)
aws ec2 wait instance-running --region $REGION --instance-ids "$INSTANCE_ID"
aws ec2 associate-address --region $REGION --instance-id "$INSTANCE_ID" --allocation-id "$EIP_ALLOC"   # eipassoc-0f11f2ca21c8a9630
DATA_VOL="$(aws ec2 describe-volumes --region $REGION --filters "Name=attachment.instance-id,Values=$INSTANCE_ID" "Name=attachment.device,Values=/dev/xvdf" --query 'Volumes[0].VolumeId' --output text)"
aws ec2 create-tags --region $REGION --resources "$DATA_VOL" --tags Key=Name,Value=steward-data Key=Role,Value=retained-data-volume

# ---------------------------------------------------------------- 8. Wait for bootstrap (marker written by user-data) and CloudFront
echo "instance=$INSTANCE_ID eip=$EIP_IP cloudfront=https://$CF_DOMAIN"
echo "Poll: aws ssm send-command --region $REGION --instance-ids $INSTANCE_ID --document-name AWS-RunShellScript --parameters 'commands=[\"cat /opt/steward/bootstrap-complete\",\"tail -n 20 /var/log/steward-bootstrap.log\"]'"
echo "Then: curl -sS https://$CF_DOMAIN/health"
