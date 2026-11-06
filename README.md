# HarambeeOne

<p align="center">
  <img src="apps/web/public/harambeeone-logo.png" alt="HarambeeOne logo" width="112" />
</p>

<p align="center">
  <strong>One reliable financial record for every learner.</strong><br />
  A bursar-first school finance platform for Uganda, with privacy-preserving learner support.
</p>

HarambeeOne brings learner billing, payments, requirements, receipts, reconciliation, arrears, and financial reporting into one accountable workspace. Its core is an immutable learner ledger: balances are calculated from traceable financial entries instead of being stored as unexplained totals.

The project also includes **Harambee Support**, an isolated workflow that lets a school turn a verified learner obligation into an anonymous, consent-controlled support campaign. Donations are never treated as received until the school independently verifies settlement and the learner ledger is updated atomically.

> [!IMPORTANT]
> HarambeeOne is an actively developed MVP, not a production payment processor. Real-money use still requires licensed payment-provider integrations, operational controls, backups, security review, and Ugandan privacy and legal review.

## Product scope

The active product serves the school bursar and the minimum learner, guardian, and school structure needed for finance.

### Implemented

- Supabase email/password and Google authentication.
- Tenant-scoped owner, bursar, cashier, and auditor permissions.
- Institution onboarding, Ugandan school structures, classes, and optional streams.
- Academic years and terms with draft, open, closing, closed, and controlled-reopen states.
- Learner registration, guardian records, import, placement, status changes, and transfers.
- Flexible fee plans by class, stream, boarding status, or selected learners.
- Fixed-amount and percentage installments.
- Monetary, physical, mandatory, optional, and candidate-specific requirements.
- Conflict-aware billing previews and atomic, idempotent publication.
- Learner-specific additions, discounts, sponsorship credits, and waivers.
- Chronological learner statements with running balances and CSV export.
- Payment recording, allocations, receipt views, arrears, statement reconciliation, and collections reporting.
- Immutable ledger controls, tenant-aware row-level security, and financial audit events.
- Anonymous Harambee Support campaigns backed by verified learner obligations.
- Guardian invitations, scoped consent, learner-assent handling, and consent withdrawal.
- Optional privacy-minimized Gemma review with mandatory human publication approval.
- Public campaign discovery, pledge tracking, verified settlement posting, and redacted outcomes.

### In progress

The current delivery priority is **Slice 8, Phase 8: final verification**. Reports, period closing, balance carry-forward, learner rollover, and controlled reopening are complete. The final phase will prove the complete bursar journey, financial equation, historical reproducibility, exports, security boundaries, and production controls.

See the [MVP roadmap](docs/MVP_ROADMAP.md) and [Support expansion plan](docs/HARAMBEE_SUPPORT_EXPANSION_PLAN.md) for completion gates and current evidence.

### Deferred

The following areas remain outside the active product until the bursar completion gate passes:

- General sponsor and programme administration.
- Production Stellar or Soroban settlement.
- Academic grading, attendance, teaching, payroll, and procurement.
- Automated SMS, WhatsApp, SchoolPay, bank, and mobile-money integrations.
- Mainnet assets or direct custody of school funds.

Some deferred screens and prototypes remain in the repository as design and migration references. They must not be treated as production functionality.

## How the system works

### Bursar workflow

```text
Create institution
  -> Configure classes and streams
  -> Open an academic period
  -> Register or import learners
  -> Configure fees and requirements
  -> Preview and publish learner bills
  -> Receive and allocate payments
  -> Issue receipts
  -> Reconcile provider and bank records
  -> Follow up arrears
  -> Produce accountability reports
  -> Close the period and carry balances forward
```

### Harambee Support workflow

```text
School identifies a real overdue obligation
  -> School privately refers the learner
  -> Verified guardian reviews the privacy notice
  -> Guardian gives or declines scoped consent
  -> Capable learner's view is recorded
  -> Private case is reviewed by the school
  -> Owner approves anonymous publication
  -> Donor records a pledge to a school-controlled channel
  -> School independently verifies settlement
  -> Payment, allocation, ledger credit, receipt, and audit event post together
  -> Donor and guardian receive privacy-safe status and outcome information
```

Campaign money must never be sent to a guardian or learner. A target cannot exceed the associated live obligation, pending pledges do not count as funded, and public responses must not expose learner or guardian identity.

## Architecture

```text
                           +----------------------+
                           | Supabase Auth        |
                           | email, Google, JWT   |
                           +----------+-----------+
                                      |
+--------------------+      +---------v----------+      +----------------------+
| Next.js web app    +----->+ Server API gateway +----->+ FastAPI application  |
| staff and portals  |      | session forwarding |      | RBAC and workflows   |
+--------------------+      +--------------------+      +----------+-----------+
                                                                  |
                                                       +----------v-----------+
                                                       | Supabase PostgreSQL  |
                                                       | ledger, RLS, audit   |
                                                       +----------------------+

Signed-out donors -> restricted public gateway -> anonymous Support endpoints
Gemma review      -> server-only Google API call -> validated, redacted response
```

### Financial invariants

- PostgreSQL is the authoritative source of school financial truth.
- Money uses exact decimal values; floating-point values are not used for ledger writes.
- Posted financial history is corrected with new reversal or adjustment entries, not deletion.
- Billing publication uses a preview hash and idempotency key to prevent stale or duplicate posting.
- Every school-owned operational record is tenant-scoped.
- Every consequential financial action records an authenticated actor.
- Closed periods reject ordinary enrollment and financial mutations.
- AI may explain, summarize, or flag; it cannot approve publication or mutate finance directly.
- Personally identifiable learner information must never be placed on a public blockchain.

## Technology stack

| Layer | Technology | Purpose |
| --- | --- | --- |
| Web | Next.js 15, React 19, TypeScript | Staff workspace, guardian portal, donor portal, and API gateway |
| Authentication | Supabase Auth and `@supabase/ssr` | Email/password, Google OAuth, server-managed sessions |
| API | FastAPI, Pydantic, SQLAlchemy | Active business workflows and authorization |
| Database | Supabase PostgreSQL | Financial ledger, tenant data, RLS, triggers, and audit evidence |
| Migrations | Alembic | Versioned database changes and security policies |
| AI | Gemma 4 through the Gemini API | Optional, consented, privacy-minimized case review |
| Tooling | pnpm, uv, Ruff, Pytest, ESLint | Reproducible development and verification |
| Deferred protocol | Rust and Soroban SDK | Experimental post-bursar education-funding contract |

The NestJS/Prisma application under `apps/api` is a legacy migration reference. New operational endpoints belong in the FastAPI service.

## Repository layout

```text
HarambeeOne/
|- apps/
|  |- web/                 # Active Next.js application
|  |- backend/             # Active FastAPI application and Alembic migrations
|  `- api/                 # Legacy NestJS/Prisma reference
|- packages/
|  |- shared/              # Small shared TypeScript vocabulary
|  `- soroban/             # Deferred experimental contract
|- docs/                   # Roadmap, architecture, security, and integration notes
|- scripts/                # Repository setup helpers
|- SUPPORT/                # Product documents, diagrams, and brand assets
|- docker-compose.yml      # Optional local PostgreSQL, Redis, and RabbitMQ services
`- AGENTS.md               # Mandatory repository working rules
```

## Prerequisites

- Node.js 22 or newer.
- pnpm 9.15 or a compatible pnpm 9 release.
- Python 3.12.
- [uv](https://docs.astral.sh/uv/).
- A Supabase project for authentication and the PostgreSQL database.
- A Google AI Studio API key only when testing the optional Gemma integration.

Redis and RabbitMQ are present in the local Compose file for planned background work, but they are not required by the current request path.

## Local setup

1. Clone the repository and enter the project directory.

   ```bash
   git clone https://github.com/RockieRaheem/HacktoberFest-HarambeeOne.git
   cd HacktoberFest-HarambeeOne/HarambeeOne
   ```

2. Create the local environment file.

   ```bash
   cp .env.example .env
   ```

   PowerShell equivalent:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Configure at least these values in `.env`:

   ```dotenv
   API_URL=http://localhost:4100
   NEXT_PUBLIC_SUPABASE_URL=https://PROJECT_REF.supabase.co
   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_REPLACE_ME
   SUPABASE_URL=https://PROJECT_REF.supabase.co
   DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:PASSWORD@POOLER_HOST:5432/postgres
   MIGRATION_DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:PASSWORD@POOLER_HOST:5432/postgres
   ```

   Optional Gemma configuration:

   ```dotenv
   GEMINI_API_KEY=replace-with-a-server-only-key
   GEMMA_MODEL=gemma-4-26b-a4b-it
   ```

   Never expose database credentials, service-role keys, or `GEMINI_API_KEY` through a `NEXT_PUBLIC_*` variable.

4. Install the JavaScript and Python dependencies.

   ```bash
   pnpm install
   uv python install 3.12
   uv sync --directory apps/backend
   ```

5. Apply database migrations.

   ```bash
   pnpm db:migrate
   ```

6. Start the active web and API applications.

   ```bash
   pnpm dev
   ```

   | Service | Address |
   | --- | --- |
   | Web application | <http://localhost:3000> |
   | FastAPI service | <http://localhost:4100> |
   | API documentation | <http://localhost:4100/docs> |
   | Liveness | <http://localhost:4100/health> |
   | Database readiness | <http://localhost:4100/health/readiness> |

## Supabase authentication

Email/password authentication works after the public Supabase URL and publishable key are configured.

To enable Google sign-in:

1. Create a Google OAuth 2.0 web client.
2. Add `http://localhost:3000` as an authorized JavaScript origin.
3. Add `https://PROJECT_REF.supabase.co/auth/v1/callback` as the Google redirect URI.
4. Enable Google in **Supabase Authentication -> Sign In / Providers**.
5. Set the Supabase site URL to `http://localhost:3000`.
6. Add `http://localhost:3000/auth/callback` to the allowed redirect URLs.
7. Add equivalent HTTPS origins and redirects before production deployment.

Authorization is derived from database relationships such as `school_memberships` and verified guardian links. It must never depend on editable Supabase `user_metadata`.

## Useful commands

Run commands from the repository root unless stated otherwise.

```bash
# Start the active web and FastAPI applications
pnpm dev

# Start one application
pnpm dev:web
pnpm dev:api

# Backend tests and lint
pnpm --filter @harambeeone/backend test
pnpm --filter @harambeeone/backend lint

# Frontend lint and production build
pnpm --filter @harambeeone/web lint
pnpm --filter @harambeeone/web build

# Database lifecycle
pnpm db:revision
pnpm db:migrate
pnpm db:seed
```

The backend suite covers the complete bursar journey: tenant authorization, school structure, period lifecycle, learner and guardian registration, controlled billing, targeted requirements, payments and receipts, reconciliation and cash-up, arrears follow-up, reports and exports, closing, carry-forward, rollover, controlled reopening, Support privacy boundaries, Gemma validation, duplicate prevention, and rollback behavior.

## Database verification

Alembic migrations contain the PostgreSQL row-level security policies, private helper functions, constraints, indexes, audit triggers, and immutable-ledger controls. The scripts under `apps/backend/scripts` verify these PostgreSQL-specific guarantees against a configured Supabase database.

Examples:

```bash
uv run --directory apps/backend python scripts/verify_tenant_security.py
uv run --directory apps/backend python scripts/verify_academic_periods.py
uv run --directory apps/backend python scripts/verify_controlled_billing.py
uv run --directory apps/backend python scripts/verify_learner_accounts.py
uv run --directory apps/backend python scripts/verify_portal_roles.py
uv run --directory apps/backend python scripts/verify_support.py
uv run --directory apps/backend python scripts/verify_bursar_completion.py
```

Operational verification scripts may require `SUPABASE_TEST_ACCESS_TOKEN` for a dedicated signed-in test user. Verification scripts use rollback transactions where documented; inspect a script before running it against any shared environment.

## Security and privacy

HarambeeOne handles financial records and children's personal data. Security and privacy are therefore product behavior, not deployment afterthoughts.

- Browser code receives only the Supabase publishable key.
- The API verifies the Supabase session independently.
- Operational authorization is server-derived and tenant-scoped.
- Sensitive tables use PostgreSQL RLS and restricted Data API grants.
- Guardian portal access is created through expiring, hashed, single-use invitations.
- Support publication requires anonymous-publication consent and an acceptable learner-assent state.
- Gemma and cross-border processing require separate consent.
- Public campaign text and model output are checked for learner identifiers.
- Withdrawal stops new fundraising while preserving required financial and audit history.
- Production use requires MFA, secrets management, backup restoration exercises, incident procedures, provider webhook verification, and independent security testing.

Read [Security and privacy](docs/SECURITY.md) and the legal safeguards in the [Support expansion plan](docs/HARAMBEE_SUPPORT_EXPANSION_PLAN.md) before handling real learner information.

## Engineering rules

Before changing code, database objects, configuration, documentation, or interfaces:

1. Read [AGENTS.md](AGENTS.md) and [docs/MVP_ROADMAP.md](docs/MVP_ROADMAP.md) in full.
2. Work on the first incomplete authorized slice unless the user explicitly changes priority.
3. Build a complete vertical workflow, including authorization, audit, loading, empty, error, and success states.
4. Add migrations and indexes instead of manually changing production data.
5. Verify success, validation, tenant isolation, duplicate submission, retry, and rollback behavior.
6. Run the relevant backend tests, lint, frontend checks, production build, and database verification.
7. Update roadmap evidence only when every completion gate passes.
8. Commit one coherent change before beginning another slice.

Do not use sponsor or blockchain work to bypass the bursar completion gate.

## Documentation

- [Developer handoff](docs/DEVELOPER_HANDOFF.md)
- [Canonical MVP roadmap](docs/MVP_ROADMAP.md)
- [Repository guide](docs/REPOSITORY_GUIDE.md)
- [Harambee Support expansion plan](docs/HARAMBEE_SUPPORT_EXPANSION_PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security baseline](docs/SECURITY.md)
- [Integration notes](docs/INTEGRATIONS.md)
- [API overview](docs/API_OVERVIEW.md)

The roadmap is authoritative when older product documents or design artifacts describe a broader system.

## License

HarambeeOne is released under the [MIT License](LICENSE).
