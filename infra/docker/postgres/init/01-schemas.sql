-- Runs once on first start of the postgres container (docker-entrypoint-initdb.d).
-- Mirrors what alembic revision 0001 does on PostgreSQL so that psql users see the schemas even before migrations run,
-- and creates the restricted role used for PII access in production-like setups.
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS pii;
CREATE SCHEMA IF NOT EXISTS ts;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- PII is never readable by PUBLIC; only the owner (the app user) and explicitly granted roles.
REVOKE ALL ON SCHEMA pii FROM PUBLIC;

-- Read-only reporting role for local analytics; excluded from pii by default.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kifaru_readonly') THEN
    CREATE ROLE kifaru_readonly NOLOGIN;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA core, ts TO kifaru_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT SELECT ON TABLES TO kifaru_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA ts GRANT SELECT ON TABLES TO kifaru_readonly;
