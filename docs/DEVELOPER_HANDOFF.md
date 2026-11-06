# HarambeeOne Developer Handoff

**Handoff date:** 25 October 2026

**Verified branch:** `master`

**Verified commit:** `dde2fad` (`Verify complete bursar workflow`)

**Current database head:** `a72d5e8c19f4`

## 1. What HarambeeOne is

HarambeeOne is a tenant-isolated school finance platform designed around the work of a Ugandan school bursar. Its financial ledger is the source of truth for what each learner was charged, what was paid, how a payment was allocated, what remains outstanding, and how those figures were reconciled and reported.

The application also contains Harambee Support, a privacy-preserving assistance workflow. A verified learner obligation can become an anonymous public support campaign after guardian consent, appropriate learner assent, optional Gemma review, and human approval. Contributions are not counted as funded until the school verifies settlement and posts the value to the learner's account.

HarambeeOne is not a general school-management system. Academic grading, attendance, teaching, payroll, procurement, and broad school administration are outside its current boundary.

## 2. The problem being solved

Many schools still manage fees, requirements, receipts, provider statements, and arrears across paper books and disconnected spreadsheets. This makes it difficult to answer basic questions reliably:

- What exactly does this learner owe?
- Was a payment allocated to fees, a uniform, examinations, or another requirement?
- Does the school ledger agree with bank, Mobile Money, SchoolPay, and cashier evidence?
- Can a receipt, adjustment, closed-term balance, or support contribution be independently traced?
- Can a learner move between school sections without rewriting financial history?

HarambeeOne provides one controlled workflow from school setup through term close. Financial history is append-only: corrections use traceable reversals, credits, refunds, or controlled reopening instead of silently editing posted evidence.

## 3. Active architecture

```text
Browser
  -> Next.js 15 / React 19 application
  -> same-origin authenticated Next.js gateway
  -> FastAPI workflow and authorization service
  -> Supabase PostgreSQL ledger, RLS, constraints, triggers, and audit evidence

Supabase Auth
  -> email/password and Google identity
  -> FastAPI resolves operational access from school membership

Gemini API
  -> optional Gemma 4 assistance and case review
  -> consented, privacy-minimized, structured, and always subordinate to human decisions
```

The active runtime is only:

- `apps/web` — Next.js interface, authentication routes, portals, and server gateway.
- `apps/backend` — FastAPI endpoints, SQLAlchemy models, Alembic migrations, tests, and live database verification.

Do not add new operational features to `apps/api`; it is a legacy NestJS/Prisma reference. `packages/soroban` is a deferred experiment, while `SUPPORT` and `stitch_harambeeone_education_finance_platform` contain source material and visual references rather than production code.

## 4. Financial and security rules that must remain true

- Use `Decimal` in Python and `numeric(18,2)` in PostgreSQL for money.
- The canonical equation is `opening balance + net assessed - net collected = closing balance`.
- Ledger entries explain the learner balance and must not be destructively edited.
- Supabase establishes identity; submitted `school_id` values never establish authority.
- FastAPI derives the active school and permissions from `school_memberships` and resource ownership.
- Every school-owned query and mutation is tenant-scoped.
- Consequential actions record the authenticated actor in audit evidence.
- Browser code may receive only publishable Supabase configuration. Database credentials, service-role credentials, and `GEMINI_API_KEY` remain server-side.
- Retryable financial commands require idempotency protection and atomic transactions.
- Closed-period evidence is immutable. Later corrections use controlled, hash-linked evidence.
- Personally identifiable learner information must not enter public campaigns or unnecessary AI prompts.

## 5. What is implemented

### Authentication, tenancy, and staff access

- Supabase email/password and Google authentication entry points.
- Server-owned Google OAuth PKCE callback handling.
- Owner, bursar, cashier, and auditor permissions with least privilege.
- Explicit multi-unit workspace selection for organizations with multiple school sections.
- Email-bound, expiring, single-use staff invitations; role changes and revocation.
- API authorization, PostgreSQL RLS, restricted Data API grants, and actor-aware audit records.

### Institution structure and learner registry

- One operational workspace per day-care, nursery, primary, O-Level, or full-secondary section.
- Ugandan class presets with editable names, canonical codes, ordering, and optional streams.
- Safe deletion of genuinely unused classes and protection of classes with learner or financial history.
- Learner registration, guardians, placement, import, status changes, and historical movement.
- Organization-stable learner identities and consented transfers between linked sections.

### Academic periods

- Academic years and terms with editable Uganda-oriented defaults.
- Draft, open, closing, and closed lifecycle states.
- One operational period per school and consistent period selection across bursar workflows.
- Closed-period mutation protection and activity-aware deletion rules.
- Immutable close snapshots with deterministic hashes.
- Exact balance carry-forward, controlled learner rollover, and owner-only controlled reopening.

### Fees and requirements

- Fee categories and flexible plans targeted by class, stream, boarding status, or selected learners.
- Any number of fixed-amount or percentage installments.
- General class fees that automatically apply once to newly registered or first-placed learners.
- Monetary and physical requirements, including class-specific and candidate-only needs.
- Optional purchases such as uniforms, meals, transport, trips, and learning materials.
- Learner additions, discounts, waivers, and explicit reasoned scholarships.
- Conflict-aware billing preview and atomic, idempotent publication.

### Learner accounts and collections

- A chronological learner statement with opening and carried balances, charges, requirements, payments, credits, waivers, discounts, reversals, refunds, and running balance.
- Printable and CSV learner statements with limited guardian and payer context.
- Obligation-first payment desk with learner search and school-configured channels.
- Split allocation across fees, requirements, and learner credit.
- Sequential official receipts, controlled reprints, and evidence-preserving corrections.
- Cash and electronic collection support, including bank, Mobile Money, and SchoolPay references.

### Reconciliation and cash-up

- Server-validated statement imports with duplicate-content and retry protection.
- Explainable match suggestions and controlled confirm, reject, and undo actions.
- Unidentified-funds handling without inventing learner allocations.
- Daily cashier batches, cash-receipt inclusion, deposits, submission, and supervisor decisions.
- Pre-close controls for unresolved statement items, provider variance, unsigned cash-up, unbatched cash, allocation imbalance, and unallocated learner credit.

### Arrears and reporting

- Exact current, 1–30, 31–60, 61–90, and 90+ day aging.
- Period, class, stream, residence, category, and priority filters.
- Guardian follow-up history, promises to pay, automatic promise evaluation, and next actions.
- Printable worklists, statements, and CSV exports.
- Sixteen operational and control reports covering collections, balances, aging, billing, requirements, adjustments, corrections, reconciliation, cash-up, deposits, and billing versus collection.
- Screen, print, and CSV output derived from the same server-calculated rows and totals.

### Term close and rollover

- Server-owned readiness checklist that cannot be bypassed by the browser.
- Atomic close transaction with learner rows, school totals, control evidence, actor, timestamp, and deterministic evidence hash.
- Idempotent close retries and full rollback on partial failure.
- Exact debt and learner-credit carry-forward into the immediate next period.
- Reviewed continue, promote, repeat, hold, complete, or depart decisions for every active learner.
- Owner-controlled corrections that preserve the original close and create hash-linked revisions.

### Harambee Support

- Arrears-derived school referrals routed to verified guardian accounts.
- Versioned privacy notice, authority checks, consent, age-sensitive learner assent, refusal, and withdrawal.
- Guardian-authored private support cases tied to exact live obligations.
- School review, requested changes, owner approval, and anonymous publication.
- Institution-owned SchoolPay, bank, and Mobile Money payment destinations; parent accounts are not donation destinations.
- Guest and authenticated-donor pledges, independent settlement verification, learner-ledger posting, school receipts, reversals, and reissues.
- Guardian, donor, and school notifications with read state, deep links, deduplication, and an outbox.
- Private guardian acknowledgements and owner-approved anonymous outcomes for donors.
- Guardian and donor Gemma assistants with explicit consent, minimal role-scoped facts, structured responses, prompt-injection and identity-leak checks, no retained conversation content, and rate limiting.

### Enterprise interoperability

- Legal organizations separated from operational school sections.
- Versioned `harambeeone.v1` learner and transfer resources with stable identifiers and canonical education codes.
- Purpose-limited, hashed, rotatable, revocable service credentials.
- Data minimization, scopes, rate limits, idempotent inbound imports, and conflict quarantine.
- Signed HTTPS webhooks, durable outbox delivery, retry evidence, and owner review tools.
- Transfers preserve the source section's ledger and create a new target placement rather than moving historical finance records.

## 6. Current verification state

At this handoff, all eight bursar delivery slices are complete.

- 111 backend tests pass.
- Ruff passes across backend source, tests, migrations, and verification scripts.
- Frontend ESLint and TypeScript validation pass.
- The optimized Next.js production build passes with 51 routes.
- Alembic has one head: `a72d5e8c19f4`.
- `verify_bursar_completion.py` passes against the configured live Supabase database.
- The final verifier checks tenant isolation, revoked Data API grants, idempotency constraints, immutable-evidence triggers, financial equations, snapshot aggregation, audit actors, and carry-forward totals across 34 operational tables.
- `master` was clean and synchronized with `origin/master` at commit `dde2fad`.

The canonical evidence and progress history are in `docs/MVP_ROADMAP.md`. Do not replace that evidence with assumptions based on an old interface, source document, or mock-up.

## 7. What remains

The bursar product is complete at its current roadmap boundary. Remaining work is deliberately ordered as follows.

### Next: sponsor onboarding and programme administration

Turn the existing sponsor demonstration area into a controlled production workflow:

1. Register and verify sponsor organizations without mixing them with school tenants.
2. Add sponsor users and least-privilege programme roles.
3. Create programmes with currency, budget, dates, purpose, eligible obligation types, supported schools or sections, and privacy rules.
4. Add draft, review, approved, active, suspended, closed, and cancelled lifecycle controls.
5. Require school-side review where a programme interacts with learner obligations.
6. Provide sponsor and school views for programme budget, reserved value, settled value, remaining value, beneficiaries, exceptions, and outcomes.
7. Record every approval, status change, allocation decision, and financial consequence in immutable audit evidence.
8. Add RLS, restricted grants, indexes, uniqueness constraints, idempotency, retry behavior, and atomic rollback tests.

The first implementation must not send money or write blockchain records. It should establish trusted sponsor identities and controlled programme definitions before beneficiary allocation or settlement is introduced.

Suggested completion gate:

- An authorized sponsor administrator can create an organization and submit a programme.
- An authorized HarambeeOne or school reviewer can approve, request changes, suspend, or close it.
- Budgets and eligibility are exact, tenant-scoped, and immutable after activation except through audited amendments.
- Unauthorized, cross-tenant, duplicate, expired, and partial submissions are rejected.
- Loading, empty, validation, success, conflict, and recovery states work in both sponsor and school interfaces.
- Backend tests, Ruff, frontend lint, TypeScript, production build, migration, and a live Supabase verification script all pass.

### Then: beneficiary allocation and sponsor reporting

- Match approved programmes to verified learner obligations under explicit privacy and eligibility rules.
- Separate proposed, reserved, approved, settled, reversed, and expired allocations.
- Prevent duplicate funding and over-allocation across programmes and public Support campaigns.
- Give sponsors aggregate accountability by default; reveal learner data only when a documented lawful purpose and consent permit it.
- Produce school acknowledgements, sponsor statements, exception queues, and outcome reports from ledger evidence.

### Then: audited Stellar testnet settlement

- Treat the PostgreSQL ledger as financial authority and Stellar as independently verifiable settlement evidence.
- Use testnet only until custody, signing, recovery, reconciliation, fee, and failure controls have independent review.
- Link every transaction hash to an approved programme allocation and local settlement record.
- Make retries idempotent and distinguish submitted, confirmed, failed, reversed, and externally settled states.

### Then: fiat-delivery reconciliation and production validation

- Reconcile any on-chain movement with the actual bank, Mobile Money, SchoolPay, or school-account delivery.
- Add provider webhook verification, exception handling, and settlement reports.
- Complete threat modelling, penetration testing, backup restoration, incident-response exercises, data-retention review, legal review, and corridor-specific validation before considering mainnet or real-money custody.

## 8. Production-readiness work that remains outside feature completion

Passing the roadmap does not by itself authorize production use with real learner data or money. Before deployment, complete:

- Production domains, HTTPS, Supabase redirect URLs, and Google OAuth production configuration.
- MFA and stronger administrative session controls.
- Managed secret storage and credential rotation.
- Database backups with a tested restoration procedure.
- Error monitoring, metrics, structured logs, alerting, and uptime checks.
- Background-worker operation for outbox and provider retries where required.
- Verified provider integrations rather than manual confirmation alone.
- Rate limiting and abuse monitoring at the public edge.
- Privacy impact assessment, retention schedules, consent-form review, and Ugandan legal review.
- Independent security testing before handling real financial or child data.

## 9. How to run the project

### Prerequisites

- Node.js 22 LTS or another version proven compatible with Next.js 15.
- pnpm 9.15.
- Python 3.12.
- `uv`.
- A configured Supabase project.
- A Google AI Studio key only for optional Gemma features.

### Environment

Copy `.env.example` to `.env` and configure the values documented there. The important groups are:

- `DATABASE_URL` and `MIGRATION_DATABASE_URL` for PostgreSQL.
- `SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, and the Supabase publishable key.
- `API_URL` for the web-to-API path.
- `GEMINI_API_KEY` and `GEMMA_MODEL` for optional AI features.

Never commit `.env` or print its secrets in terminal output, logs, screenshots, tests, or documentation.

### Install and start

```powershell
pnpm.cmd install
uv sync --directory apps/backend
pnpm.cmd db:migrate
pnpm.cmd dev
```

The services are normally available at:

- Web: `http://localhost:3000`
- FastAPI: `http://localhost:4100`
- OpenAPI: `http://localhost:4100/docs`
- Liveness: `http://localhost:4100/health`
- Database readiness: `http://localhost:4100/health/readiness`

On Windows, use `npm.cmd` or `pnpm.cmd` if PowerShell blocks the `.ps1` launcher. Do not weaken the machine-wide execution policy just to start the project.

## 10. Required verification before a phase is complete

```powershell
# Backend
Set-Location apps/backend
uv --cache-dir .cache/uv run --no-sync python -m ruff check .
uv --cache-dir .cache/uv run --no-sync python -m pytest
uv --cache-dir .cache/uv run --no-sync python -m alembic heads

# Web
Set-Location ../web
pnpm.cmd lint
pnpm.cmd exec tsc --noEmit
pnpm.cmd build

# Live Supabase completion controls
Set-Location ../backend
uv --cache-dir .cache/uv run --no-sync python scripts/verify_bursar_completion.py
```

Run the new phase's targeted tests and live verification in addition to this baseline. A migration is not complete merely because it applies locally; verify PostgreSQL RLS, grants, constraints, indexes, triggers, and live behavior against the configured Supabase environment.

## 11. Contribution workflow

Before every change:

1. Read `AGENTS.md` and all of `docs/MVP_ROADMAP.md`.
2. Confirm the first incomplete authorized phase.
3. Inspect working code and preserve unrelated changes.
4. Define database, API, interface, authorization, audit, loading, empty, error, success, retry, and rollback behavior.
5. Implement one complete vertical workflow rather than isolated screens.
6. Add a new Alembic migration for persistent schema changes; never edit production data manually as the implementation.
7. Test success, validation, authorization, tenant isolation, duplicate submission, retry, and partial failure.
8. Run the full verification appropriate to the risk.
9. Update roadmap status only after every completion gate passes.
10. Commit the coherent phase with one concise, single-line commit message.

Do not begin the following phase while tests fail or required behavior is incomplete.

## 12. Recommended starting point for the next developer

Start with a discovery pass over:

- `apps/backend/src/harambeeone_api/sponsors.py`
- Sponsor-related models in `apps/backend/src/harambeeone_api/models.py`
- `apps/web/app/sponsors`
- `apps/backend/tests` for existing authorization and finance test patterns
- Current sponsor references in `SUPPORT`
- `docs/MVP_ROADMAP.md`, `docs/ARCHITECTURE.md`, and `docs/SECURITY.md`

The existing sponsor implementation is a reference, not proof that the next phase is complete. Document the sponsor-domain lifecycle and authorization matrix first, add the next phase and completion gate to the canonical roadmap, then implement sponsor onboarding and programme administration end to end. Preserve the existing bursar and Harambee Support behavior throughout.

## 13. Key documentation

- `AGENTS.md` — mandatory working rules.
- `docs/MVP_ROADMAP.md` — authoritative delivery order and completion evidence.
- `docs/ARCHITECTURE.md` — runtime, financial authority, and automation boundaries.
- `docs/REPOSITORY_GUIDE.md` — active, legacy, reference, and generated areas.
- `docs/SECURITY.md` — security and privacy baseline.
- `docs/API_OVERVIEW.md` — API groups and authorization expectations.
- `docs/ENTERPRISE_INTEROPERABILITY_PLAN.md` — multi-unit, transfer, and exchange design.
- `docs/INTEGRATION_API.md` — versioned external exchange contract.
- `docs/HARAMBEE_SUPPORT_EXPANSION_PLAN.md` — Support consent, roles, settlement, notification, and AI boundaries.

When documents disagree, follow `AGENTS.md` and the current `docs/MVP_ROADMAP.md`.
