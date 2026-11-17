# Database production gate

HarambeeOne must not hold real learner, guardian, staff, donor or financial data until every mandatory gate below has current evidence. Passing application tests alone is not production approval.

## Automated gate

Production must use the Supabase CA certificate downloaded from the production project's database SSL settings:

```powershell
$env:NODE_ENV='production'
$env:DATABASE_SSL_MODE='verify-full'
$env:DATABASE_SSL_ROOT_CERT='C:\secure\supabase-prod-ca.crt'
pnpm.cmd db:verify-production
```

The command fails if the database is not writable, either database transport leg is unencrypted, configured statement controls are not active, the schema is not at the expected migration head, tenant RLS or revoked Data API grants are missing, immutable evidence or retry constraints are missing, tenant-owned data is inconsistent, or sealed financial equations fail.

Never commit the certificate, database URLs, passwords or command output containing credentials. Runtime and migration credentials belong in the deployment platform's managed secret store.

## Provider controls requiring operator evidence

- Use a separate paid production Supabase project; never promote the development or E2E database in place.
- Enable Database SSL Enforcement. Schedule the short database restart and rerun the automated gate afterward.
- Enable Network Restrictions for the fixed production egress addresses. Retain emergency-access and rotation procedures.
- Enable PITR or an approved backup tier whose retention meets the school's recovery-point objective.
- Restore a chosen recovery point into a separate project. Verify migration head, object-storage recovery, record counts, tenant boundaries, financial control totals and authentication configuration. Record restore duration and data-loss window.
- Configure database, pooler, disk, CPU, memory, slow-query, lock-wait and connection-exhaustion alerts with named responders.
- Size `DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW` across the maximum API replica count, leaving capacity for Supabase Auth, administrative access and recovery operations.
- Rotate runtime and migration database credentials before go-live. Keep migration credentials unavailable to the running API.
- Run Supabase Security Advisor and resolve every applicable warning. Retain an independent penetration-test report and remediation evidence.

## Current evidence · 2026-11-17

| Control | Status | Evidence |
| --- | --- | --- |
| Backend regression | Pass | 131 tests pass |
| Static validation | Pass | Ruff passes for backend source, tests and verification scripts |
| Migration integrity | Pass | Configured database reports Alembic head `f2b71a6c9d40` |
| Tenant and financial schema controls | Pass | Consolidated verifier passes RLS, grants, tenant consistency, immutability, retry, audit and exact financial checks |
| Bounded runtime connections | Pass in code | Configurable pool, pre-ping, recycle, acquisition/connect/query/lock/idle-transaction timeouts and rollback-on-failure are enforced |
| Verified TLS | **Fail** | PostgreSQL reports the pooler-to-database connection is not encrypted; enable Supabase SSL Enforcement, install the CA, select `verify-full`, then rerun |
| Network restrictions | Not evidenced | Requires Supabase dashboard configuration and retained proof |
| PITR and restore drill | Not evidenced | Requires plan selection and a successful restore into a separate project |
| Capacity and pool budget | Not evidenced | Requires representative load test and production replica assumptions |
| Independent review | Not evidenced | Requires an external security reviewer and remediation record |

The database is not approved for real school data while any mandatory row is failed or lacks evidence.
