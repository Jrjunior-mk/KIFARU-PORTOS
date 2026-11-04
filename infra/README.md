# infra/ — KIFARU PORTOS infrastructure

> **No deployment has been performed.** There is no AWS account for this project yet. Everything here is validated
> offline (`terraform fmt -check`, `terraform init -backend=false`, `terraform validate`) — see section 4 for the actual
> output. `terraform plan`/`apply` and `docker build` have not been run (no credentials, no local Docker daemon).

## 1. Layout

```
infra/
├── README.md                     this file
├── docker/
│   ├── docker-compose.yml        local full stack: postgres:16, redis:7, emqx:5, api, web (+ worker/ingest profile)
│   ├── .env.compose.example      compose variables (copy to .env.compose, git-ignored)
│   └── postgres/init/01-schemas.sql   core/pii/ts schemas + extensions on first start
└── terraform/
    ├── .gitignore                ignores .terraform/, *.tfstate, backend.hcl, terraform.tfvars (keeps *.example)
    ├── bootstrap/                LOCAL-state root: S3 state bucket (KMS, versioned) + DynamoDB lock table (once per account)
    ├── envs/
    │   ├── dev/                  root config: versions.tf providers.tf variables.tf main.tf outputs.tf
    │   ├── staging/              IDENTICAL .tf files to dev …
    │   └── prod/                 … only terraform.tfvars(.example) and backend.hcl(.example) differ
    └── modules/
        ├── network               VPC, 2 AZ, public/private subnets, NAT (shared or per-AZ), S3 gateway + interface endpoints, flow logs
        ├── secrets               KMS key; JWT secret + Ed25519 seed (random provider, sensitive); app-secrets placeholder
        ├── storage               S3 objects (versioning, Object Lock enforced on tickets/ by policy), backups, web, access-logs; CRR to eu-west-1
        ├── queue                 SQS events + jobs, each with DLQ; TLS-only policies
        ├── rds                   PostgreSQL 16, KMS, force_ssl, 35-day PITR, Multi-AZ, cross-region backup replication, secrets + rotation hook
        ├── redis                 ElastiCache Redis 7, TLS + AUTH + at-rest, optional Multi-AZ, URL secret
        ├── ecs                   ECR, cluster, IAM, ALB + regional ACM, services (for_each), autoscaling, migrate/seed/pg_dump tasks
        ├── edge                  us-east-1 ACM, WAF (managed groups + rate rules), CloudFront web (OAC) + api (ALB origin), Route 53
        ├── iot                   IoT Core thing type, per-thing scoped policy, rule kifaru/stations/+/events -> SQS
        ├── iot_emqx_fallback     documented EMQX-on-ECS fallback (NLB :8883) when IoT Core is unavailable in af-south-1
        ├── monitoring            SNS + e-mail, alarms (ALB 5xx/unhealthy/latency, RDS, ECS, Redis, DLQ, queue age), dashboard
        └── ci_oidc               GitHub OIDC provider, least-privilege deploy role, optional broader terraform role
```

**Environments = separate roots, not workspaces.** Rationale: each environment gets its own state file and (ideally)
AWS account, a mistaken `apply` can never touch another environment, and CI can be granted a role per root. The `.tf`
files in the three roots are byte-identical by design; `diff -r envs/dev envs/staging` must show only the `.example`
files. Environment differences are variables (`terraform.tfvars.example` documents every one with the recommended value).

Remote state: S3 + DynamoDB created by `bootstrap/`; roots use a **partial** `backend "s3" {}` block configured with
`terraform init -backend-config=backend.hcl` (template `backend.hcl.example` per env).

Providers are pinned: `hashicorp/aws ~> 5.100` (resolved 5.100.0), `hashicorp/random ~> 3.7` (resolved 3.9.1),
Terraform `>= 1.9.0`. `.terraform.lock.hcl` files are **not** committed yet because the only validation machine was
Windows and a Windows-only lock breaks Linux CI; the first `terraform init` in CI (or `terraform providers lock
-platform=linux_amd64 -platform=windows_amd64`) should generate and commit them.

Tags: every resource carries `Project=KIFARU-PORTOS`, `Env=<env>`, `ManagedBy=terraform`, `Root=…` via provider
`default_tags`, and a `DataClass` (`Public`, `Internal`, `Confidential`, `Confidential-PII`, `Secret`) set per module.

## 2. Request path and trust boundaries

```
browser ──HTTPS──► CloudFront (WAF) ──► S3 web (OAC)                               app.<domain>
browser ──HTTPS──► CloudFront (WAF) ──X-Origin-Verify──► ALB :443 (CloudFront prefix list only)   api.<domain> -> api-origin.<domain>
                                                             ├─ /ws/*  -> realtime service
                                                             └─ /*     -> api service
gateway ──MQTT/mTLS──► IoT Core ──rule──► SQS events ──► ingest service
api/worker ──► RDS (TLS) · Redis (TLS+AUTH) · S3 (KMS) · SQS (KMS)
```

## 3. Commands

```bash
# format check (whole tree)
terraform fmt -check -recursive infra/terraform

# validate each root offline (no credentials needed)
for d in bootstrap envs/dev envs/staging envs/prod; do
  (cd infra/terraform/$d && terraform init -backend=false -input=false && terraform validate)
done

# real usage (owner credentials) — see docs/06-operations/deployment-guide.md
cd infra/terraform/bootstrap && terraform init && terraform apply
cd ../envs/dev && terraform init -backend-config=backend.hcl && terraform plan -out tfplan && terraform apply tfplan
```

## 4. Validation evidence (run 2026-11-04 on Windows 11, Terraform v1.16.6, provider aws 5.100.0 / random 3.9.1)

```
$ terraform fmt -check -recursive        (in infra/terraform)
fmt-check exit=0

$ cd envs/dev     && terraform init -backend=false -input=false && terraform validate
Success! The configuration is valid.

$ cd envs/staging && terraform init -backend=false -input=false && terraform validate
Success! The configuration is valid.

$ cd envs/prod    && terraform init -backend=false -input=false && terraform validate
Terraform has been successfully initialized!
Success! The configuration is valid.

$ cd bootstrap    && terraform init -backend=false -input=false && terraform validate
Terraform has been successfully initialized!
Success! The configuration is valid.
```

Notes on the run: all twelve modules are exercised by the three environment roots (including `iot_emqx_fallback`, which is
instantiated with `count = 0` and still type-checked), so module-level validation is covered by the root runs. The
`network` module was additionally validated stand-alone (`Success! The configuration is valid.`). The validation machine
had almost no free disk, so roots were initialised one at a time from a shared plugin cache
(`plugin_cache_may_break_dependency_lock_file = true`) and their `.terraform/` directories removed afterwards; this has
no effect on the result.

Not verified (no AWS account): `terraform plan`/`apply`, IoT Core availability in af-south-1, ACM/Route 53 validation
timing, actual costs. Not verified (no Docker daemon): `apps/api/Dockerfile` and `infra/docker/docker-compose.yml`
builds — the CI `docker` job builds and smoke-tests the image.

## 5. Known gaps / follow-ups

| # | Item | Where |
|---|---|---|
| 1 | Application entrypoints `python -m kifaru.worker` and `python -m kifaru.ingest` do not exist yet; ECS services `worker`/`ingest` and the compose `workers` profile reference them. Until they exist, set `desired_count = 0`/`min_count = 0` for those two services in tfvars or remove them from `services`. | `apps/api` (application) |
| 2 | `boto3` is installed by the Dockerfile but is not in `apps/api/pyproject.toml`; add it when S3 object storage and SQS consumers are implemented. The API must also set `ObjectLockMode=COMPLIANCE` + `ObjectLockRetainUntilDate` on `tickets/` uploads (bucket policy rejects puts without it). | `apps/api` |
| 3 | `KIFARU_EVENTS_QUEUE_URL`, `KIFARU_JOBS_QUEUE_URL`, `KIFARU_IOT_MODE`, `KIFARU_SERVICE_ROLE` are injected but not yet read by `config.py` (`extra="ignore"` makes this harmless). | `apps/api/kifaru/config.py` |
| 4 | DR: expose an `s3_objects_bucket_override` root variable so a DR apply can point at the replica bucket (`dr-runbook.md` §4 step 4); add `mqtt.<domain>` CNAME convention for gateway failover. | `infra/terraform/envs/*` |
| 5 | Alarm on missed `pg_dump` runs (EventBridge `FailedInvocations` + S3 object canary). | `modules/monitoring` |
| 6 | Add a repo-root `.dockerignore` (the BuildKit-specific `apps/api/Dockerfile.dockerignore` covers `docker build -f apps/api/Dockerfile .` only). | repo root (outside infra scope) |
| 7 | Commit `.terraform.lock.hcl` files generated on Linux. | CI |
| 8 | `cloud-architecture.md` §5 budget figures are lower than the itemised estimate in the deployment guide §9; owner to reconcile. | docs |
