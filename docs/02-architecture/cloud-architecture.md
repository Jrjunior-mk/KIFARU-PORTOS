# KIFARU PORTOS — Live Cloud Infrastructure Architecture

## 1. Provider evaluation

Evaluated 2026-11-04 for a Kenyan deployment serving Mombasa, Mariakani and the Northern Corridor.
Facts below are stated as of the authors' knowledge and **must be re-verified against the providers' regional service lists at
deployment time**; nothing here is a measured latency figure.

| Criterion | AWS | Microsoft Azure | Google Cloud |
|---|---|---|---|
| Nearest region | **af-south-1 (Cape Town)**; CloudFront/Route 53 edge PoPs in Nairobi | South Africa North (Johannesburg), South Africa West (Cape Town) | africa-south1 (Johannesburg) |
| Kenyan region | None | None | None |
| Data residency / Kenya DPA 2019 | Transfer outside Kenya permitted under DPA s.48–49 with safeguards (adequacy, consent, or contractual clauses); AWS DPA + SCC-style terms available | Same legal position; Azure DPA available | Same legal position; GCP DPA available |
| Managed IoT (MQTT, X.509 device auth) | AWS IoT Core (verify availability in af-south-1; fallback: self-hosted EMQX on ECS) | Azure IoT Hub (regional availability must be verified) | IoT Core was discontinued (2023); third-party only |
| Managed PostgreSQL | RDS / Aurora PostgreSQL | Azure Database for PostgreSQL Flexible | Cloud SQL |
| Time-series | RDS has **no TimescaleDB**; use native partitioning + pg_partman, or Timescale on self-managed container | Same limitation | Same |
| Containers | ECS Fargate (simple), EKS | Container Apps, AKS | Cloud Run, GKE |
| Edge CDN in Kenya | CloudFront PoP Nairobi | Azure Front Door (Nairobi edge) | Cloud CDN (Nairobi edge) |
| Cost (small prod: 2 Fargate tasks, db.t4g.medium RDS, cache.t4g.micro, IoT, S3) | ≈ USD 250–400 / month | Comparable | Comparable, slightly lower egress |
| Team familiarity / IaC maturity | Terraform AWS provider is the most mature | Good | Good |
| Disaster recovery | Multi-AZ RDS, cross-region S3 replication to eu-west-1 | Equivalent | Equivalent |

**Selection: AWS, primary region `af-south-1` (Cape Town), DR copies in `eu-west-1`.** Reasons: mature IoT Core with
per-device X.509 certificates (critical for station authentication), most mature Terraform tooling, CloudFront edge presence in
Nairobi, and the Master Prompt's stated preference. Decision is reversible: the backend is container-based and the data layer is
plain PostgreSQL/Redis/S3-compatible object storage.

**Data-protection posture.** The platform is a *data controller* for user accounts and a *data processor* for transporter and
cargo-owner commercial data. Personal data (driver names, ID numbers, phone numbers) is stored in a separate `pii` schema with
column-level encryption; cross-border storage in Cape Town is documented in the privacy notice and the Data Protection Impact
Assessment (`docs/04-security/dpia.md`). Registration with the Office of the Data Protection Commissioner (ODPC) as controller/processor
is an owner action before production launch.

## 2. Target topology (production)

```
                  Route 53 (kifaru.example) ── ACM certs
                        │
            ┌───────────┴───────────┐
       CloudFront (web, S3 origin)   AWS WAF ─► ALB (api.kifaru…, ws.kifaru…)
                                                 │
                              ┌──────────────────┴──────────────────┐
                              │  ECS Fargate (private subnets, 2 AZ) │
                              │   api  ×2   realtime ×2   worker ×1  │
                              │   ingest ×1 (IoT rule → SQS → ingest)│
                              └───┬──────────┬──────────┬───────────┘
                                  │          │          │
                        RDS PostgreSQL 16   ElastiCache  S3 (tickets, evidence
                        Multi-AZ, encrypted  Redis 7     images, backups)
                                  │
                        Secrets Manager · CloudWatch (logs, metrics, alarms) · SQS (jobs, DLQ)
                                  │
                        AWS IoT Core ◄── MQTT/TLS mTLS ── station gateways (Mariakani L1, L2 …)
```

Environments: `dev` (single AZ, db.t4g.micro, 1 task each), `staging` (prod-shaped, smaller), `prod` (above). Each is a separate
Terraform workspace and AWS account (recommended) or at minimum a separate VPC and name prefix.

## 3. Required live capabilities → implementation

| # | Capability | Implementation |
|---|---|---|
| 1 | Deployed backend | ECS Fargate services from ECR images built by GitHub Actions |
| 2 | Production DB | RDS PostgreSQL 16, Multi-AZ, storage encrypted (KMS), automated backups 35 days + PITR |
| 3 | Real auth | Platform-native auth (Argon2id, JWT, TOTP MFA) in the API; Cognito evaluated and rejected to keep auth portable |
| 4 | Secure APIs | HTTPS only (ACM), WAF managed rules + rate rules, JWT, RBAC, Pydantic validation |
| 5 | Real-time | Redis pub/sub → WS gateway; IoT Core rules → SQS |
| 6 | Persistent storage | RDS + S3 (versioned, Object Lock for tickets) |
| 7 | IoT messaging | IoT Core (mTLS, per-device policies); EMQX fallback documented |
| 8 | Live notifications | WS, Africa's Talking SMS adapter, SES email, webhooks |
| 9 | Frontend hosting | S3 + CloudFront (OAC), SPA fallback |
| 10 | Backups | RDS automated + daily `pg_dump` to S3 (cross-region replicated), Redis snapshot |
| 11 | DR | RTO 4 h / RPO 15 min: restore RDS snapshot in eu-west-1 from replicated copy; runbook in `docs/06-operations/dr-runbook.md` |
| 12 | App monitoring | CloudWatch Logs (JSON), metrics, alarms → SNS; `/health` + `/ready` |
| 13 | Error tracking | Sentry SDK (DSN via Secrets Manager); optional |
| 14 | Infra monitoring | CloudWatch Container Insights, RDS Performance Insights |
| 15 | Automated deployment | GitHub Actions: test → build → push ECR → terraform apply (staging auto, prod manual approval) |

## 4. Edge resilience (outage operation)

Each station gateway keeps a local SQLite (WAL) outbox and a mirror of the rule configuration (limits, watch-list snapshot,
calibration). The clearance decision never depends on the cloud. On reconnect, events are replayed in order with ULID
idempotency keys; the cloud ingest is idempotent on `event_id`. Clock drift is bounded by GPS/NTP on the gateway; events carry
both `occurred_at` and `received_at`.

## 5. What requires the owner's authorisation (CLD-03)

1. An AWS account (or Organization) with billing; IAM user/role for Terraform with an OIDC trust to the GitHub repository.
2. A registered domain and Route 53 hosted zone.
3. Africa's Talking (or equivalent) SMS account; SES production access.
4. ODPC registration decision and signed privacy notice.
5. Approval of monthly budget. The itemised estimate in `docs/06-operations/deployment-guide.md` §9 (including NAT gateways, VPC endpoints, WAF and CloudWatch) is approximately USD 120 (dev), 240 (staging) and 540–580 (prod) before IoT message volume and data egress; the provider-evaluation figure above (USD 250–400) excluded those shared network costs. Cost levers are listed in the deployment guide.

Until these are provided, `infra/terraform` is validated (`terraform validate`, `fmt`) and `plan` is documented, but **no live
deployment is claimed**. The platform runs end-to-end locally with Docker Compose (PostgreSQL, Redis, EMQX) using the same images.
