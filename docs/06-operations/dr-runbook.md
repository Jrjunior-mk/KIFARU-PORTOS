# KIFARU PORTOS — Disaster Recovery Runbook

**Targets:** RTO **4 hours**, RPO **15 minutes** (production). Primary region `af-south-1` (Cape Town); recovery region
`eu-west-1` (Ireland).

> No environment is deployed yet; this runbook describes the procedure the Terraform code is designed for and must be
> rehearsed (section 6) before production go-live. Commands assume the prod root in `infra/terraform/envs/prod` and an
> operator with the owner's break-glass IAM credentials (CI roles are deliberately not allowed to do this).

---

## 1. What is replicated where

| Data | Primary | Copy | Mechanism | RPO contribution |
|---|---|---|---|---|
| PostgreSQL (RDS) | af-south-1, Multi-AZ | eu-west-1 | **RDS cross-region automated backup replication** (`rds_cross_region_backup_replication = true`): snapshots + transaction logs, 14-day retention, KMS key in eu-west-1 | ≤ 5 min typical log shipping lag → within RPO 15 min |
| PostgreSQL logical dump | — | S3 `backups` → `backups-dr` | Daily `pg_dump` (ECS scheduled task) + S3 replication (RTC 15 min) | Last-resort only (RPO 24 h) |
| Objects (tickets, evidence) | S3 `kifaru-prod-objects-<acct>` | `kifaru-prod-objects-dr-<acct>` (eu-west-1) | S3 CRR with Replication Time Control (15 min SLA), Object Lock preserved | ≤ 15 min |
| Redis | ElastiCache | daily snapshot (same region) | not replicated; cache/pub-sub only, rebuilt on start | n/a (no durable data) |
| Secrets | Secrets Manager af-south-1 | — | Re-created by Terraform in the recovery region (new random values) or replicated manually with `replicate-secret-to-regions` before an event (recommended, see 2.3) | n/a |
| SQS | in-region | — | In-flight events may be lost; gateways replay from their SQLite outbox with idempotent `event_id`s | covered by edge design |
| Web SPA | S3 `web` + CloudFront | rebuilt from git/artifact | CloudFront is global; S3 web origin re-synced | n/a |
| Terraform state | S3 state bucket af-south-1 | **owner action:** enable CRR on the state bucket or copy weekly | needed to run Terraform in DR |

---

## 2. Preparedness (do once, verify quarterly)

### 2.1 Confirm replication is healthy
```bash
aws rds describe-db-instance-automated-backups --region eu-west-1 \
  --query 'DBInstanceAutomatedBackups[?DBInstanceIdentifier==`kifaru-prod-postgres`].[Status,RestoreWindow.LatestTime]'
aws s3api get-bucket-replication --bucket kifaru-prod-objects-<acct>
aws cloudwatch get-metric-statistics --namespace AWS/S3 --metric-name ReplicationLatency \
  --dimensions Name=SourceBucket,Value=kifaru-prod-objects-<acct> Name=DestinationBucket,Value=kifaru-prod-objects-dr-<acct> Name=RuleId,Value=objects-to-dr \
  --statistics Maximum --period 900 --start-time $(date -u -d '-1 day' +%FT%TZ) --end-time $(date -u +%FT%TZ)
```

### 2.2 Keep a DR tfvars ready
Copy `envs/prod/terraform.tfvars` to `envs/prod/dr.tfvars` (git-ignored) with:
```hcl
aws_region                          = "eu-west-1"
dr_region                           = "af-south-1"   # replicate back once primary is healthy
vpc_cidr                            = "10.43.0.0/16"
rds_cross_region_backup_replication = false
create_oidc_provider                = false           # account-level, already exists
restrict_alb_to_cloudfront          = true
```
Domain names stay the same (Route 53 is global). `api_origin_domain` may stay the same too: the record is re-pointed.

### 2.3 Replicate secrets (recommended)
```bash
for s in jwt-secret signing-seed app-secrets; do
  aws secretsmanager replicate-secret-to-regions --secret-id kifaru/prod/$s --add-replica-regions Region=eu-west-1
done
```
The signing seed **must** be identical in DR, otherwise previously issued tickets fail verification. The DR apply will
create new secrets with new names only if you let it; instead import the replicas (`terraform import`) or set the
replicated values into the Terraform-created secrets after apply (section 4, step 7).

### 2.4 Pre-stage images
ECR replication rule (owner action, console or CLI): replicate `kifaru-prod/*` to eu-west-1 so the DR cluster can pull the
current tag without a rebuild.

---

## 3. Decision and declaration

1. **Trigger**: af-south-1 regional impairment (AWS Health Dashboard) **or** RDS unavailable > 30 min with Multi-AZ
   failover not resolving **or** data corruption requiring point-in-time restore.
2. **Declare**: incident commander records time of declaration (T0), notifies owner and port-control stakeholders.
   Station operations continue on the edge (clearance decisions are local; events queue in gateway outboxes).
3. **Freeze**: disable the `Deploy` workflow (GitHub → Actions → disable) to prevent CI from fighting the recovery.

RTO clock: T0 → T0 + 4 h. Typical durations below total ≈ 2 h 15 min.

---

## 4. Recovery procedure (region failover to eu-west-1)

| Step | Action | Expected time |
|---|---|---|
| 1 | **Restore RDS from the replicated automated backup** (point-in-time, latest restorable time): see command below. | 25–45 min (100 GB) |
| 2 | **Terraform the DR stack**: `terraform init -backend-config=backend.hcl -reconfigure` then `terraform plan -var-file=dr.tfvars -out dr.plan` from a **separate state key** (`key=envs/prod-dr/terraform.tfstate` in a copy of `backend.hcl`). Apply. This creates VPC, ECS, ALB, Redis, queues, IoT, monitoring in eu-west-1. It also creates a *new empty* RDS instance, which we will not use (step 3). | 25–35 min |
| 3 | **Point the app at the restored DB**: update secrets `kifaru/prod/database` and `kifaru/prod/database-url` in eu-west-1 with the endpoint of the instance restored in step 1 (same master username/password — the restore keeps them). Then `terraform apply -replace` is **not** needed: force a new deployment so tasks re-read secrets: `aws ecs update-service --force-new-deployment` for each service. Delete the unused Terraform-created instance later (`terraform state rm` + console delete) or import the restored one into state when calm. | 10 min |
| 4 | **Objects**: set `KIFARU_S3_BUCKET` to the DR bucket. Fastest path: the DR root's `storage` module creates `kifaru-prod-objects-<acct>` **in eu-west-1** — this name already exists (S3 names are global, the replica is `…-objects-dr-…`). Therefore in `dr.tfvars` the storage module must be told to *use* the replica: set `extra_tags` is irrelevant; instead run `terraform apply -target` without the storage module and set `KIFARU_S3_BUCKET` through an override in `app_environment` (`terraform.tfvars` → add `s3_objects_bucket_override = "kifaru-prod-objects-dr-<acct>"` — **TODO owner/infra: expose this variable before the first drill**; tracked in `infra/README.md` known gaps). | 5 min |
| 5 | **Secrets**: if 2.3 was done, point tasks at the replica ARNs (same names → ECS task definitions resolve the regional replica automatically because ARNs contain the region: re-run `terraform apply -var-file=dr.tfvars` after importing the replicas with `terraform import module.secrets.aws_secretsmanager_secret.jwt kifaru/prod/jwt-secret`, same for `signing_seed`, `app`). | 10 min |
| 6 | **Images**: confirm `kifaru-prod/api:<tag>` exists in the eu-west-1 ECR (2.4). If not, run the Deploy workflow against a temporary `prod-dr` GitHub Environment or `docker push` from a workstation. | 0–15 min |
| 7 | **Migrate**: run the `migrate` task (deployment guide 6.1) — it is a no-op if the restored DB is at head, and protects against a restore from an older snapshot. | 3 min |
| 8 | **DNS failover**: `api-origin.<domain>` → new ALB (Terraform already did this in step 2 because the record is managed by the `ecs` module); CloudFront distributions are re-created by the DR root with the same aliases — **conflict**: an alias can be attached to only one distribution. Delete/disable the primary distributions first if the primary account/region is reachable (`aws cloudfront update-distribution … Enabled=false`), or use `aws cloudfront associate-alias` (requires a TXT record `_<alias>`). | 10–20 min (CloudFront propagation) |
| 9 | **Verify**: `https://api.<domain>/ready` 200; login; ticket verification of a pre-incident ticket (signing seed intact); WebSocket connects; a gateway reconnects to the new MQTT endpoint (`terraform output mqtt_endpoint`) — gateways need the new endpoint pushed via their config channel or a DNS CNAME `mqtt.<domain>` (**recommendation**: always configure gateways with `mqtt.<domain>`, a CNAME managed outside Terraform, so failover is one record change). | 15 min |
| 10 | **Unfreeze**: re-enable the Deploy workflow pointing at the DR state key; announce; start the post-incident log. | — |

### RDS restore command (step 1)
```bash
LATEST=$(aws rds describe-db-instance-automated-backups --region eu-west-1 \
  --query 'DBInstanceAutomatedBackups[?DBInstanceIdentifier==`kifaru-prod-postgres`].RestoreWindow.LatestTime' --output text)
aws rds restore-db-instance-to-point-in-time --region eu-west-1 \
  --source-db-instance-automated-backups-arn arn:aws:rds:eu-west-1:<acct>:auto-backup:<id> \
  --target-db-instance-identifier kifaru-prod-postgres-dr \
  --restore-time "$LATEST" \
  --db-instance-class db.t4g.medium --multi-az --no-publicly-accessible \
  --db-subnet-group-name kifaru-prod-db --vpc-security-group-ids <sg from step 2> \
  --kms-key-id <rds dr kms key arn> --copy-tags-to-snapshot --deletion-protection
aws rds wait db-instance-available --region eu-west-1 --db-instance-identifier kifaru-prod-postgres-dr
```
(The subnet group and security group come from step 2; run steps 1 and 2 in parallel and attach when both are ready via
`modify-db-instance`.)

### Same-region data-corruption variant
If the region is healthy but data is corrupt (bad migration, operator error): skip steps 2, 4, 5, 6, 8. Restore
point-in-time **in af-south-1** to `kifaru-prod-postgres-pitr`, validate on a bastion task (`aws ecs execute-command`),
update the two database secrets, force new deployments. RTO ≈ 1 h.

---

## 5. Failback

1. When af-south-1 is healthy, apply the primary root again (state key `envs/prod`) with `rds_cross_region_backup_replication`
   pointing at the DR region as source — simplest is a fresh apply then a logical copy: `pg_dump` from DR, `pg_restore`
   into primary during a maintenance window (announce read-only period; the API has no read-only switch yet — **app
   change recommended**: a `KIFARU_READ_ONLY=true` flag).
2. Reverse S3 replication (DR → primary) until counts match (`aws s3api list-objects-v2 --query 'KeyCount'` on both),
   then restore the original rules with `terraform apply`.
3. Re-point CloudFront aliases, `api-origin`, and `mqtt.<domain>`; decommission DR resources with
   `terraform destroy -var-file=dr.tfvars` (keep the DR RDS snapshot for 35 days).

---

## 6. Quarterly DR test checklist

| # | Test | Pass criterion | Evidence |
|---|---|---|---|
| 1 | RDS restore to point-in-time in eu-west-1 (step 1 only, into an isolated VPC) | instance available ≤ 45 min; `SELECT count(*) FROM core.ledger_entries` matches primary at that time ± in-flight | CloudTrail event, screenshot, timing |
| 2 | Restore of latest `pg_dump` object from the **DR** backups bucket into a scratch PostgreSQL (`pg_restore --list` + full restore) | restore completes; row counts within 24 h of primary | task log |
| 3 | Ticket verification continuity: verify a signed ticket against the restored data using the replicated signing seed | signature valid | API response |
| 4 | S3 replication lag ≤ 15 min over the last 30 days (`ReplicationLatency` max) and zero `OperationsFailedReplication` | metrics | CloudWatch screenshot |
| 5 | Full DR stack apply from `dr.tfvars` into eu-west-1 **without** DNS cutover (steps 2–7, 9 using the ALB DNS name directly) | `/ready` 200 through the DR ALB within 4 h | timing log, then `terraform destroy` |
| 6 | Gateway failover: one lab gateway re-pointed to the DR MQTT endpoint, replay of 100 queued events | all events ingested once (idempotency) | ingest logs / ledger count |
| 7 | Alarm path: force `kifaru-prod-rds-cpu` into ALARM | e-mail received | mailbox |
| 8 | Runbook review: every command in this file executed or dry-run; owner contacts and account IDs still correct | updated document committed | git history |

Record each test in `docs/06-operations/dr-test-log.md` (create on first test) with date, participants, measured RTO/RPO,
deviations and follow-ups.

---

## 7. Contacts and roles (OWNER to fill)

| Role | Name | Channel |
|---|---|---|
| Incident commander | | |
| AWS account owner / billing | | |
| Port control liaison (KPA) | | |
| Weighbridge operations (KeNHA) | | |
| AWS Support plan level | Business recommended for prod (needed for < 1 h response) | |
