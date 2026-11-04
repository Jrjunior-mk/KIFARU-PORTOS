# Vercel demo hosting (live: https://kifaru-portos.vercel.app)

The Vercel deployment is a **demo configuration**, not the production architecture (which is AWS ECS + RDS + IoT Core,
see `docs/02-architecture/cloud-architecture.md` and `docs/06-operations/deployment-guide.md`). It exists so the
platform can be shown and used without any cloud account beyond a Vercel hobby plan.

## How it is wired

| Part | On Vercel |
|---|---|
| Web app | `apps/web` built by Vite into static files (`vercel.json` `buildCommand`/`outputDirectory`); SPA fallback rewrite to `index.html`. |
| API | `api/index.py` exposes the FastAPI app as a Python serverless function; `/api/*`, `/health`, `/docs`, `/openapi.json` are rewritten to it. Local packages are imported via `sys.path`; third-party deps from `requirements.txt`. |
| Database | Without a hosted database each function instance creates `/tmp/kifaru.db` (SQLite) and seeds it on cold start. Seeded rows use deterministic ids (`seed.stable_id`) so every instance agrees on users, stations and vehicles and tokens work across instances, but **runtime data (simulated passes, shipments, refresh sessions) is per instance and ephemeral**. To make it durable: Vercel dashboard → project → Storage → Create Database (Neon Postgres, free tier) → connect to the project. The API picks up the injected `DATABASE_URL`/`POSTGRES_URL` automatically (`api/index.py`); redeploy once. |
| Live updates | Vercel functions cannot hold WebSockets. The web app is built with `VITE_WS_DISABLED=1` and polls `GET /api/v1/events/recent` every 5 s instead (`apps/web/src/hooks/useLiveEvents.ts`). |
| Workers | No background processes. Forecasts, release predictions and the security scan run on request (`GET /queue/{id}/forecast`, `POST /shipments/{id}/predict-release`) instead of on a schedule. |
| Session lifetime | `KIFARU_ACCESS_TOKEN_MINUTES=240` on the demo because refresh sessions live in the per-instance database; with a hosted database the 15-minute default can be restored. |
| Secrets | `KIFARU_JWT_SECRET`, `KIFARU_SIGNING_SEED_B64`, `KIFARU_PII_KEY_B64`, `KIFARU_SIGNING_KEY_ID`, `KIFARU_PUBLIC_BASE_URL`, `KIFARU_SEED_ACCOUNTS_JSON` (the demo accounts, as a secret environment variable — never in the repository). |

## Deploying

```bash
npx vercel link --scope <team> --project kifaru-portos      # once; then reset "Root Directory" to empty in the
                                                             # project settings if Vercel auto-detected apps/api
npx vercel env add KIFARU_... --environment production       # each variable above (also for preview)
npx vercel deploy --prod
```

Known pitfall: `vercel link` auto-detects the FastAPI app and sets the project Root Directory to `apps/api`, which
makes the build fail with `cd: apps/web: No such file or directory`. Clear the Root Directory (project settings or
`PATCH /v9/projects/{id}` with `rootDirectory: null`) and redeploy.

## Limits to be aware of

- Hobby plan: 60 s maximum function duration (the simulator caps at 50 passes per call), cold starts of ~1–2 s while
  NumPy/SciPy load and the database is seeded.
- Preview deployment URLs (`*-<team>.vercel.app` hashes) are protected by Vercel Authentication; the production
  domain is public.
- Because the database is per-instance, a user may occasionally see a freshly seeded database after a cold start.
