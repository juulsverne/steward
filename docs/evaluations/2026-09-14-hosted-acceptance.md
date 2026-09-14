# Hosted acceptance, September 14, 2026

Status: **the public HTTPS URL passed the sixteen-step couch acceptance driver (criteria 1–15 in one run; criterion 16 needs a second independently seeded run and was not attempted) and retained the resolved case, the PAID job, exactly one 7,200-cent simulated payment and every image byte across a `systemctl restart steward` and a full instance reboot.** Instance replacement was not exercised.

- URL: **https://d1uke66gfefpu4.cloudfront.net** (CloudFront `E35BM8K25UCHPV` → EC2 `i-0b3030bce260538ea`, Elastic IP `35.80.131.214`, `us-west-2a`)
- Commit served: `57e7e27` (`git archive` shipped as `s3://steward-hackathon-589354718907/artifacts/57e7e27/steward-57e7e27.tar.gz`, SHA-256 `cd84ed8a…`; SPA built locally from the same commit, `frontend-dist-57e7e27.tar.gz` SHA-256 `29d9bacb…`)
- Models: `global.anthropic.claude-sonnet-4-6` for text and vision through the instance role (no access keys); policy `south-loop-v3`; fixture scenario `baseline`
- Topology and resource IDs: [HOSTING_DECISION.md](../HOSTING_DECISION.md); commands: [`deploy/provision.sh`](../../deploy/provision.sh), bootstrap [`deploy/user-data.sh`](../../deploy/user-data.sh)

All times are UTC on September 14 (CDT = UTC−5).

## Timeline

| Time | Event |
|---|---|
| 20:56–20:58 | S3 bucket, instance role/profile, security group (80 from `pl-82a045eb` only) and Elastic IP created; CloudFront distribution created (status `InProgress`) |
| 21:00:08 | Artifacts uploaded to `artifacts/57e7e27/` |
| ~21:00:30 | `run-instances` (t3.small, 20 GiB encrypted root, 10 GiB encrypted data volume with `DeleteOnTermination=false`, IMDSv2 required, standard credits); Elastic IP associated once running |
| 21:01–21:02 | Bootstrap: packages, data volume formatted and mounted by UUID at `/var/lib/steward`, code extracted, `uv sync --locked`, secrets generated, **seed** (`python -m agent.seed --db /var/lib/steward/steward.sqlite3 --data /opt/steward/app/data`, score 65), units installed; CloudFront reported `Deployed` |
| 21:02:19–21:02:40 | Service up; the bootstrap's own readiness loop failed with `HOST_FORBIDDEN` because the nginx `Host` placeholder had been rendered away (see "Defect found"); fixed in place with `sed` + `nginx reload`, local `/health` OK |
| 21:03:30 | Public smoke test: `GET /health` 200 in 0.14 s, `GET /` 200 (`text/html`, Steward SPA), `http://` → 301 to `https://`, `GET /api/board` without a cookie → 401 `AUTH_REQUIRED`, direct `http://35.80.131.214/health` times out (security group) |
| 21:03:45 | URL written to `.superpowers/sdd/BUILD_PLAN/H4-url.txt` |
| 21:02–21:04 | The seeded intake invocation `invocation-f5637455-…` ran on its own through the dispatcher: tool calls looped through CloudFront (`observe/authorize/prepare/load/begin/context/finish/complete` all 200), Bedrock answered via the instance role, status `WAITING` (MONITOR at 65) |
| 21:05:23–21:07:53 | **Acceptance driver run 1**, exit code 0 (details below) |
| 21:09:39 | Baseline judge-style fingerprint over the public URL |
| 21:11:05–21:11:29 | **Restart proof** |
| 21:11:36–21:12:18 | **Reboot proof** |
| 21:13:10 | Backup unit run once by hand: `backups/20260914T211310Z/` (DB copy 4,280,320 B with `integrity_check` ok, images tarball 807,164 B, SHA-256 manifest); timer scheduled every 6 h |

## Acceptance driver run

Command (run **on the instance** as root with `/etc/steward/steward.env` sourced so the service token never left the host; the auto-mode permission classifier refused to copy the token to the operator's laptop, so "from this machine" became "from the instance", still against the public HTTPS origin through CloudFront):

```
cd /opt/steward/app && set -a && . /etc/steward/steward.env && set +a
.venv/bin/python -m agent.demo --base-url https://d1uke66gfefpu4.cloudfront.net \
  --out /opt/steward/acceptance/hosted-run-1.json --wait-seconds 240
```

Artifact `hosted-run-1.json` (schema `b13-http-acceptance-v1`, run id `1a34da61…`, origin `https://d1uke66gfefpu4.cloudfront.net`, started 21:05:23, finished 21:07:53; 187 HTTP steps, status codes only 200 and 202, no 4xx/5xx; no bearer token or secret in the file). A copy is at `s3://steward-hackathon-589354718907/backups/acceptance/hosted-run-1.json` and locally under `.steward/hosted/` (not committed, 2.5 MB).

| # | Assertion | Result |
|---|---|---|
| 1 | seed signal is linked | Pass |
| 2 | original invocation saved MONITOR at 65, explicitly waits, and made no dispatch | Pass |
| 3 | saved SIGNAL_LINKED event for the second resident report projects exact evidence score 85 | Pass |
| 4 | supported official dispute reaches 100 | Pass |
| 5 | detail retains official completion and observation facts | Pass |
| 6 | saved scoped plan has 7200-cent quote | Pass |
| 7 | agent selected an eligible saved vendor with one reservation | Pass |
| 8 | saved crew acceptance and plan-location GPS check-in reached CHECKED_IN | Pass |
| 9 | first proof saved distinct before/partial-after evidence and awaits its receipt invocation | Pass |
| 10 | actual 90 proof has failed settlement, zero payment, and a pending completion exception | Pass |
| 11 | actual operator invocation reworked the same saved job, quote, and reservation | Pass |
| 12 | fresh after-only proof produced actual 100 accepted verification | Pass |
| 13 | exactly one saved simulated 7200-cent payment follows fresh verification | Pass |
| 14 | separate resolution accepts fresh proof | Pass |
| 15 | Board reflects resolved marker and final simulated budget | Pass |
| 16 | first successful run retained; reset independently and pass it with `--compare` | Not run (single hosted run; closed locally in [the UI walk](2026-09-14-ui-walk.md)) |

Invocations recorded by the driver (all `error_code: null`, one episode each): `invocation-f5637455` 23 logical requests / 7 model cycles; `invocation-11142100` 12 / 4; `invocation-4b2c127d` 33 / 11; `invocation-52b60d04` 15 / 5; `operator-decision-f9bc01a3` 5 / 2. Final state: issue `demo-couch` `RESOLVED`, evidence score 100 (image 30, independent sources 40, precise geocode 15, service match 15, persistence 0), revision 14; job `47598ea7-4575-40b6-a2cd-5e3ca87b859c` `PAID`, quote 7,200 cents, reservation `375048fb-…`, payment `fde94faa-…`, `simulated: true`; Board available $428.00, reserved $0.00, spent $72.00; watching 0, active 0, resolved 1, attention 0.

## Durability proofs

Judge-style fingerprint (no service token): select the `operator` persona over HTTPS (cookie `__Host-steward-demo` set through CloudFront), then read `/health`, `/api/board`, `/api/issues/demo-couch`, `/api/jobs/47598ea7-…` and the seeded evidence bytes `/api/evidence/evidence-f222f988-…/content` (200,215 bytes, SHA-256 `4161ac8daf72fbe4…`). On-instance fingerprint: `sqlite3` counts (payments, jobs, events, invocations, job status) and `sha256sum /var/lib/steward/images/*`.

| Check | Baseline 21:09:39 | After `systemctl restart steward` | After reboot |
|---|---|---|---|
| Service | PID 23965 | PID 26839 at 21:11:09 (restart took ~4 s) | PID 1957; instance booted 21:11:52, `steward.service` started 21:11:56, application startup complete 21:12:01 |
| Public `/health` | 200 | 200 at 21:11:29 | CloudFront returned 504 at 21:11:55, 200 at 21:12:05 (about 30 s of unavailability) |
| Data volume | `/dev/nvme1n1` on `/var/lib/steward` (ext4) | same | remounted by UUID from `/etc/fstab` |
| DB counts (payments, jobs, events, invocations, job) | 1, 1, 37, 5, PAID | identical | identical |
| Images | `image-e34b66c7…` `4161ac8d…`; `proof-before-image-3bdeb0fb…` `59943871…`; `proof-after-image-a49453b7…` `65f167b9…`; `proof-after-image-b7ccf528…` `a051df56…` | identical digests | identical digests |
| Public fingerprint (board, issue, job, evidence bytes, cookie name) | recorded | **SAME** at 21:11:29 | **SAME** at 21:12:18 |
| Backup timer / nginx | active | active | active after boot |

Exactly one payment row existed before and after both events; no invocation was re-run and no new event was written by the restart or the reboot (event count stayed 37).

## Defect found and fixed

`deploy/provision.sh` renders `__CF_DOMAIN__` in `deploy/user-data.sh`; the first version of the user-data also used `__CF_DOMAIN__` as the marker inside its own `sed` for `nginx.conf`, so the render turned that `sed` into a no-op and nginx forwarded the literal placeholder as `Host`, which the application rejects (`HOST_FORBIDDEN`). Fixed in place on the instance (`sed -i … /etc/nginx/nginx.conf; nginx -t; systemctl reload nginx`) and at the source: `deploy/nginx/nginx.conf` now uses `@CF_DOMAIN@` and the bootstrap asserts the substituted hostname is present. Because the initial bootstrap exited at its readiness loop, `/opt/steward/bootstrap-complete` was not written on this instance; all other steps had completed and the corrected deploy bundle was re-uploaded (bucket versioning keeps the first). The corrected bootstrap has not yet run end to end on a fresh instance; that is the replacement test listed as open.

## Not proven

- Instance replacement with the retained volume (procedure in [HOSTING_DECISION.md](../HOSTING_DECISION.md)); the permission classifier refused to stop the live instance during the session.
- Criterion 16 (second independently seeded hosted run with `--compare`).
- Concurrent duplicate/stale request races on the hosted URL (covered by the offline test suite, not re-run here).
- CloudWatch log shipping; logs remain on the instance.
