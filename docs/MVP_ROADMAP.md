# HarambeeOne Bursar Implementation Plan

This is the canonical delivery plan for HarambeeOne. Read this file before making any code, database, configuration, or interface change. Work on only the first incomplete delivery slice, complete it end to end, verify every completion gate, update this document, and commit the finished slice before moving to the next one.

## Product boundary

HarambeeOne serves the school bursar. Every active feature must directly support learner billing, requirements, collections, receipts, reconciliation, arrears follow-up, financial reporting, or the minimum learner and school structure needed for those duties.

Sponsor administration and blockchain settlement remain deferred until the bursar completion gate passes. The user-authorized Harambee Support hackathon pilot is the sole exception: it is an isolated, privacy-preserving workflow backed by existing learner obligations and does not reopen general sponsor administration or blockchain settlement. Academic grading, attendance, teaching, payroll, procurement, and general school administration are outside the current product.

## Delivery discipline

For every slice:

1. Re-read this plan and confirm the slice is the first incomplete priority.
2. Inspect the existing implementation and preserve working behaviour.
3. Define database, API, interface, authorization, audit, loading, empty, error, and success behaviour before editing.
4. Implement the complete vertical workflow rather than isolated screens.
5. Add migrations and indexes where required; never edit production data manually as the implementation.
6. Test success, validation, authorization, tenant isolation, duplicate submission, retry, and rollback behaviour.
7. Run relevant backend tests, frontend checks, production builds, and database verification.
8. Update the status and evidence in this file only after the completion gate passes.
9. Commit the completed coherent change with one concise, single-line commit message.
10. Do not start the next slice while required work or failing verification remains in the current slice.

Money must use exact decimal values. Posted financial history must be corrected through traceable reversals or adjustments, never destructive edits. Every school-owned record must be tenant-scoped and every consequential financial action must be audited.

## Target bursar workflow

```text
Create school
  -> Configure classes and streams
  -> Open academic period
  -> Register or promote learners
  -> Configure fees and requirements
  -> Preview and publish learner bills
  -> Receive and allocate payments
  -> Issue official receipts
  -> Reconcile cash, bank and provider collections
  -> Follow up arrears
  -> Produce accountability reports
  -> Close the term and carry balances forward
```

## Current capability baseline

| Area | Current position | Gap to close |
| --- | --- | --- |
| Authentication | Supabase email/password and Google entry points exist | Operational APIs need consistent membership enforcement |
| School structure | School levels, classes, optional streams, and editable names exist | Period-aware controls must govern all downstream records |
| Learners | Registration, guardians, placement, import, status, and movement exist | Bulk progression and controlled period rollover are missing |
| Fees | Categories, class plans, and installments exist | Fixed 50/30/balance UI and uncontrolled publishing must be replaced |
| Requirements | Class targeting, assignment, fulfilment, and payment allocation exist | Requirements must appear in the unified learner obligation view |
| Payments | Recording, allocations, ledger entries, and receipts exist | Credits, reversals, refunds, and cashier controls are incomplete |
| Reconciliation | Statement import, suggestions, and confirmation exist | Duplicate protection, undo, unidentified funds, and cash-up are incomplete |
| Arrears | Overdue calculations and filters exist | Aging, follow-up history, promises, and exports are incomplete |
| Reports | Collections report exists | Control reports, statements, close reports, and exports are incomplete |
| Governance | Demonstration interface exists | Real roles and approval policies are not implemented |
| Settlement | Demonstration interface exists | Deferred until bursar operations are complete |
| Verification | Limited backend tests exist | Financial, authorization, frontend, and end-to-end coverage is insufficient |

## Ordered implementation slices

### Slice 1 - Tenant security and bursar authorization

Status: **COMPLETE**

Implement:

- Require a valid Supabase session for every operational API.
- Resolve the active school from `school_memberships`; do not authorize from a submitted `school_id` alone.
- Add owner, bursar, cashier, and auditor permissions with least privilege.
- Enforce school ownership in API queries and Supabase row-level security policies.
- Record the authenticated actor on every consequential audit event.
- Keep service-role or secret credentials out of browser code.

Completion gate:

- Unauthenticated requests return `401`.
- Authenticated users without permission return `403`.
- Cross-school reads and writes fail in API and database tests.
- Authorized workflows continue to work through the web application.
- Security-relevant Supabase guidance is checked against current official documentation.

Verification evidence:

- 26 backend tests pass, including unauthenticated, role, cross-school query, cross-school resource, cross-school write, and authenticated audit-actor cases.
- Ruff passes for backend source, tests, migrations, and verification scripts.
- Web lint and the optimized Next.js production build pass.
- Live Supabase is at Alembic head `5342e3f4519b`; tenant RLS, membership-role constraints, policy counts, and private helper privileges pass `verify_tenant_security.py`.
- Development smoke tests return `401` from both the same-origin gateway and direct Python API without a session, while the public health endpoint remains available.

### Slice 2 - Academic period lifecycle

Status: **COMPLETE**

Implement:

- School-owned academic years and terms with names, opening dates, closing dates, due dates, and statuses.
- Draft, open, closing, and closed lifecycle rules.
- One active operational period per school, with historical period selection.
- Configurable Uganda calendar defaults without hard-coded dates.
- Safe correction, close, and authorized reopen behaviour.
- Replace every hard-coded or manually duplicated period selector across the application.

Completion gate:

- Changing the active period changes dashboard, enrollment, fees, requirements, arrears, payments, and reports consistently.
- Closed periods reject ordinary mutations.
- Periods containing financial activity cannot be destructively deleted.

### Slice 3 - Controlled term billing

Status: **COMPLETE**

Implement:

- Flexible fee plans by class, stream where needed, boarding status, or selected learner group.
- Any number of fixed-amount or percentage installments.
- Monetary and physical requirements, including candidate-only P.7, S.4, and S.6 items.
- Optional items such as uniforms, transport, meals, trips, and other school-defined charges.
- Learner-specific additions, discounts, sponsorship credits, and waivers with reasons.
- A billing preview showing included learners, exclusions, conflicts, and exact totals.
- Atomic, idempotent publication that creates immutable learner charge entries exactly once.

Completion gate:

- A bursar can configure and publish a complete term bill to every eligible learner.
- Repeated submission cannot double-bill a learner.
- Preview totals equal posted ledger totals at learner, class, and school level.

### Slice 4 - Learner financial account

Status: **COMPLETE**

Implement:

- One chronological statement containing opening balances, charges, requirements, payments, allocations, discounts, waivers, credits, reversals, refunds, and carried balances.
- A running balance after every ledger entry.
- Clear separation between tuition, other charges, optional purchases, and physical requirements.
- Printable and downloadable learner statements.
- Guardian and payer context without exposing unnecessary personal information.
- Preserved history when a learner changes class, stream, status, or period.

Completion gate:

- Every displayed learner balance can be independently recalculated from immutable ledger entries.
- Statement totals agree with billing, payment, arrears, and reporting totals.

### Priority refinement - automatic general class fees

Status: **COMPLETE**

The user explicitly prioritized this refinement after Slice 4. Each class and academic period can have one general whole-class fee. After its controlled first publication, registering, importing, or first placing a learner in that class posts the same immutable fee automatically. A same-period move never silently adds a second class fee when a charge already exists; it is held for bursar review. Scholarships are explicit reasoned learner credits, cannot exceed the available posted balance, and still require controlled publication.

Completion gate:

- Duplicate general fees for the same class and period are rejected.
- New registrations and unbilled class placements inherit the published general fee exactly once.
- Existing same-period fee history is preserved during class movement without automatic double billing.
- A bursar can apply a scholarship explicitly, and over-crediting is rejected.

### Priority refinement - section-safe school structure

Status: **COMPLETE**

The user explicitly prioritized correcting mixed-level onboarding and empty-class deletion before further workflow work. A new bursar workspace now represents one operational section: day care, nursery, primary, O-Level, or full secondary. Empty classes can be removed when they only contain unused draft fee or requirement configuration; learner placement history and published billing history remain protected.

Completion gate:

- Onboarding rejects accidental primary-and-secondary combinations while preserving the valid S.1-S.6 secondary structure.
- Class summaries distinguish learners, draft configuration, and published history instead of treating every linked record as a learner.
- Deleting a genuinely unused class also removes its unused draft billing configuration atomically.
- Classes with learner placement or published financial history cannot be deleted and show the reason in the interface.

Verification evidence:

- Ruff passes and all 60 backend tests pass, including onboarding boundaries, draft cleanup, and learner-history protection.
- Web lint and the optimized 38-route Next.js production build pass.

### Priority refinement - multi-unit access and learner mobility

Status: **COMPLETE**

Model a legal school organization separately from its operational campus sections, give staff memberships access to one or more explicit units, and add consented, audited learner-transfer and interoperability workflows. Financial ledgers remain owned by their originating unit; transfers create a new target placement without rewriting source history. External exchange must use stable identifiers, canonical education codes, least-privilege service credentials, idempotency keys, an outbox/webhook delivery record, and purpose-limited data sharing.

The completion-gated design is maintained in `docs/ENTERPRISE_INTEROPERABILITY_PLAN.md`. Phase A provides organization-linked units, separate owner-created section setup, multi-unit memberships, workspace selection, and per-request server-side membership validation. Phase B adds section-specific, email-bound, 72-hour single-use staff invitations; least-privilege bursar, cashier, and auditor roles; protected owner access; role changes, revocation, and preserved audit history. Phase C adds guardian-authorized transfers between linked units, target-side review and placement, organization-stable learner identity, matching audit history, retry-safe acceptance, and strict preservation of the source ledger. Phase D adds purpose-limited service credentials, versioned canonical resources, idempotent inbound validation and quarantine, signed webhooks, retriable outbox delivery, and complete exchange evidence.

Verification evidence for Phase A:

- Ruff passes and all 63 backend tests pass, including explicit unit selection, cross-unit denial, and owner-created sibling sections.
- Web lint and the optimized 39-route Next.js production build pass.

Verification evidence for Phase B:

- Ruff passes and all 67 backend tests pass, including wrong-email rejection, expiry, replay prevention, non-owner denial, acceptance, role change, revocation, and owner protection.
- Web lint and the optimized 41-route Next.js production build pass.
- Live Supabase reached Alembic head `ce42d91f5a10`, and backend database readiness passes.

Verification evidence for Phase C:

- A dedicated Section transfers workspace covers source consent capture, target review, new admission and placement, rejection, cancellation, status history, and clear empty, loading, success, and error states.
- Acceptance creates a new section-owned learner account linked by an organization-stable identity, applies any published general class fee, marks the source learner transferred, and never copies or rewrites the source financial ledger.
- Ruff and all 71 backend tests pass, including consent enforcement, cross-organization denial, source-only initiation, target-only decisions, duplicate-admission rollback, matching audit events, source-ledger preservation, and idempotent acceptance retry.
- Web lint and the optimized 42-route Next.js production build pass.
- Live Supabase reached Alembic head `d719a24c6e31`, and backend database readiness passes.

Verification evidence for Phase D:

- Owners can create, rotate and revoke section-scoped service credentials with explicit scopes, field groups, purpose, lawful authority, expiry and per-minute rate limits; keys are stored as hashes and shown only when issued.
- Versioned `harambeeone.v1` learner and transfer exports preserve organization, unit, learner and transfer identifiers, canonical class codes, cursor pagination and enforced data minimization while recording a payload hash and correlation evidence for every exchange.
- Inbound learner references require idempotency keys, validate organization and stable identity boundaries, quarantine conflicts, preserve trusted records, and require explicit owner acknowledgement or rejection.
- Transfer changes enter a durable outbox and are delivered after commit through public HTTPS webhooks signed over timestamp plus raw payload. Delivery results, exponential retry state and controlled retries remain visible in the Connected systems workspace.
- Ruff and all 76 backend tests pass, including scoped export, minimization, audit evidence, scope and rate enforcement, rotation/revocation, import replay/conflict quarantine, source-record preservation, webhook signature verification, failure and retry.
- Web lint and the optimized 43-route Next.js production build pass.
- Live Supabase reached Alembic head `e84a1f03c9b2`; `verify_external_exchange.py` passed RLS, revoked Data API grants, owner policies, uniqueness constraints and delivery indexes.
- The external contract and receiver verification procedure are documented in `docs/INTEGRATION_API.md`.

### Priority override - Harambee Support pilot

Status: **COMPLETE**

This one-off override was explicitly authorized for the 2026 Wakiso hackathon. It does not change the next bursar priority, which remains Slice 5.

Implemented:

- Private, tenant-scoped support cases tied to a real learner ledger balance or monetary requirement.
- Scoped guardian consent, learner assent state, anonymous-publication enforcement, and separate consent for Gemma and cross-border processing.
- Gemma 4 multimodal review of pseudonymous facts and optional redacted evidence, with deterministic schema validation and mandatory human approval.
- A separate signed-out donor portal that exposes campaign codes, verified totals, pending totals, redacted AI findings, and anonymous outcome attestations without learner or guardian identity.
- Idempotent donor pledges with public tracking references; pending pledges never count as funded.
- Atomic settlement verification that rechecks the live obligation and creates the payment, learner allocation, ledger credit, receipt, audit record, and pending settlement commitment together.
- Tenant RLS, revoked Data API grants, immutable verified contributions, indexed lookups, public-text identity checks, and an MIT open-source license.

Completion gate:

- The full private-case-to-public-campaign-to-verified-learner-credit journey passes automated tests.
- Identity leakage, over-target support, duplicate references, cross-tenant access, unconsented publication, and partial settlement failure are rejected.
- The optimized web build includes the private school workspace, public donor portal, and public tracking gateway.
- The live Supabase migration and database security verification pass.

Verification evidence:

- Ruff passes and all 40 backend tests pass, including three Harambee Support end-to-end, validation, tenant, duplicate, and rollback tests.
- Web lint and the optimized 30-route Next.js production build pass.
- The campaign workspace is now directly reachable from a dedicated Support navigation group and from the public portal; case creation exposes live requirement obligations, explains the consent-review-owner-publication sequence, and was reverified with web lint, the 30-route production build, public campaign API HTTP 200, signed-out admin redirect, and database readiness HTTP 200.
- Google OAuth now starts through a server-owned PKCE route and explicitly carries verifier and session cookies across redirects; invalid callbacks fail safely, campaign API responses reject HTML/error payloads cleanly, the 31-route production build passes, and live checks confirm login and Support stylesheets, database readiness, and the public campaign endpoint return HTTP 200.
- Support case creation now previews the server-calculated eligible balance, constrains targets to the selected obligation, rejects learner identity before submission, and keeps precise API validation errors inside the active modal; Ruff, all 41 backend tests, web lint, the 31-route production build, and the rolled-back live Supabase Support verification pass.
- Live Supabase reached Alembic head `9d2a6f08c4b1`; `verify_support.py` passed tenant RLS, revoked grants, policy, trigger, immutability, and index checks, then completed the private-case-to-public-campaign-to-payment-to-ledger-to-proof journey inside a fully rolled-back transaction.
- Current official Supabase guidance was reviewed: exposed tables require RLS plus explicit grants, secrets stay server-side, and schema changes remain migration-managed. The October 2026 Data API exposure and TLS changelog items do not require an implementation change here.
- Current official Google documentation confirms `gemma-4-26b-a4b-it`, image input, and the Gemini API endpoint used by the server integration.

### Priority override - Harambee Support multi-role expansion

Status: **COMPLETE — NORMAL BURSAR ROADMAP RESUMES**

The user explicitly authorized a second Support priority override on 2026-10-16. It expands the privacy-preserving pilot into guardian and donor workspaces while keeping every campaign tied to the bursar ledger and every settlement directed to a school-controlled payment channel. The ordered, completion-gated implementation and legal safeguards are defined in `docs/HARAMBEE_SUPPORT_EXPANSION_PLAN.md`.

Support S6 is complete. Guardian and donor Gemma 4 assistants are separately consented, role-grounded, read-only, rate-limited and stateless; hostile prompts, private identifiers, other users' records, malformed responses and claimed financial authority fail safely. The school review assistant remains human decision support under the same controls. Ruff and all 81 backend tests, web lint, the optimized 48-route build, live migration `a91d38c7e5f2`, and production assistant security verification passed. The Support expansion is complete and normal bursar Slice 5 resumes.

Support slices S1-S6 are complete. The normal bursar roadmap resumes at Slice 5; no further Support expansion should interrupt it without a new explicit priority override.

### Slice 5 - Payment desk and official receipts

Status: **COMPLETE**

Implement:

- Fast learner search by name, admission number, guardian, or phone.
- Open obligations displayed before money is entered.
- Cash, bank, mobile money, SchoolPay, and configurable payment channels.
- Split allocation across fees and requirements, partial payments, and unallocated learner credit.
- Duplicate external-reference protection.
- Sequential school-specific official receipt numbers, printing, and reprinting.
- Authorized reversals and refunds that preserve the original transaction and require a reason.
- One canonical payment workflow; remove or redirect duplicate dashboard payment behaviour.

Completion gate:

- A payment updates the learner account, requirements, arrears, dashboard, receipt, and reports in one database transaction.
- Failed posting leaves no partial financial records.
- Reversal restores balances without deleting evidence.

Verification evidence:

- The canonical payment desk now searches learners by learner or guardian details, displays live obligations before entry, supports school-configured channels, and atomically splits receipts across fees, monetary requirements, and unallocated learner credit.
- School-specific sequential receipts, reasoned reprints, stable retry keys, duplicate provider-reference protection, linked refunds and complete reversals preserve immutable source evidence and audited actors.
- The learner account, requirement position, arrears calculations, dashboard and collections report consume the same payment and allocation records; split receipts count once in reports and corrections net consistently.
- Ruff and all 84 backend tests pass, including payment search, split allocation, duplicate retry, correction retry, rollback, tenant isolation, reporting agreement and reissue coverage. Web lint, TypeScript checking, and the optimized 48-route production build pass.
- Live Supabase reached Alembic head `b72c41e9a603`; `verify_payment_desk.py` passed standard-channel coverage, RLS, revoked Data API grants, indexes, integrity constraints and immutable financial-history triggers.

### Slice 6 - Reconciliation and daily cash-up

Status: **COMPLETE**

Implement:

- Validated CSV adapters for supported banks, mobile money providers, and SchoolPay exports.
- File and transaction duplicate protection.
- Suggested learner matches with explainable confidence.
- Confirm, reject, and authorized undo actions.
- An unidentified-funds holding register.
- Cashier collection batches, expected cash, counted cash, variance, deposits, and supervisor sign-off.
- Reconciliation summaries by channel and period.
- Route dashboard statement imports through the canonical reconciliation API.

Completion gate:

- Every collected amount is reconciled, awaiting review, unidentified, or formally reversed.
- Provider totals, posted payments, deposits, and variances can be traced and reproduced.

Verification evidence:

- Server-owned CSV adapters validate common bank, Mobile Money and SchoolPay exports before any row is stored; content hashes, source references and idempotency keys prevent duplicate files, transactions and retries.
- Suggested learner matches expose their confidence and reason. Human reviewers can confirm, reject, reopen or place receipts in the unidentified-funds register, while authorized undo creates a linked reversal or safely unlinks a previously posted payment.
- Cashiers can submit Kampala-day cash batches calculated from their official receipts, physical counts, deposit references and notes. Owners or bursars return or sign off each batch, with explanations required for cash or deposit differences.
- Source and cash-up summaries are period- and channel-aware, all consequential decisions are audited, and database triggers preserve imported source evidence and cash-batch receipt membership.
- Ruff and all 89 backend tests pass, including all provider adapters, duplicate/retry controls, rollback, tenant and role boundaries, matching evidence, unidentified funds, reversal restoration, cash capture and supervisor sign-off. Web lint, TypeScript validation and the optimized 48-route production build pass.
- Live Supabase reached Alembic head `c83d7a2f14e6`; `verify_reconciliation_cashup.py` passed RLS, revoked Data API grants, uniqueness controls, indexes and immutable-evidence triggers.

### Slice 7 - Arrears management

Status: **COMPLETE**

Implement:

- Current, 1-30, 31-60, 61-90, and 90+ day aging.
- Filters by period, class, stream, boarding status, fee category, and severity.
- Guardian contact history, notes, next actions, and payment promises.
- Printable worklists and guardian statement exports.
- Internal follow-up workflow before adding SMS or WhatsApp integrations.

Completion gate:

- A bursar can identify who owes what, why it is owed, who was contacted, what was promised, and what action is due next.

### Slice 8 - Reports, close, and rollover

Status: **COMPLETE**

Delivery phases:

1. **COMPLETE — Canonical financial reporting foundation.** One exact-decimal calculation service now classifies charges, credits, receipts, refunds, reversals, payment corrections, prior balances, and explicit carried balances. Learner statements, official receipts, dashboard totals, and collection-report control totals use the same equation and exact per-learner arrears count.
2. **COMPLETE — Complete bursar report centre.** Sixteen server-calculated operational and control reports now cover daily, cashier, channel, class and stream collections; learner balances and arrears aging; fee categories and requirements; adjustments and corrections; unidentified funds and reconciliation variance; cash-up, deposits, and billing versus collection. Shared period, date, class, stream and channel filters, print layouts, and authenticated server-generated CSV exports preserve the same totals across screen, paper and file.
3. **COMPLETE — Pre-close control checklist.** A server-owned checklist now blocks closing for unresolved statement items, provider-to-receipt differences, unsigned cash-ups, cash receipts outside a batch, receipt-allocation imbalances, and positive unallocated learner credit. Every blocker routes the bursar to its corrective workspace; supervisor-approved explained cash differences remain visible as permanent warnings.
4. **COMPLETE — Controlled period closing.** Atomic, idempotent learner and school snapshots now freeze exact financial totals, placement labels, passed controls, approved warnings, actor, timestamp, and a deterministic evidence hash in the same transaction as status and audit evidence.
5. **COMPLETE — Balance carry-forward.** Each non-zero debt or learner credit now posts from the immutable source snapshot into the next configured period exactly once, without rewriting closed history.
6. **COMPLETE — Learner rollover and promotion.** Every active learner in the immutable source snapshot receives an explicit continue, promote, repeat, hold, complete, or depart decision before atomic application to the next period.
7. **COMPLETE — Controlled reopening.** The owner can apply reasoned learner charge or credit corrections through a dedicated workflow that preserves the original close, seals a new linked evidence version, and propagates the signed delta into an existing open balance-carry destination.
8. **COMPLETE — Final verification.** The financial equation, historical reproducibility, tenant controls, retry safety, exports, production build, and live Supabase database controls are proven by the final completion suite.

Phase 1 verification evidence:

- The canonical calculation distinguishes assessment corrections from payment-linked refunds and reversals, uses an explicit carried balance when present, and otherwise derives the opening balance from ordered prior periods.
- Learner statement, dashboard, collection report, arrears result, and official receipt agree on the representative account closing balance, including prior-period debt.
- Ruff and all 97 backend tests pass, including dedicated equation, payment-correction, carried-balance, aggregation, tenant, and existing financial workflow coverage.
- Web lint, TypeScript validation, and the optimized 49-route Next.js production build pass.

Phase 2 verification evidence:

- The report catalogue exposes sixteen bursar reports from existing ledger, allocation, requirement, adjustment, reconciliation, and cashier-batch evidence; no parallel financial totals were introduced.
- Learner balances and billing-versus-collection views use the canonical Phase 1 financial equation. Fee-category reporting explicitly limits itself to authoritative assessment because general fee receipts are not falsely attributed to categories.
- Reports enforce school membership and `reports:read`, validate class and stream ownership, apply server-side filters, and produce authenticated CSV from the same rows and columns shown on screen.
- Ruff and all 98 backend tests pass, including catalogue coverage for every report type, canonical total agreement, CSV fidelity, and cashier denial. Web lint, TypeScript validation, and the optimized 49-route production build pass.

Phase 3 verification evidence:

- Period readiness is calculated on the server from statement transactions, linked receipts, payment allocations, cash receipts, cashier batches, deposits, and supervisor decisions; the browser cannot declare a period ready.
- The closing transition independently re-runs the controls and returns structured blockers, so bypassing the interface cannot close an unresolved period.
- Owners and bursars can act on the checklist, auditors can inspect it without close authority, and every failed control links to reconciliation, payments, or reports for correction.
- Ruff and all 99 backend tests pass, including all six blocker types, authorized read-only review, server-side close rejection, resolved close, and warning disclosure. Web lint, TypeScript validation, and the optimized 49-route production build pass.

Phase 4 verification evidence:

- The close transaction obtains a period row lock, re-runs all financial controls, freezes every enrolled or financially active learner plus school totals, changes the period status, and records the authenticated audit event atomically.
- A deterministic SHA-256 fingerprint covers the school, period, exact totals, learner rows, and control evidence. Repeated and concurrent close submissions return the original snapshot without creating duplicates, while failed snapshot creation rolls the entire transaction back.
- Snapshot-backed periods cannot use the legacy reopen path. Owners, bursars, and auditors can inspect immutable closing summaries, while only owners and bursars can close a period.
- Ruff and all 101 backend tests pass, including exact financial equations, idempotent replay, immutable historical reads, authorization, and rollback. Web lint, TypeScript validation, and the optimized 49-route production build pass.
- Live Supabase reached Alembic head `f13c9b2a4d60`; `verify_period_close.py` passed exact numeric money columns, tenant RLS, revoked Data API grants, uniqueness controls, indexes, constraints, and immutable snapshot triggers.

Phase 5 verification evidence:

- The immutable Phase 4 learner snapshot is the sole carry source. Every non-zero signed closing balance becomes one `carried_balance` ledger entry in the immediate next configured period; explicit destination opening balances block posting instead of being overwritten.
- Source and destination periods can each participate in only one carry batch. Row locks, idempotent replay, one transaction, exact batch-to-line totals, and rollback tests prevent duplicates or partial posting.
- Owners and bursars can preview and post; auditors can inspect without write authority. Tenant-scoped APIs, RLS, revoked Data API grants, immutable database triggers, source-line-to-ledger validation, and permanent audit evidence protect the workflow.
- Ruff and all 104 backend tests pass, including debt and credit accuracy, canonical destination totals, retry safety, skipped-period and cross-school rejection, opening conflicts, authorization, audit evidence, and atomic rollback. Web lint and the optimized 49-route production build pass.
- Live Supabase reached Alembic head `e27d4c8a91b0`; `verify_balance_carry_forward.py` passed exact numeric money columns, tenant RLS, revoked Data API grants, next-period validation, uniqueness, indexes, constraints, immutable evidence, and aggregate integrity.

Phase 6 verification evidence:

- Rollover uses the immutable period-close learner rows, requires the Phase 5 balance carry, and targets only the immediate next configured draft or open period. Existing destination placements block the whole batch.
- Same-year continuation preserves placement; new-year promotion must move to a higher configured class; repetition retains the class; holds and departures require reasons; completion and departure set controlled terminal statuses. Class-free day-care learners remain class-free.
- Every active candidate requires exactly one reviewed decision. Placements, learner statuses, published general-fee assignment, immutable decision lines, and authenticated audit events commit atomically; retries return the original result and partial failures roll back.
- Owners and bursars can apply rollover while auditors can review only. Ruff and all 108 backend tests pass, including suggestions, all six decisions, authorization, full-review validation, retry safety, rollback, and class-free day-care continuity. Web lint and the optimized 50-route production build pass.
- Live Supabase reached Alembic head `c91b7e2a4f60`; `verify_learner_rollover.py` passed tenant RLS, revoked Data API grants, close-and-carry prerequisites, next-period validation, uniqueness, decision integrity, aggregate totals, and immutable evidence.

Phase 7 verification evidence:

- Controlled reopening never changes a period back to ordinary open status. The original close and hash remain immutable while each atomic correction case creates a sequential, hash-linked financial snapshot revision.
- Only the institution owner can apply a case; bursars and auditors can inspect the evidence. Every corrected learner must exist in the sealed register, every amount and reason is validated, retries are idempotent, and live ledger totals must still match the latest sealed version before a correction can proceed.
- Omitted charges and compensating credits create immutable source ledger entries. If balances were already carried, the same signed delta is posted into the still-open destination; a closed downstream destination blocks the case instead of silently rewriting later history.
- Ruff and all 110 backend tests pass, including immutable-original evidence, signed carry propagation, authorization, invalid scope, retry safety, and rollback. Web lint and the optimized 51-route production build pass.
- Live Supabase reached Alembic head `a72d5e8c19f4`; `verify_controlled_reopening.py` passed tenant RLS, revoked Data API grants, owner-only inserts, revision-chain constraints, correction ledger links, aggregate totals, and immutable evidence.

Phase 8 verification evidence:

- The exact equation `opening balance + net assessed - net collected = closing balance` passes independently for each representative learner and after aggregation to class and school totals, including debt, credit, discounts, waivers, requirements, and payments.
- A close snapshot and its learner rows retain the same evidence hash and reproduce the same exact balances after carry-forward and after the destination term opens.
- All 111 backend tests pass as one suite, covering the Supabase-authenticated school journey, tenant and role boundaries, structure, periods, learners and guardians, controlled billing, targeted requirements, payments and receipts, reconciliation and cash-up, arrears follow-up, exports, close, carry, rollover, retry safety, and injected rollback failures.
- Ruff, web lint, TypeScript validation, and the optimized 51-route production build pass.
- Live Supabase remains at Alembic head `a72d5e8c19f4`; `verify_bursar_completion.py` passed RLS and revoked Data API grants across 34 operational tables, required idempotency constraints and immutable-evidence triggers, financial equations, snapshot aggregation, tenant consistency, audit actors, and carry-forward totals.

Implement:

- Daily collections, cashier, channel, class, stream, fee-category, and requirements reports.
- Learner balances, arrears aging, adjustments, reversals, refunds, unidentified funds, reconciliation variance, cash-up, deposit, and billing-versus-collection reports.
- Exportable and printable reports with consistent filters and totals.
- Pre-close validation for unresolved reconciliation, unallocated payments, and control variances.
- Period locking, closing control summary, balance carry-forward, and learner promotion or movement.
- Authorized reopening with complete audit evidence.

Completion gate:

- `opening balance + charges - credits - payments = closing balance` at learner, class, and school level.
- A closed term remains historically reproducible after the next term opens.

## Bursar completion gate

Sponsor administration may resume only when all eight slices are marked **COMPLETE** and the following journey passes against a Supabase-backed test environment:

1. A user signs up, creates a school, and receives an authorized role.
2. The bursar creates the school structure and opens a term.
3. Learners and guardians are registered or imported and placed correctly.
4. Fees and targeted requirements are previewed and published exactly once.
5. Cash and electronic payments are allocated and receipted.
6. Statements are imported, matched, reconciled, and included in cash-up.
7. Arrears are followed up and statements are produced.
8. Reports balance and the term closes with balances carried forward.
9. Audit evidence identifies who performed every consequential action.
10. Cross-school access, unauthorized actions, duplicate submissions, and partial failures are rejected by automated tests.

## Deferred roadmap

Only after the bursar completion gate:

1. Sponsor onboarding and programme administration.
2. Beneficiary allocation and sponsor reporting.
3. Audited Stellar testnet settlement controls.
4. Settlement-provider and fiat-delivery reconciliation.
5. Independent security and corridor validation before any mainnet activity.

## Progress log

Add a dated entry only when a slice changes status. Include the verification commands or evidence used to justify completion.

- 2026-10-24: Started Slice 8 and completed Phase 1. A shared exact-decimal financial calculation now makes learner statements, official receipts, dashboard metrics, and collection-report control totals agree across prior balances, charges, credits, receipts, refunds, reversals, payment corrections, and future carried balances. Ruff, all 97 backend tests, web lint, TypeScript validation, and the optimized 49-route production build passed. Phase 2, the complete bursar report centre, is next.
- 2026-10-24: Completed Slice 8 Phase 2. Sixteen tenant-scoped bursar reports now cover collections, balances, aging, billing, requirements, adjustments, corrections, reconciliation, unidentified funds, cash-up, deposits, and billing-versus-collection with shared filters, print layouts, and server-generated CSV. Ruff, all 98 backend tests, web lint, TypeScript validation, and the optimized 49-route production build passed. Phase 3, the pre-close control checklist, is next.
- 2026-10-24: Completed Slice 8 Phase 3. Server-owned pre-close controls now block unresolved reconciliation, provider-to-receipt variance, unsigned cash-up, unbatched cash, receipt-allocation imbalance, and unallocated learner credit, while preserving approved explained differences as warnings. Ruff, all 99 backend tests, web lint, TypeScript validation, and the optimized 49-route production build passed. Phase 4, controlled period closing, is next.
- 2026-10-24: Completed Slice 8 Phase 4. Period closing now atomically freezes exact learner and school financial totals, placement labels, control evidence, actor, timestamp, audit record, and a deterministic evidence hash; retries are idempotent and partial failures roll back. Ruff, all 101 backend tests, web lint, TypeScript validation, the optimized 49-route production build, live migration `f13c9b2a4d60`, and `verify_period_close.py` passed. Phase 5, balance carry-forward, is next.
- 2026-10-24: Completed Slice 8 Phase 5. Signed learner debts and credits now carry from immutable closing evidence into the immediate next period exactly once, with conflict detection, atomic ledger posting, role and tenant controls, database-enforced integrity, immutable audit evidence, and a complete bursar review interface. Ruff, all 104 backend tests, web lint, the optimized 49-route production build, live migration `e27d4c8a91b0`, and `verify_balance_carry_forward.py` passed. Phase 6, learner rollover and promotion, is next.
- 2026-10-25: Completed Slice 8 Phase 6. A dedicated bursar workspace now reviews every active learner against immutable closing evidence and atomically applies continuation, promotion, repetition, hold, completion, or departure into the immediate next period, including published general fees and class-free day-care continuity. Ruff, all 108 backend tests, web lint, the optimized 50-route production build, live migration `c91b7e2a4f60`, and `verify_learner_rollover.py` passed. Phase 7, controlled reopening, is next.
- 2026-10-25: Completed Slice 8 Phase 7. Owner-controlled charge and credit corrections now preserve the original close, seal sequential hash-linked revisions, propagate signed deltas into an open carried destination, reject divergent or closed downstream history, and retain immutable audit evidence. Ruff, all 110 backend tests, web lint, the optimized 51-route production build, live migration `a72d5e8c19f4`, and `verify_controlled_reopening.py` passed. Phase 8, final verification, is next.
- 2026-10-25: Completed Slice 8 Phase 8 and the bursar completion gate. Learner, class, and school equations now have explicit aggregate proof; closed-term evidence remains reproducible after carry-forward and opening the destination term; all 111 backend tests, Ruff, web lint, TypeScript validation, the optimized 51-route build, and the consolidated live Supabase verification at `a72d5e8c19f4` passed. All eight bursar slices are complete.

- 2026-10-23: Completed Slice 7. Exact current, 1-30, 31-60, 61-90 and 90+ aging; period, class, stream, residence, fee-category and priority filters; obligation reasons; immutable guardian contact history; next actions; automatically evaluated payment promises; printable worklists; and guardian statement and CSV exports are operational. Ruff and all 92 backend tests, web lint, TypeScript checks, the optimized 48-route production build, live migration `d54a9c7e210f`, and `verify_arrears_management.py` passed. Slice 8 is next.

- 2026-10-09: Replaced the broad roadmap with the ordered bursar implementation plan. Slice 1 is the next authorized delivery target.
- 2026-10-09: Completed Slice 1. Supabase-backed tenant policies, server-derived roles, authenticated web/API transport, scoped resource queries, audit attribution, 26 backend tests, frontend lint/build, and live database verification passed. Slice 2 is next.
- 2026-10-11: Completed Slice 2. Academic-year and period setup, lifecycle transitions, historical selection, tenant-scoped permissions, database-enforced closed-period protection, and period-aware bursar registers were implemented. Ruff and 31 backend tests passed, including cross-period enrollment, fees, requirements, arrears, payments, dashboard, and reporting coverage; web lint and the 28-route production build passed; live Supabase reached Alembic head `20e3e44669b3`, and `verify_academic_periods.py` passed its RLS, policy, trigger, backfill, uniqueness, privilege, and closed-period checks. Slice 3 is next.
- 2026-10-12: Completed Slice 3. Flexible class, stream, residence, and selected-learner fee plans; arbitrary fixed or percentage installments; monetary, physical, optional, and candidate requirements; reasoned learner additions and credits; exact conflict-aware previews; and atomic idempotent publication to immutable ledger entries were implemented. Ruff and 35 backend tests passed, including learner-, class-, and school-level preview/posting equality, replay protection, and safe draft removal; web lint and the 28-route production build passed; live Supabase reached Alembic head `81d7c62772c3`; `verify_controlled_billing.py` passed RLS, policy, grant, trigger, backfill, uniqueness, and immutability checks; and `verify_requirements.py` completed draft-to-publication-to-payment-to-issue in a rollback transaction. Slice 4 is next.
- 2026-10-15: Completed Slice 4. Selected-period learner statements now combine brought-forward balances, categorized charges and requirements, payments and allocations, discounts, waivers, sponsorship credits, reversals, refunds, physical obligations, and carried balances in deterministic chronological order with a recalculated running balance. Historical placement, authorized guardian and payer context, print styling, CSV download, loading, empty, error, filtering, and responsive states were implemented. Ruff and 37 backend tests passed, including exact ledger recalculation, movement history, tenant isolation, auditor access, contact privacy, CSV output, and agreement with dashboard, arrears, and reporting totals; web lint and the 28-route production build passed; live Supabase reached Alembic head `189d96d367f9`; and `verify_learner_accounts.py` passed the chronological index, immutable-ledger, opening-balance, period-activity, and running-balance checks in a rollback transaction. Slice 5 is next.
- 2026-10-16: Completed the explicitly authorized Harambee Support pilot override. Anonymous obligation-backed campaigns, scoped guardian consent and learner assent, Gemma 4 review, owner approval, donor pledges and public tracking, atomic learner-account settlement, outcome proof, tenant controls, and the public portal were delivered. Ruff and all 40 backend tests, web lint, the 30-route production build, live migration `9d2a6f08c4b1`, and the rolled-back live Supabase workflow in `verify_support.py` passed. Slice 5 remains next.
- 2026-10-16: Completed Support expansion S1. Server-derived multi-role portal discovery, school staff continuity, donor activation, hashed 72-hour single-use guardian invitations, verified guardian-account links, role-aware login routing, and separate guardian/donor interfaces were delivered. Ruff, web lint, all 46 backend tests, the optimized 36-route build, live migration `a5da2b77f0d5`, portal RLS/grant/audit verification, and the original rolled-back Support financial workflow passed. Support expansion S2 is next.
- 2026-10-16: Completed Support expansion S2. Canonical arrears-derived referral candidates, verified guardian routing, versioned privacy notice, authority and age checks, independent publication/Gemma/cross-border choices, capable-learner assent, refusal and withdrawal were delivered. Withdrawal closes matching open campaigns without deleting financial evidence. Ruff, web lint, all 48 backend tests, the optimized 36-route build, live migration `e30afe762c9b`, referral RLS/grant/audit verification, and the original rolled-back Support settlement workflow passed. Support expansion S3 is next.
- 2026-10-18: Completed Support expansion S3. Guardians can now save, submit and revise private cases against exact live fee or monetary-requirement obligations; school staff can request changes, owners separately approve and publish, optional Gemma review follows recorded consent, and private narratives never enter public payloads. Database-enforced partial uniqueness prevents concurrent duplicate obligation campaigns, while targets reduce when the ledger balance changes. Ruff, all 53 backend tests, web lint, the optimized 38-route build, live migration `f42c8e910ab7`, guardian-case schema/RLS/grant verification, and the rolled-back Support settlement workflow passed. Support expansion S4 is next.
- 2026-10-18: Completed Support expansion S4. Verified institution-owned SchoolPay, bank and mobile-money destinations, idempotent guest and authenticated-donor checkout, independent cashier settlement, atomic learner-ledger posting, sequential privacy-safe receipts, audited reissue, rejection and compensating reversal were delivered. Ruff, all 55 backend tests, web lint, the optimized 39-route build, live migration `7ac4d92e1b63`, contribution RLS/grant/index/immutability verification and the rolled-back live Support financial workflow passed. Support expansion S5 is next.
- 2026-10-21: Completed the automatic general class fee refinement. Published whole-class fees now follow learner registration, imports, and first placement exactly once; existing posted fees force movement review; scholarships have a dedicated bursar workflow and cannot exceed the available balance. Ruff, all 56 backend tests, web lint, and the optimized 38-page production build passed.
- 2026-10-22: Completed multi-unit Phase B staff access. Owners can issue email-bound 72-hour single-use invitations for one selected section, assign bursar, cashier, or auditor access, change roles, revoke access, and preserve audit evidence while owner access remains protected. Ruff, all 67 backend tests, web lint, the optimized 41-route build, live migration `ce42d91f5a10`, and database readiness passed. Consented learner transfer is next.
- 2026-10-22: Completed multi-unit Phase C learner transfer. Guardian-authorized source requests, receiving-section decisions, organization-stable learner identity, new target placement, matching audit history, rollback safety, retry idempotency, and source-ledger preservation are operational. Ruff, all 71 backend tests, web lint, the optimized 42-route build, live migration `d719a24c6e31`, and database readiness passed. External system exchange is next.
- 2026-10-22: Completed multi-unit Phase D external exchange. Section-scoped hashed service credentials, versioned minimal exports, stable identifiers, idempotent import quarantine, signed transfer webhooks, post-commit outbox delivery, retry history, exchange evidence and owner controls are operational. Ruff, all 76 backend tests, web lint, the optimized 43-route build, live migration `e84a1f03c9b2`, and production schema verification passed.
- 2026-10-22: Completed Support expansion S5. Durable guardian, donor and school notifications now have per-user read state, deep links, deterministic deduplication and a provider-neutral outbox. Guardian acknowledgements and school outcomes remain private until owner-approved redaction, while donor timelines connect pledges, verified school receipts and anonymous outcomes. Ruff, all 77 backend tests, web lint, the optimized 46-route build, live migration `f6a91c42d7e0`, and production schema verification passed. Support S6 is next.
- 2026-10-22: Completed Support expansion S6 and the multi-role override. Guardian and donor Gemma 4 assistants now require explicit consent, use only role-scoped minimum facts, return validated read-only guidance, retain no conversation content, share a database-backed rate limit, and fail safely on prompt injection, identity leakage, malformed output, unavailable AI or authority claims. The school assistant remains decision support only. Ruff, all 81 backend tests, web lint, the optimized 48-route build, live migration `a91d38c7e5f2`, and `verify_support_assistants.py` passed. Normal bursar Slice 5 is next.
- 2026-10-22: Completed Slice 5. A single obligation-first payment desk now provides learner and guardian search, configured collection channels, split allocation, learner credit, idempotent references, sequential receipts, controlled reprints and evidence-preserving refunds or reversals. Ruff and all 84 backend tests, web lint, TypeScript checks, the optimized 48-route build, live migration `b72c41e9a603`, and `verify_payment_desk.py` passed. Slice 6 is next.
- 2026-10-23: Completed Slice 6. Server-validated bank, Mobile Money and SchoolPay imports, explainable matching, controlled review states, unidentified funds, evidence-preserving undo, daily cashier batches, deposit tracking and supervisor sign-off are operational. Ruff and all 89 backend tests, web lint, TypeScript checks, the optimized 48-route build, live migration `c83d7a2f14e6`, and `verify_reconciliation_cashup.py` passed. Slice 7 is next.
