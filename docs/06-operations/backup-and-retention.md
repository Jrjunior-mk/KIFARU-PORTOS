# KIFARU PORTOS — Backup and Data Retention

Scope: production (`prod`); staging follows the same mechanisms with shorter retention; dev has no backups beyond RDS
defaults. All backups are encrypted at rest with customer-managed KMS keys (`alias/kifaru-prod-rds`, `alias/kifaru-prod-s3`,
`alias/kifaru-prod-s3-dr`) and in transit with TLS. **Nothing below is running yet** — it is what
`infra/terraform` provisions.

---

## 1. Mechanisms

### 1.1 RDS automated backups + PITR
* `backup_retention_period = 35` days (RDS maximum), daily snapshot window 00:00–01:00 UTC (03:00–04:00 EAT), transaction
  logs every 5 minutes → point-in-time restore to any second in the last 35 days.
* Storage, snapshots and Performance Insights encrypted with the RDS KMS key; `rds.force_ssl = 1`.
* Prod: **cross-region automated backup replication** to eu-west-1 (`aws_db_instance_automated_backups_replication`),
  14-day retention, separate KMS key. This is the primary DR source (RPO ≤ 15 min).
* Final snapshot on deletion (`skip_final_snapshot = false` outside dev); `deletion_protection = true`.
* Manual snapshots before risky changes (migrations with destructive steps, major upgrades):
  `aws rds create-db-snapshot --db-instance-identifier kifaru-prod-postgres --db-snapshot-identifier pre-<change>-<date>`.
  Manual snapshots are **not** expired automatically — review quarterly.

### 1.2 Logical backup: scheduled `pg_dump` (ECS task)
Defined in `modules/ecs` (`aws_ecs_task_definition.pg_dump`, EventBridge rule `kifaru-<env>-pg-dump`, default
`cron(30 0 * * ? *)` = 03:30 EAT daily):

* Runs the API image (which ships `postgresql-client-16` and `boto3`), reads `PGHOST/PGUSER/…` from the JSON secret
  `kifaru/<env>/database` (Secrets Manager → ECS secrets, never on the command line), `PGSSLMODE=require`.
* `pg_dump --format=custom --compress=6 --no-owner --no-privileges` → `/tmp` (50 GiB ephemeral storage) → uploaded with
  SSE-KMS to `s3://kifaru-<env>-backups-<acct>/pgdump/<env>/kifaru-<env>-<UTC timestamp>.dump`.
* Logs: `/kifaru/kifaru-<env>/pg-dump`. Failure visibility: EventBridge retries twice; a missing daily object should be
  alarmed — **TODO**: add an `aws_cloudwatch_metric_alarm` on `FailedInvocations` for the rule and an S3 object-count
  canary (tracked in `infra/README.md` known gaps).
* Why a logical dump in addition to RDS snapshots: engine-independent (restorable to any PostgreSQL 16, including a laptop
  for audits), survives accidental deletion of the RDS instance *and* its automated backups, and is what regulators/auditors
  can be handed.
* Restore test (quarterly, see `dr-runbook.md` §6): `pg_restore --clean --if-exists --no-owner -d kifaru <file>`.

### 1.3 Redis snapshots
ElastiCache automatic snapshots: `snapshot_retention_limit` 7 days (prod), window 01:00–02:00 UTC. Redis holds only
derived/ephemeral state (pub/sub, rate-limit counters, idempotency keys with TTL, queue state cache), so snapshots exist for
fast warm-up after a failure, not for data recovery. Note: `cache.t4g.micro` does not support snapshots in all regions —
dev sets retention 1 and may need 0.

### 1.4 S3 versioning, Object Lock and replication
* `objects` and `backups` buckets: versioning on, SSE-KMS with bucket keys, TLS-only bucket policies, public access blocked.
* `objects` has **Object Lock enabled**; the bucket policy denies any `PutObject` under `tickets/` that does not carry
  `x-amz-object-lock-mode: COMPLIANCE` (the API must set mode + retain-until-date = now + 7 years on ticket uploads; **app
  change required** when S3 storage is wired in). Compliance mode means not even the root account can delete a ticket
  before its retention date.
* Cross-region replication (RTC 15-minute SLA, replication metrics) of `objects` and `backups` to eu-west-1 replicas, with
  re-encryption under the DR KMS key. Delete markers are **not** replicated (a deletion in primary never propagates).
* `web` bucket versioned (30-day history of builds); `access-logs` SSE-S3 (ALB log delivery requirement).

### 1.5 Terraform state
Versioned, KMS-encrypted bucket; 90 days of non-current versions. Owner should enable CRR of this bucket to eu-west-1 so
Terraform can run in DR (see `dr-runbook.md` §1).

### 1.6 Logs
CloudWatch Logs retention per environment (`log_retention_days`: dev 14, staging 30, prod 90). ALB access logs 90 days
in S3. WAF logs 30 days (prod `log_retention_days` applies). VPC flow logs (REJECT only) same as application logs.

---

## 2. Retention table

Legal basis column: KE = Kenyan statutory/regulatory expectation as understood by the project (Traffic Act / EAC Vehicle
Load Control Act evidence, KRA record-keeping 5 years, Kenya DPA 2019 storage limitation). **To be confirmed by the owner's
legal counsel before go-live.**

| Data class | Store | Retention | Enforcement | Encryption | Legal basis / rationale |
|---|---|---|---|---|---|
| Signed weighing tickets (PDF/JSON + QR) | S3 `objects/tickets/` | **7 years**, then eligible for deletion (not automatic) | Object Lock COMPLIANCE (policy-enforced on put), lifecycle → Glacier IR after 1 y, never expires | SSE-KMS | KE evidence in enforcement/appeals; VLC Act |
| Ticket/ledger/clearance rows | PostgreSQL `core` | 7 years online (partition by month; archive policy TBD) | application/DBA | KMS at rest | same |
| Hash-chained ledger | PostgreSQL `core.ledger_entries` | indefinite (append-only) | application | KMS | tamper-evidence |
| ANPR evidence images | S3 `objects/evidence/` | 30 d Standard → 90 d Glacier IR → **365 d delete**; non-current versions 90 d | S3 lifecycle | SSE-KMS | DPA minimisation: plates are personal data; 1 y covers appeal windows |
| Raw WIM signal snapshots | S3 `objects/raw-signals/` | **90 d** | S3 lifecycle | SSE-KMS | calibration/forensics only; decimated stats kept in `ts` |
| Exports / reports | S3 `objects/exports/` | 30 d | S3 lifecycle | SSE-KMS | regenerable |
| Time-series sensor stats | PostgreSQL `ts` | 24 months (monthly partitions dropped by job — **TODO** pg_partman revision) | DB job | KMS | capacity planning |
| PII (names, ID numbers, phones) | PostgreSQL `pii` (column-encrypted) | life of account + 12 months; erasure on request | application | KMS + column crypto | Kenya DPA 2019 |
| Audit log (privileged actions) | PostgreSQL `core.audit_log` | 5 years | application | KMS | KRA/record-keeping |
| pg_dump archives | S3 `backups/pgdump/` + DR replica | 30 d Standard-IA → 90 d Glacier → **400 d delete** | S3 lifecycle | SSE-KMS (both regions) | 13 months covers a full fiscal year audit |
| RDS automated backups | RDS | 35 d (primary), 14 d (eu-west-1 replica) | RDS | KMS | PITR |
| RDS manual snapshots | RDS | until reviewed (quarterly) | manual | KMS | pre-change safety |
| Redis snapshots | ElastiCache | 7 d | ElastiCache | at-rest encryption | warm-up only |
| Application logs (JSON) | CloudWatch Logs | prod 90 d / staging 30 d / dev 14 d | retention setting | AWS-managed | troubleshooting; contain no PII by policy (structlog processors must redact) |
| ALB access logs | S3 `access-logs/alb/` | 90 d | S3 lifecycle | SSE-S3 | security forensics |
| WAF logs | CloudWatch Logs `aws-waf-logs-…` (us-east-1) | 30–90 d | retention setting | AWS-managed | security; `authorization`/`cookie` headers redacted |
| VPC flow logs (REJECT) | CloudWatch Logs | = app logs | retention setting | AWS-managed | security |
| Terraform state versions | S3 state bucket | 90 d of history | lifecycle | SSE-KMS | rollback of infra |
| Web builds | S3 `web` versions | 30 d | lifecycle | SSE-S3 | rollback |
| ECR images | ECR | last 30 tags; untagged 7 d | lifecycle policy | AES-256 | rollback |
| SQS messages | SQS | 4 d main / 14 d DLQ | queue attributes | SSE-KMS | redelivery window |

---

## 3. Encryption of backups — key summary

| Key | Protects | Rotation | Notes |
|---|---|---|---|
| `alias/kifaru-<env>-rds` | RDS storage, automated/manual snapshots, Performance Insights | yearly (AWS automatic) | snapshots copied to another account must be re-encrypted |
| RDS DR key (eu-west-1, module `rds`) | replicated automated backups | yearly | needed by `restore-db-instance-to-point-in-time` in DR |
| `alias/kifaru-<env>-s3` | `objects`, `backups` buckets (incl. pg_dump objects) | yearly | bucket keys reduce KMS cost |
| `alias/kifaru-<env>-s3-dr` | replica buckets | yearly | replication role has `kms:Encrypt`/`GenerateDataKey` on it |
| `alias/kifaru-<env>-secrets` | Secrets Manager secrets, SQS queues | yearly | ECS execution role has `kms:Decrypt` |
| `alias/kifaru-terraform-state` | state bucket, lock table | yearly | |

Key deletion windows are 30 days; keys are never scheduled for deletion while any backup they protect is within retention.

---

## 4. Operator procedures

| Task | How |
|---|---|
| Run an ad-hoc dump | `aws ecs run-task --cluster kifaru-prod --launch-type FARGATE --task-definition kifaru-prod-pg-dump --network-configuration "awsvpcConfiguration={subnets=[…],securityGroups=[…],assignPublicIp=DISABLED}"` |
| List dumps | `aws s3 ls s3://kifaru-prod-backups-<acct>/pgdump/prod/` |
| Restore a dump locally for an audit | `aws s3 cp s3://…/kifaru-prod-<ts>.dump . && docker run -d -e POSTGRES_PASSWORD=x -p 5433:5432 postgres:16 && pg_restore -h localhost -p 5433 -U postgres -d postgres --create --no-owner kifaru-prod-<ts>.dump` |
| Point-in-time restore | `dr-runbook.md` §4 (same-region variant) |
| Verify Object Lock on a ticket | `aws s3api get-object-retention --bucket kifaru-prod-objects-<acct> --key tickets/<id>.pdf` |
| Right-to-erasure (DPA) | application job anonymises `pii` rows; S3 evidence under `evidence/` deleted by key; **tickets are exempt** (legal retention) — document the exemption in the privacy notice |
| Quarterly review | manual RDS snapshots, Glacier IR volumes, lifecycle rule hits (S3 Storage Lens), restore test record |
