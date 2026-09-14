# deploy/ — hosted judging topology (H1 decision, H4)

Everything here reproduces the single-instance deployment recorded in [docs/HOSTING_DECISION.md](../docs/HOSTING_DECISION.md) and proven in [docs/evaluations/2026-09-14-hosted-acceptance.md](../docs/evaluations/2026-09-14-hosted-acceptance.md). No secrets live in this directory.

| File | Purpose |
|---|---|
| `provision.sh` | The exact AWS CLI commands run on September 14, 2026 (bucket, instance role, security group, Elastic IP, CloudFront, artifacts, instance), with the resulting resource IDs in comments. A runbook, not an idempotent installer |
| `build-artifact.sh` | `git archive` of the commit + locally built `frontend/dist` + this directory, uploaded to `s3://<bucket>/artifacts/<commit>/` |
| `user-data.sh` | Instance bootstrap (cloud-init): packages, data volume by UUID at `/var/lib/steward`, code, `uv sync --locked`, secrets, seed once, nginx, systemd units, backup timer |
| `cloudfront-distribution.json` | Distribution config template (HTTP-only custom origin, CachingDisabled + AllViewer, redirect-to-HTTPS, 60 s origin timeout) |
| `iam/instance-trust-policy.json`, `iam/instance-policy.json` | Instance role trust and inline access policy (`__BUCKET__`/`__ACCOUNT__` placeholders) |
| `s3-bucket-policy.json` | TLS-only bucket policy |
| `nginx/nginx.conf` | Port-80 reverse proxy to uvicorn; `@CF_DOMAIN@` is pinned as `Host` |
| `systemd/steward.service` | uvicorn under the non-root `steward` user; fails readiness if the data volume or database is missing |
| `systemd/steward-backup.service`, `systemd/steward-backup.timer`, `steward-backup.sh` | Consistent SQLite + images backup to S3 every 6 hours |
| `steward.env.example` | Environment file template with placeholders only |
| `teardown.sh` | `pause` (stop instance) / `destroy` (final backup, delete everything except the bucket retention window). Not before October 9, 2026 |

Operate the instance without SSH through Session Manager, for example:

```
aws ssm send-command --region us-west-2 --instance-ids i-0b3030bce260538ea \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["systemctl status steward --no-pager","journalctl -u steward -n 50 --no-pager"]'
```

Do not export `AWS_REGION` when using an `aws login` profile whose configured region differs; pass `--region us-west-2` per command (the README explains the token-refresh reason).
