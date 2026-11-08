# HarambeeOne

<p align="center">
  <img src="apps/web/public/harambeeone-logo.png" alt="HarambeeOne logo" width="112" />
</p>

<p align="center">
  <strong>One reliable financial record for every learner.</strong><br />
  A bursar-first school finance platform for Uganda, with privacy-preserving learner support.
</p>

HarambeeOne brings learner billing, payments, requirements, receipts, reconciliation, arrears, and financial reporting into one accountable workspace. Its core is an immutable learner ledger: balances are calculated from traceable financial entries instead of being stored as unexplained totals.

The project also includes **Harambee Support**, an isolated workflow that lets a school turn a verified learner obligation into an anonymous, consent-controlled support campaign. Contributions are never treated as received until settlement is independently verified and the learner ledger is updated atomically: Solana transfers are checked server-side through RPC, while off-chain rails require school verification.

> **Solana Hackathon build -- SomaFund:** parents, relatives, diaspora family members, employers, and sponsors can collaboratively fund a verified school-fee obligation with devnet SOL. The donor signs from their own wallet; HarambeeOne verifies the transfer on Solana before crediting the learner's private school account. [See the complete Solana integration](#how-solana-is-used).

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

## How Solana is used

SomaFund uses Solana as the public payment and proof layer for collaborative school-fee support. It is not a decorative wallet connection or a simulated transaction table: a donor authorizes a real **devnet SOL transfer** to a school-controlled wallet, and the backend independently reads Solana RPC before any financial record is posted.

### End-to-end contribution flow

1. A guardian prepares a support request for a real learner balance and gives scoped publication consent.
2. The school reviews the request, approves any learner photo, completes the consented safety review, and publishes the campaign.
3. An institution owner registers and verifies the school's Solana devnet wallet; HarambeeOne never stores its private key.
4. A donor connects a Wallet Standard wallet such as Phantom or Solflare on the public campaign page.
5. The server creates a short-lived, idempotent checkout containing the verified recipient, exact lamports, anonymous campaign memo, and expiry time.
6. The web app uses `@solana/kit` and the System Program to build the exact SOL transfer, adds a Memo Program instruction, and asks the donor's wallet to sign and send it.
7. The backend fetches the transaction through Solana RPC and accepts it only when all of these checks pass:
   - the transaction succeeded and reached `confirmed` or `finalized`;
   - the connected donor address is an actual transaction signer;
   - the System Program transfer source and verified school destination match;
   - the transferred lamports equal the protected checkout amount exactly;
   - the Memo Program value matches the one-time campaign reference;
   - the signature has not already been used for another contribution.
8. Only after verification does one database transaction confirm the pledge, credit the learner obligation, update campaign totals, anchor the Solana signature and slot, issue the official school receipt, and write audit evidence.
9. The donor can open the transaction in Solana Explorer and safely retry confirmation if the transfer succeeded while the receipt request was interrupted. Idempotency and the unique signature constraint prevent double posting.

### Why Solana matters here

Ugandan school support often comes from many small contributors, including relatives abroad. Solana provides a fast, low-cost, globally accessible transfer rail and a public proof that a specific amount reached the school's published wallet. HarambeeOne supplies the missing institutional controls: the transfer is tied to a verified obligation, reconciled into the school ledger, and converted into an accountable receipt without putting a child's identity on-chain.

| Stored on Solana devnet | Kept private in Supabase PostgreSQL |
| --- | --- |
| Donor and school public wallet addresses | Learner and guardian identity |
| SOL amount and confirmation slot | Admission number, class, contacts, and photo |
| Anonymous campaign memo | Verified invoice and remaining balance |
| Public transaction signature | Consent evidence and private family context |
| Transaction success evidence | Allocation, school receipt, roles, and audit workflow |

This MVP deliberately uses **devnet** and the native System and Memo Programs; it does not deploy a custom program or claim production custody. The configured UGX-to-SOL quote is a fixed judging/demo value, not a market oracle. A production launch would require mainnet treasury governance, regulated fiat/off-ramp partners, live pricing, key-management controls, monitoring, and legal review.

### Judge demo path

1. Sign in as the institution owner and open **Harambee Support**.
2. Publish a guardian-submitted campaign after completing its consent and safety gates.
3. Add and verify a **Solana devnet wallet** under payment methods.
4. Open the campaign from the public support portal.
5. Connect a devnet Wallet Standard wallet funded from the Solana faucet.
6. Enter a whole-UGX contribution within the remaining verified balance and approve the exact devnet transaction.
7. Observe the confirmed slot, official receipt, learner-ledger credit, updated campaign total, and Solana Explorer link.

See the [SomaFund Solana build guide](docs/SOMAFUND_SOLANA_HACKATHON.md), [MVP roadmap](docs/MVP_ROADMAP.md), and [Support expansion plan](docs/HARAMBEE_SUPPORT_EXPANSION_PLAN.md).

### Deferred

The following areas remain outside the active product until the bursar completion gate passes:

- General sponsor and programme administration.
- Production mainnet custody, escrow, or token settlement.
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
  -> Donor signs an exact devnet SOL transfer to the verified school wallet
  -> HarambeeOne verifies signer, recipient, lamports, memo, status, and replay protection through RPC
  -> Payment, allocation, ledger credit, receipt, Solana proof, and audit event post together
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
+---------+----------+      +--------------------+      +----------+-----------+
          |                                                       |
          | donor signs transfer                                  v
          +----------------> Solana devnet             Supabase PostgreSQL
                             public signature          ledger, RLS, audit
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
| Solana | Kit, Wallet Standard, System Program | Devnet wallet connection, transfer, and public transaction proof |
| Tooling | pnpm, uv, Ruff, Pytest, ESLint | Reproducible development and verification |

## Repository layout

```text
HarambeeOne/
|- apps/
|  |- web/                 # Active Next.js application
|  - backend/              # Active FastAPI application and Alembic migrations
|- packages/
|  - shared/               # Shared TypeScript vocabulary
|- docs/                   # Roadmap, architecture, security, and integration notes
|- SUPPORT/                # Product documents, diagrams, and brand assets
|- docker-compose.yml      # Optional local PostgreSQL, Redis, and RabbitMQ services
- AGENTS.md                # Mandatory repository working rules
```

## Prerequisites

- Node.js 22 or newer.
- pnpm 9.15 or a compatible pnpm 9 release.
- Python 3.12.
- [uv](https://docs.astral.sh/uv/).
- A Supabase project for authentication and the PostgreSQL database.
- A Solana Wallet Standard browser wallet configured for devnet.
- A Google AI Studio API key only when testing the optional Gemma integration.

Redis and RabbitMQ are present in the local Compose file for planned background work, but they are not required by the current request path.

## Local setup

1. Clone the repository and enter the project directory.

   ```bash
   git clone https://github.com/RockieRaheem/SolanaHackathon.git
   cd SolanaHackathon
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
   API_URL=http://localhost:4101
   NEXT_PUBLIC_SUPABASE_URL=https://PROJECT_REF.supabase.co
   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_REPLACE_ME
   SUPABASE_URL=https://PROJECT_REF.supabase.co
   DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:PASSWORD@POOLER_HOST:5432/postgres
   MIGRATION_DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:PASSWORD@POOLER_HOST:5432/postgres
   NEXT_PUBLIC_SOLANA_CLUSTER=devnet
   NEXT_PUBLIC_SOLANA_RPC_URL=https://api.devnet.solana.com
   SOLANA_CLUSTER=devnet
   SOLANA_RPC_URL=https://api.devnet.solana.com
   SOLANA_DEMO_UGX_PER_SOL=750000
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
   | FastAPI service | <http://localhost:4101> |
   | API documentation | <http://localhost:4101/docs> |
   | Liveness | <http://localhost:4101/health> |
   | Database readiness | <http://localhost:4101/health/readiness> |

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

Hackathon work must preserve the bursar ledger, tenant, audit, and privacy gates even when the user explicitly prioritises the Solana slice.

## Documentation

- [SomaFund Solana Hackathon build](docs/SOMAFUND_SOLANA_HACKATHON.md)
- [Developer handoff](docs/DEVELOPER_HANDOFF.md)
- [Canonical MVP roadmap](docs/MVP_ROADMAP.md)
- [Harambee Support expansion plan](docs/HARAMBEE_SUPPORT_EXPANSION_PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security baseline](docs/SECURITY.md)
- [Integration notes](docs/INTEGRATIONS.md)
- [API overview](docs/API_OVERVIEW.md)

The roadmap is authoritative when older product documents or design artifacts describe a broader system.

## License

HarambeeOne is released under the [MIT License](LICENSE).
