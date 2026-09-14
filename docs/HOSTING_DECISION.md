# Durable hosting decision — approved and built

Status: **Approved by the owner on September 14, 2026 (15:50 CDT) and provisioned the same afternoon.** The public judging URL is **https://d1uke66gfefpu4.cloudfront.net**, serving the exact candidate commit `57e7e27`. Hosted acceptance evidence (driver run, restart and reboot proofs) is in [the hosted acceptance record](evaluations/2026-09-14-hosted-acceptance.md); the provisioning commands, bootstrap, units and runbooks are under [`deploy/`](../deploy/README.md). Instance *replacement* with the retained volume is documented below but **not yet exercised**.

## Decision

Host the public app on **one Amazon EC2 `t3.small` (Amazon Linux 2023, `us-west-2a`)** with a **separate retained encrypted 10 GiB gp3 data volume** holding SQLite and the evidence image bytes, a **private versioned S3 bucket** for code artifacts and backups, an **instance role** (no long-lived keys), and a **CloudFront distribution** as the HTTPS front. FastAPI on the instance remains the only policy and transaction owner; the Strands agent runs in-process (`STEWARD_RUNTIME_ENABLED=true`), exactly the configuration that passed B13 and the UI walk. App Runner is not used (it stopped accepting new customers on April 30, 2026, and its filesystem is ephemeral; see the comparison at the end).

Approved real AWS spend ceiling: **$50 total incremental** for deployment plus judging through October 8, 2026. The seeded $500 cleanup ledger is entirely simulated and unrelated to AWS spend.

### Rulings by the lead (recorded September 14)

- Evidence bytes stay on the retained EBS data volume next to SQLite (one durability owner); S3 holds artifacts and backups. The per-upload S3 object design from the researched recommendation is **not** built: it needs product-code changes (B3 image store) that could not be reviewed before the deadline. Cost if wrong: losing the volume loses evidence written since the last 6-hour backup; that exposure is documented here.
- The agent runs in-process on the instance. AgentCore Runtime, Observability and Gateway (H2, H3, H5) remain open tier-3 items and are **not deployed**; AgentCore is optional under the hackathon rules.
- Bedrock permissions on `*` resources for the instance role; narrowing to the exact inference-profile and model ARNs is a hardening item.
- No domain purchase; the CloudFront default hostname is the public URL.

## Topology as built (resource IDs)

| Component | Value |
|---|---|
| Account / region | `589354718907` / `us-west-2` (default VPC `vpc-0766ae2ae8d7b658b`, subnet `subnet-01cc4e95cc7cfe51f`, AZ `us-west-2a`) |
| Instance | `i-0b3030bce260538ea`, `t3.small`, AMI `ami-03db3415e6524c5d2` (`al2023-ami-2023.12.20260909.0-kernel-6.18-x86_64`), CPU credits `standard`, IMDSv2 required (hop limit 1), private IP `172.31.34.174` |
| Root volume | `vol-02a4b2ce8cc0c4829`, 20 GiB gp3, encrypted, DeleteOnTermination=true |
| **Data volume** | `vol-0f35f7df1813d0b4e`, 10 GiB gp3, encrypted, **DeleteOnTermination=false**, ext4 label `steward-data`, mounted by UUID at `/var/lib/steward` (`nvme1n1`), tags `Name=steward-data`, `Role=retained-data-volume` |
| Elastic IP | `eipalloc-0c09e7e3ad520748a` = `35.80.131.214` (`eipassoc-0f11f2ca21c8a9630`); public DNS `ec2-35-80-131-214.us-west-2.compute.amazonaws.com` is the CloudFront origin |
| Security group | `sg-0d4fa4cac4804a5fe` `steward-web`: inbound TCP 80 **only from prefix list `pl-82a045eb`** (`com.amazonaws.global.cloudfront.origin-facing`); no port 22; outbound all. A direct request to the EIP times out |
| Instance role | `steward-instance-role` / profile `steward-instance-profile`: `AmazonSSMManagedInstanceCore`; inline `steward-instance-access` = Bedrock `InvokeModel*`/`Converse*` on `*`, `s3:GetObject` on `artifacts/*`, `s3:PutObject` on `backups/*`, prefix-scoped `ListBucket`, CloudWatch Logs on `/steward/service` ([policy](../deploy/iam/instance-policy.json)) |
| S3 bucket | `steward-hackathon-589354718907`: private (Block Public Access on), versioned, SSE-S3, bucket-owner-enforced, TLS-only policy; prefixes `artifacts/57e7e27/` (code tarball, built SPA, deploy bundle, SHA-256 list) and `backups/` |
| CloudFront | `E35BM8K25UCHPV` → `d1uke66gfefpu4.cloudfront.net`; HTTP-only custom origin, viewer protocol redirect-to-HTTPS, all seven methods, managed `CachingDisabled` (`4135ea2d-…`) + `AllViewer` origin request policy (`216adef6-…`, forwards all headers including `Authorization`, cookies and query strings), origin read timeout 60 s, default certificate, PriceClass_100 |
| Runtime | `uv sync --locked --python 3.11 --extra dev --extra web` under `/opt/steward/app` (uv-managed CPython 3.11 in `/opt/steward/python`); non-root `steward` user; systemd `steward.service` runs `uvicorn agent.server:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=*`; nginx on :80 proxies to it and pins `Host` to the CloudFront hostname (the app's allowed-host check derives from `STEWARD_ORIGIN`); `client_max_body_size 64m` |
| Configuration | `/etc/steward/steward.env` (root, 0600): store `/var/lib/steward/steward.sqlite3`, images `/var/lib/steward/images`, fixtures `/opt/steward/app/data`, SPA `/opt/steward/app/frontend/dist`, `STEWARD_ORIGIN=https://d1uke66gfefpu4.cloudfront.net`, `STEWARD_LOCAL_HTTP=false`, `STEWARD_RUNTIME_ENABLED=true`, `AWS_REGION=us-west-2`, `BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6` (no role overrides); two `secrets.token_hex(32)` values generated on the instance by the bootstrap, never committed or logged ([template](../deploy/steward.env.example)) |
| Artifacts | Code = `git archive` of `57e7e27`; the SPA was **built locally** (`npm ci && npm run build`, Node 24) and shipped as `frontend-dist-57e7e27.tar.gz`, so Node is not installed on the instance |
| Backups | `steward-backup.timer` (15 min after boot, then every 6 h): `sqlite3 .backup` + `PRAGMA integrity_check` + `tar` of images + SHA-256 manifest → `s3://steward-hackathon-589354718907/backups/<UTC stamp>/` |
| Logs | Stay on the instance (`journalctl -u steward`, `/var/log/nginx/*`, `/var/log/steward-bootstrap.log`); administration through Session Manager / `aws ssm send-command`. CloudWatch shipping is not configured (the role already permits one log group) |

Cookies are `__Host-steward-demo` (Secure, path `/`), which the browser only accepts over HTTPS; the persona-selection round trip through CloudFront was verified. The in-process runner reaches its own API at `STEWARD_ORIGIN`, so tool traffic loops through CloudFront to the instance (the acceptance run took 2.5 minutes end to end).

## Boundaries

- One authoritative state owner: FastAPI + SQLite on the data volume, with per-request connections and `BEGIN IMMEDIATE` transactions; no proxy, edge function or second service computes gates, prices or scores. nginx and CloudFront are transport only; CloudFront caching is disabled and every response carries `Cache-Control: no-store`.
- Image bytes live beside the database on the same retained volume (one durability owner). The dispatcher recovers persisted `PENDING`/expired-lease invocations on startup, so a restart mid-invocation resumes from the saved record.
- The public entry point accepts anonymous traffic only for `/health` and the SPA; every `/api` read needs a persona cookie or the service token and every mutation needs the same-origin browser intent headers. Judges never see an AWS console or credential.
- The instance role has no EC2, IAM, or bucket-administration rights; teardown and volume reattachment are human actions with the owner's login.
- The demo remains a labeled persona sandbox with simulated dispatch and settlement.

## Cost estimate (idle + active, September 14 21:00 UTC → October 9 07:00 UTC = 586 h)

| Item | Basis | Estimate |
|---|---:|---:|
| EC2 `t3.small` on-demand | 586 h × $0.0208 | $12.19 |
| Public IPv4 (Elastic IP attached) | 586 h × $0.005 | $2.93 |
| EBS gp3, 30 GiB | 30 × $0.08/GiB-month × 586/730 | $1.93 |
| S3 (artifacts 11 MB + four ~5 MB backups/day + requests) | < 1 GiB-month | ~$0.10 |
| CloudFront, SSM, EBS snapshots (none), CloudWatch (none) | free tier / unused | $0 |
| **Infrastructure through October 8** | ≈ $0.70/day | **≈ $17.20** |
| Bedrock (Sonnet 4.6 text + vision, per use) | the hosted acceptance run made 29 model cycles across 5 invocations; at the MODEL_SELECTION planning rate (~$0.02–0.04 per cycle with images) one full couch walk ≈ $1 | $1 per full run; the $15 allowance covers roughly a dozen judge walks |

Standard CPU credits cannot generate surplus charges; the instance idles at a few percent CPU. Stopping the instance saves only the compute line; EBS and the public IPv4 address keep billing until released. This stays inside the approved $50 ceiling (the H1 split was $30 hosting/retention, $15 model use, $5 contingency). AWS Budgets alerts at $25/$35/$45 are recommended but were not created (a Budget is outside the approved resource list; the owner can add one in the console).

## Recovery and restore

**Process restart** (`systemctl restart steward`) and **full reboot** (`aws ec2 reboot-instances`) were both exercised on September 14: the service returned within seconds/30 s, the data volume remounted by UUID, and the resolved case, PAID job, single 7,200-cent payment, budget and all four image digests were unchanged ([evidence](evaluations/2026-09-14-hosted-acceptance.md)).

**Instance replacement (documented, not exercised):**

1. Fence the old writer: `aws ec2 stop-instances --instance-ids i-0b3030bce260538ea` and wait for `stopped` (systemd stops uvicorn cleanly; SQLite has no WAL to lose).
2. `aws ec2 detach-volume --volume-id vol-0f35f7df1813d0b4e`; wait for `available`.
3. Launch a replacement in **the same AZ (`us-west-2a`)** with the `run-instances` line from [`deploy/provision.sh`](../deploy/provision.sh) minus the `/dev/xvdf` mapping, same role/security group/user-data; once `running`, `aws ec2 attach-volume --volume-id vol-0f35f7df1813d0b4e --instance-id <new> --device /dev/xvdf`. The bootstrap waits up to 60 s for the disk, finds an existing filesystem, mounts it by UUID, **does not reseed** (the database exists) and generates fresh web secrets on the new root volume (existing browser sessions become invalid; the service token changes).
4. `aws ec2 associate-address --allocation-id eipalloc-0c09e7e3ad520748a --instance-id <new> --allow-reassociation`; CloudFront keeps pointing at the same EC2 public DNS name.
5. Verify `https://d1uke66gfefpu4.cloudfront.net/health`, the Board and the resolved case, then terminate the old instance (its root volume is deleted; the data volume is already detached).

**Restore from S3 backup** (volume loss or corruption): create an empty encrypted 10 GiB gp3 volume in the target AZ, attach and let the bootstrap format/mount it, stop `steward.service`, download the newest `backups/<stamp>/` set, verify the manifest (`sha256sum -c`), `sqlite3 restored.sqlite3 "PRAGMA integrity_check"`, place it at `/var/lib/steward/steward.sqlite3` and untar `images/` beside it (owner `steward`), start the service. RPO is the last successful 6-hour backup; RTO is manual, about 30 minutes, unmeasured.

## Shutdown and teardown

Judging access must stay up through October 8, 2026; nothing below runs before October 9 at 00:00 Pacific and only as part of the owner-approved plan. [`deploy/teardown.sh pause`](../deploy/teardown.sh) stops the instance (compute stops billing; EBS and the public IP continue). `deploy/teardown.sh destroy` runs a final backup, terminates the instance, deletes the data volume, releases the Elastic IP, deletes the security group, disables and deletes the CloudFront distribution, and removes the instance role/profile; the S3 bucket is kept for the 30-day retention window and deleted (all object versions first) only with owner approval. The exact commands are in that script.

## Hardening list (open)

1. Narrow the instance role's Bedrock statement from `*` to the `global.anthropic.claude-sonnet-4-6` inference profile and its regional model ARNs.
2. Exercise the instance-replacement procedure above once (it also proves the corrected bootstrap end to end on a fresh root volume; the first instance needed an in-place nginx `Host` fix, see the acceptance record).
3. Ship `journalctl -u steward` to the `/steward/service` log group (permission exists; agent not installed) and add disk/backup-age alarms.
4. Add an S3 lifecycle rule expiring `backups/` object versions after 30 days, and AWS Budgets alerts at $25/$35/$45.
5. Consider a CloudFront rate limit / WAF if judges' traffic ever looks abusive; today the API's own authentication and idempotency gates are the only throttle.
6. Run the second independently seeded acceptance pass with `--compare` on the hosted URL (criterion 16), then reseed to the resolved state for judges.
7. Rotate the web secrets after judging (they are regenerated automatically on instance replacement).

## Comparison that led here (researched September 13, condensed)

| Concern | Retain App Runner for the public app | Stateful EC2 host (chosen) |
|---|---|---|
| Support | App Runner stopped accepting new customers on April 30, 2026; account eligibility unknown; [filesystem is ephemeral](https://docs.aws.amazon.com/apprunner/latest/dg/develop.html) | EC2/EBS/S3/CloudFront available in Oregon and provisioned in this account |
| Policy/transaction owner | Would have to move the policy-bearing API to EC2 anyway (App Runner as a stateless proxy), or migrate SQLite to RDS PostgreSQL and requalify all money/concurrency tests | FastAPI + SQLite unchanged; local semantics preserved |
| Durability | None on App Runner itself; every durable byte on EC2/EBS/S3 | Retained volume survives instance replacement; S3 backups every 6 h |
| Cost | Chosen stack **plus** ~$5–6/month App Runner | ≈ $0.70/day, ≈ $17 through October 8 |
| Code impact | Proxy timeouts, header allowlists, origin auth, upload forwarding | Configuration only: persistent paths, HTTPS origin, secrets, proxy headers; **no backend source change was needed** |

S3 synchronization of a live SQLite file cannot provide a transaction owner ([SQLite WAL documentation](https://www.sqlite.org/wal.html)); the retained-EBS design keeps the database local to its single writer.
