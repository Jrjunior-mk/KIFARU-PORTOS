# KIFARU PORTOS — Deployment Guide (AWS af-south-1)

> **Status: NO DEPLOYMENT HAS BEEN PERFORMED.** No AWS account, domain, or third-party account exists for this project at
> the time of writing (2026-11-04). Everything in `infra/terraform` has passed `terraform fmt -check` and
> `terraform validate` (offline, `-backend=false`) only. `terraform plan`/`apply` have never been run. The steps below are
> the exact procedure the owner (or an engineer with the owner's credentials) must follow; wherever a value must come from
> the owner it is marked **OWNER**.

Related documents: `docs/02-architecture/cloud-architecture.md` (design and provider choice), `dr-runbook.md`,
`backup-and-retention.md`, `local-development.md`, `infra/README.md` (layout and validation evidence).

---

## 1. What gets deployed

| Layer | Resources (per environment) | Terraform module |
|---|---|---|
| Network | VPC /16, 2 AZs, public + private subnets, NAT (1 or per-AZ), S3 gateway endpoint, interface endpoints (ECR, Secrets Manager, Logs, SQS, KMS), flow logs | `network` |
| Secrets | KMS key; Secrets Manager: `kifaru/<env>/jwt-secret`, `signing-seed`, `app-secrets` (third-party placeholders) | `secrets` |
| Storage | S3: `objects` (versioned, Object Lock, KMS), `backups`, `web`, `access-logs`; DR replicas in eu-west-1 | `storage` |
| Queues | SQS `events` + `jobs`, each with a DLQ | `queue` |
| Database | RDS PostgreSQL 16 (gp3, KMS, TLS forced, 35-day PITR, Multi-AZ in prod, cross-region backup replication in prod), credentials in Secrets Manager with rotation hook | `rds` |
| Cache | ElastiCache Redis 7 (TLS, AUTH, at-rest encryption; 2-node Multi-AZ in prod) | `redis` |
| Compute | ECR repos (`kifaru-<env>/api`, `/web`), ECS Fargate cluster, services `api`, `realtime`, `worker`, `ingest`, ALB (HTTPS, regional ACM cert), autoscaling, one-off `migrate`/`seed` task definitions, scheduled `pg-dump` task | `ecs` |
| Edge | CloudFront (web via OAC, api via ALB origin), ACM cert in us-east-1, WAF (managed rule groups + rate rules), Route 53 records | `edge` |
| IoT | IoT Core thing type, per-thing policy, topic rule `kifaru/stations/+/events` → SQS; EMQX fallback module | `iot`, `iot_emqx_fallback` |
| Monitoring | SNS topic + e-mail, alarms (ALB 5xx, unhealthy targets, latency, RDS, ECS, Redis, DLQ), dashboard | `monitoring` |
| CI/CD | GitHub OIDC provider, `github-deploy` and `github-terraform` roles | `ci_oidc` |
| State | S3 state bucket + DynamoDB lock (one per account) | `bootstrap/` |

Environments are **separate Terraform roots** (`infra/terraform/envs/{dev,staging,prod}`) with identical `.tf` files and
different `terraform.tfvars`. Each root has its own state key. Recommended: one AWS account per environment (at minimum
separate VPC/name prefixes, which the roots already guarantee).

---

## 2. Prerequisites the OWNER must provide

| # | Item | Why | Where it is used |
|---|---|---|---|
| 1 | **AWS account(s)** with billing enabled; ideally an AWS Organization with `dev`, `staging`, `prod` member accounts. An IAM identity with `AdministratorAccess` for the bootstrap and first apply (afterwards CI uses OIDC roles). | Everything | Bootstrap, first `terraform apply` |
| 2 | **Registered domain + Route 53 hosted zone** (e.g. `kifaru.example`). Terraform creates records; it does not register domains. | TLS certificates, public URLs | `route53_zone_id`, `web_domain`, `api_domain`, `api_origin_domain` |
| 3 | **Alerting e-mail** (shared ops mailbox) | Alarm notifications | `alarm_email` |
| 4 | **GitHub repository** location (`org/repo`) and permission to configure Environments, variables and secrets | OIDC trust, approvals | `github_org`, `github_repo`, Environment settings |
| 5 | **Africa's Talking** account (SMS) and **Amazon SES production access** (out of the SES sandbox; verified sending domain) | Notifications | Values written into secret `kifaru/<env>/app-secrets` by the owner |
| 6 | Optional: **Sentry** DSN; **KeNHA/KRA/NTSA** integration tokens when real adapters are enabled | Error tracking, integrations | Same secret |
| 7 | **Budget approval**: dev ≈ USD 60–90, staging ≈ USD 150–200, prod ≈ USD 300–400 per month before IoT message volume and egress (section 9) | Cost | AWS Budgets (recommended, not in Terraform) |
| 8 | **Data-protection decisions**: ODPC registration, privacy notice, DPIA sign-off (`docs/04-security/dpia.md`) | Kenya DPA 2019 | Before prod go-live |
| 9 | **Verification that AWS IoT Core is offered in af-south-1** at deployment time; if not, decide `iot_mode = "emqx"` | Station messaging | `iot_mode` |
| 10 | Station gateway inventory (station code, lane numbers) for Thing registration | IoT onboarding | Section 7.4 |

Tools on the deploying workstation: Terraform ≥ 1.9 (validated with 1.16.6), AWS CLI v2, Docker (for local builds only;
CI builds the images), `jq`.

---

## 3. Bootstrap (once per AWS account)

```bash
cd infra/terraform/bootstrap
cp terraform.tfvars.example terraform.tfvars      # adjust names if required
export AWS_PROFILE=kifaru-<env>-admin              # OWNER credentials
terraform init
terraform plan
terraform apply
terraform output                                   # state_bucket_name, lock_table_name, state_kms_key_arn, ARNs
```

This root uses **local state** (`bootstrap/terraform.tfstate`). Keep that file in a safe place (password manager/secure
share); it only tracks the bucket, table and KMS key and can be re-imported if lost.

---

## 4. First apply of an environment

### 4.1 Configure backend and variables

```bash
cd infra/terraform/envs/dev          # or staging / prod
cp backend.hcl.example backend.hcl   # fill bucket / kms_key_id from bootstrap outputs
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`: every `<PLACEHOLDER>` is an OWNER value (section 2). Review the sizing block — the examples are
the recommended per-environment sizes. `create_oidc_provider` must be `true` in exactly one root per AWS account.

### 4.2 Apply

```bash
terraform init -backend-config=backend.hcl
terraform plan -out tfplan
terraform apply tfplan
```

Expected duration: 20–35 minutes (RDS Multi-AZ and CloudFront dominate). The first apply uses `image_tag = "latest"`
which does not exist yet; ECS services will show failed task launches until the first image is pushed (section 5). This is
expected and harmless (the circuit breaker leaves the service at 0 running tasks).

ACM certificates are validated automatically through Route 53 records; if the hosted zone is not authoritative for the
domain yet, the apply blocks on `aws_acm_certificate_validation` — fix delegation at the registrar and re-run.

### 4.3 Confirm the SNS e-mail subscription

AWS sends a confirmation e-mail to `alarm_email`. Alarms are silent until it is confirmed.

### 4.4 Record outputs for GitHub

```bash
terraform output
```

Create a GitHub **Environment** per env (`dev`, `staging`, `prod`; prod with *Required reviewers*) and set:

| Type | Name | Value |
|---|---|---|
| Variable | `AWS_REGION` | `af-south-1` |
| Variable | `AWS_ACCOUNT_ID` | account id |
| Variable | `AWS_DEPLOY_ROLE_ARN` | output `github_deploy_role_arn` |
| Variable | `AWS_TERRAFORM_ROLE_ARN` | output `github_terraform_role_arn` |
| Variable | `TF_STATE_BUCKET` / `TF_STATE_LOCK_TABLE` / `TF_STATE_KMS_KEY_ARN` | bootstrap outputs |
| Variable | `PUBLIC_API_URL` | output `api_url` (e.g. `https://api.<domain>`); baked into the SPA as `VITE_API_BASE` |
| Variable | `PUBLIC_WS_URL` (optional) | `wss://api.<domain>`; derived from `PUBLIC_API_URL` when empty |
| Secret | `TF_VARS_B64` | `base64 -w0 terraform.tfvars` of that environment |

`TF_VARS_B64` is the only place the tfvars leave the workstation; it contains no secrets (all secrets are generated inside
AWS), only identifiers and sizing.

---

## 5. Images and first deployment

The deploy workflow (`.github/workflows/deploy.yml`) does everything below; for the very first run you may trigger it
manually (*Actions → Deploy → Run workflow → environment: dev*). What it does, for reference or manual execution:

```bash
# 1. build + push (CI uses OIDC; manual example)
aws ecr get-login-password | docker login --username AWS --password-stdin <acct>.dkr.ecr.af-south-1.amazonaws.com
docker build -f apps/api/Dockerfile -t <acct>.dkr.ecr.af-south-1.amazonaws.com/kifaru-dev/api:<git-sha> .
docker push <acct>.dkr.ecr.af-south-1.amazonaws.com/kifaru-dev/api:<git-sha>

# 2. point the services at the tag
terraform apply -var image_tag=<git-sha>

# 3. migrations (one-off Fargate task) — see 6
# 4. web: build apps/web, sync to the web bucket, invalidate CloudFront
aws s3 sync apps/web/dist s3://$(terraform output -raw web_bucket_name)/ --delete
aws cloudfront create-invalidation --distribution-id $(terraform output -raw web_distribution_id) --paths "/index.html" "/"
```

Images are tagged with the git SHA (manual runs) or the release tag `vX.Y.Z` (tag push). ECR tags are immutable.

---

## 6. Migrations, seeding and first-time secrets

### 6.1 Migrations

Alembic runs as a one-off task from the same image (`migrate` task definition, command `alembic upgrade head`):

```bash
CLUSTER=$(terraform output -raw ecs_cluster_name)
SUBNETS=$(terraform output -json private_subnet_ids | jq -r 'join(",")')
SG=$(terraform output -raw tasks_security_group_id)
aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE \
  --task-definition "$(terraform output -raw migrate_task_definition_family)" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}"
```

Logs: CloudWatch group `/kifaru/kifaru-<env>/migrate`. The workflow waits for exit code 0 before rolling services.

### 6.2 Seeding

* **dev/staging**: `create_seed_task = true` creates a `seed` task (`python -m kifaru.seed --quiet`) that loads the demo
  organisations, stations and users listed in `apps/api/kifaru/seed.py` (shared demo password, documented there). The
  workflow runs it when `run_seed` is true (dev).
* **prod**: the `ecs` module **refuses to create the seed task when `env = "prod"`**, regardless of the variable. Roles
  and the integration registry are created by the application on first use; the first `platform_admin` is created by the
  owner with `POST /api/v1/admin/users` using a bootstrap procedure (see `docs/04-security/` once written) — never with
  demo credentials.

### 6.3 Secrets

Generated by Terraform (never typed by a human): JWT secret, Ed25519 signing seed, RDS master password, Redis AUTH token,
CloudFront→ALB origin header. They live in Secrets Manager under `kifaru/<env>/…`, encrypted with the environment KMS key,
and are injected into tasks by ECS (`secrets` in the task definition). They are also present in Terraform state, which is
why the state bucket is KMS-encrypted and access-restricted.

Owner-supplied values (SMS, SES, integration tokens, Sentry) go into `kifaru/<env>/app-secrets` **after** the first apply:

```bash
aws secretsmanager put-secret-value --secret-id kifaru/prod/app-secrets --secret-string file://app-secrets.json
```

Terraform ignores later changes to that secret's value. Rotation: RDS via the Secrets Manager rotation Lambda (set
`rds_rotation_lambda_arn` after deploying the AWS SAR application `SecretsManagerRDSPostgreSQLRotationSingleUser`);
JWT/signing seed via `terraform apply -replace=module.secrets.random_password.jwt` followed by a rolling deployment (all
sessions are invalidated — announce it).

---

## 7. Per-environment notes

### 7.1 dev
Single NAT, no interface endpoints, FARGATE_SPOT, `db.t4g.micro`, single-node Redis, no S3 replication, no pg_dump,
`restrict_alb_to_cloudfront` still true. `rds_skip_final_snapshot = true` and `s3_force_destroy = true` so `terraform
destroy` works.

### 7.2 staging
Prod-shaped: interface endpoints, 2 api + 2 realtime tasks, `db.t4g.small`, S3 replication and pg_dump on. Deployed
automatically on every `v*` tag. Demo seed allowed for UAT.

### 7.3 prod
NAT per AZ, Multi-AZ RDS `db.t4g.medium`, 2-node Redis with failover, RDS cross-region backup replication, 90-day logs,
deletion protection everywhere, no seed task. Deployed only through the `prod` GitHub Environment with required reviewers.

### 7.4 Station gateway onboarding (IoT Core)

For each lane gateway (`gw-<station>-l<lane>`, matching `Lane.device_id` from the seed/stations API):

```bash
THING=gw-mrk-l1
aws iot create-thing --thing-name $THING --thing-type-name $(terraform output -raw iot_thing_type_name) \
  --attribute-payload '{"attributes":{"station_code":"MRK","lane_no":"1"}}'
aws iot create-keys-and-certificate --set-as-active --certificate-pem-outfile $THING.crt \
  --public-key-outfile $THING.pub --private-key-outfile $THING.key > $THING.json
CERT_ARN=$(jq -r .certificateArn $THING.json)
aws iot attach-policy --policy-name $(terraform output -raw iot_device_policy_name) --target $CERT_ARN
aws iot attach-thing-principal --thing-name $THING --principal $CERT_ARN
```

Install `$THING.crt`, `$THING.key` and Amazon Root CA 1 on the gateway; endpoint = `terraform output mqtt_endpoint`,
port 8883, client id = thing name. The policy allows only `kifaru/stations/<thing>/events` (publish) and
`…/commands` (subscribe). Private keys are generated on the workstation above only for the pilot; production gateways
should generate keys on-device and use a CSR (`aws iot create-certificate-from-csr`).

---

## 8. Rollback

| Failure | Action |
|---|---|
| New task definition fails health checks | ECS deployment circuit breaker rolls the service back automatically; the workflow's `services-stable` wait fails and stops. Nothing to do except fix and redeploy. |
| Bad release that passed health checks | Re-run *Deploy* manually with the previous good `image_tag` (ECR tags are immutable, so the old image is still there), or `terraform apply -var image_tag=<previous>`. |
| Bad migration | Alembic `downgrade` is **not** run automatically. Restore options: `alembic downgrade <rev>` via a one-off task (same `migrate` task definition with an overridden command) if the revision has a safe downgrade; otherwise RDS point-in-time restore to just before the migration (`dr-runbook.md` section 4) and re-point `database-url`. |
| Web regression | Re-sync the previous `web-dist-<tag>` artifact (kept 14 days) and invalidate. S3 versioning keeps 30 days of old builds. |
| Infrastructure change | `terraform plan` on the previous commit, review, apply. State history is kept 90 days in the versioned state bucket. |

---

## 9. Cost estimate (USD/month, af-south-1 list prices as understood at writing; verify in the AWS Pricing Calculator)

| Item | dev | staging | prod |
|---|---|---|---|
| NAT gateway (hourly + ~20 GB) | 35 | 35 | 70 (2×) |
| Interface endpoints (6 × ~7.5) | 0 (disabled) | 45 | 45 |
| Fargate (api/realtime/worker/ingest) | 15 (Spot, 0.25–0.5 vCPU each) | 55 | 130 (2× 1 vCPU api, 2× 0.5 realtime, 2× 0.5 workers) |
| ALB | 20 | 20 | 25 |
| RDS PostgreSQL 16 | 15 (t4g.micro, 20 GB) | 35 (t4g.small, 50 GB) | 130 (t4g.medium Multi-AZ, 100 GB) + 10 backup replication |
| ElastiCache Redis | 12 (t4g.micro) | 12 | 55 (2× t4g.small) |
| S3 + replication + Object Lock | 2 | 5 | 10–20 |
| CloudFront + WAF | 8 (WAF fixed) + traffic | 10 | 20–40 |
| IoT Core (4 stations × 2 lanes, ~1 msg/s peak) | 1 | 2 | 5–15 |
| CloudWatch (logs, Container Insights, alarms, dashboard) | 5 | 10 | 25 |
| Secrets Manager, KMS, SQS, Route 53 | 6 | 8 | 10 |
| **Total** | **≈ 120** | **≈ 240** | **≈ 540–580** |

These are higher than the budget figures in `cloud-architecture.md` §5 (dev 60 / staging 150 / prod 300–400) because that
estimate excluded NAT, endpoints, WAF and CloudWatch. Cheapest levers if the owner needs to hit those numbers: disable
interface endpoints in staging (−45), run staging only during working hours (Fargate/RDS stop-start: −40 %), single NAT
in prod (−35, at the cost of AZ-failure resilience for egress), `PriceClass_100` for dev. Not included: data egress to
Kenya (CloudFront/ALB egress at ~USD 0.11/GB in af-south-1), SMS costs (Africa's Talking), SES.

---

## 10. Checklist before calling an environment "live"

- [ ] Bootstrap applied; `backend.hcl` + `terraform.tfvars` stored securely (not committed).
- [ ] `terraform apply` clean, no pending changes on a second `plan`.
- [ ] SNS e-mail confirmed; a test alarm (`aws cloudwatch set-alarm-state`) reached the mailbox.
- [ ] Image pushed, `migrate` exit 0, `/ready` returns 200 through `https://api.<domain>/ready`.
- [ ] Web loads at `https://app.<domain>`, login works, WebSocket `/ws/events` connects through CloudFront.
- [ ] `kifaru/<env>/app-secrets` filled (SMS/SES) and a test notification delivered.
- [ ] At least one gateway Thing registered and events visible in `/kifaru/kifaru-<env>/ingest` logs.
- [ ] pg_dump task ran once manually and the object appeared in the backups bucket and its DR replica.
- [ ] DR drill performed once (`dr-runbook.md` section 6) before production traffic.
- [ ] Cost allocation tags visible in Cost Explorer (`Project`, `Env`, `DataClass`); AWS Budget alert configured.
