# Harambee Support Expansion Plan

This plan turns the existing anonymous, school-operated Support pilot into a complete multi-role workflow while preserving the school ledger as the financial source of truth. It is an explicitly authorized priority override. Each slice must be completed, verified, recorded in `docs/MVP_ROADMAP.md`, and committed before work starts on the next slice.

## Product outcome

```text
School detects material arrears
  -> school privately refers learner and invites verified guardian
  -> guardian accepts the link and reviews a plain-language privacy notice
  -> guardian gives or declines scoped consent
  -> capable learner's view is recorded without creating a public identity
  -> guardian drafts the need against a verified school obligation
  -> school reviews evidence, amount, safety and payment destination
  -> authorized school owner publishes an anonymous campaign
  -> authenticated or guest donor contributes to a school-controlled channel
  -> school independently verifies settlement
  -> contribution posts atomically to the learner ledger and campaign
  -> guardian, donor and school receive in-app notifications
  -> donor receives a school-issued, privacy-safe receipt
  -> school and guardian publish redacted outcome evidence
```

The platform must never send campaign money to a guardian or learner. Campaign targets cannot exceed a live fee or monetary-requirement obligation. Pending contributions never increase funded totals. A learner's name, admission number, photograph, exact class or guardian identity remain private even when the guardian knows and edits the private case.

## Ugandan child-data safeguards

These are engineering safeguards, not a substitute for review by Ugandan counsel or the Personal Data Protection Office before production fundraising.

- Treat every learner under 18 as a child. Record the basis used to determine age and the authority of the consenting guardian.
- Obtain specific, informed guardian consent before processing a child's campaign data. Consent to anonymous publication, Gemma processing and processing outside Uganda remain separate choices.
- Record the views of a child who is capable of expressing them. A decline blocks publication. `Not applicable` or `unable to express` requires a reason and school review.
- Show a versioned, plain-language privacy notice before consent and preserve the exact version accepted.
- Allow consent withdrawal. Withdrawal immediately unpublishes an open campaign, prevents new contributions and preserves the minimum financial/audit history required for accountability.
- Apply purpose limitation, data minimization, retention limits, access logging and redaction. Never expose learner identity merely because a guardian consented.
- Complete a privacy impact assessment, controller/processor review, PDPO registration/compliance review and cross-border assessment before production use.

Primary references:

- Uganda Data Protection and Privacy Act, 2019, especially consent, child data and processing outside Uganda: https://ict.go.ug/ims/public/site/documents/Data-Protection-and-Privacy-Act-2019.pdf
- Data Protection and Privacy Regulations, 2021, including age and guardian-consent verification: https://pdpo.go.ug/media/2022/03/Data_Protection_and_Privacy_Regulations-2021.pdf
- Uganda Children Act, sections 3 and 4 on welfare, capable children's views and privacy: https://ulii.org/en/akn/ug/act/statute/1996/6/eng@2024-08-16
- PDPO guidance and privacy impact assessment resources: https://pdpo.go.ug/knowledge-center

## Authorization model

Authorization is derived from server-owned database relationships, never editable user metadata.

| Persona | Scope | Allowed actions |
| --- | --- | --- |
| School owner | One school | Configure channels, invite guardians, review/approve/publish/withdraw cases, verify settlement, issue evidence and receipts |
| Bursar | One school | Identify arrears, create referrals, communicate with guardians, review cases, verify settlement; cannot give final publication approval |
| Cashier | One school | View approved support payments and verify assigned settlement when permitted; cannot access guardian narrative or publish |
| Auditor | One school | Read financial and audit evidence; cannot change cases or contributions |
| Guardian | Explicit linked learners only | Accept a one-time invitation, consent or withdraw, draft/edit private case details before review, view funding/receipts/evidence and use the guardian assistant |
| Donor | Own contributions only | Maintain a minimal profile, pledge, track settlement, view/download own receipts, receive notifications and use the donor assistant |
| Guest donor | One public tracking reference | View public campaigns and track a contribution using its unguessable reference; no private dashboard |

A person may hold more than one persona. School membership remains separate from guardian and donor relationships.

## Slice S1 - Portal identity and roles

Status: **COMPLETE**

Implement:

- A platform profile keyed by Supabase `auth.users.id` with a display name and safe portal preferences.
- Guardian-account links to existing `guardian_links`, created only through expiring, single-use, hashed invitations.
- Donor profiles and authenticated donor identity on new contributions.
- A server-derived `/me` capability response and role-aware post-login routing.
- Separate guardian and donor portal shells; school staff keep the bursar workspace.
- Tenant/ownership RLS, revoked Data API access where appropriate, audit records and negative authorization tests.

Completion gate:

- A school can issue a guardian invitation without exposing a reusable secret in storage.
- The intended signed-in guardian can accept it once and can access only explicitly linked learners.
- Any signed-in user can activate a donor profile without gaining school or guardian access.
- Users with multiple personas can choose a workspace; authorization never relies on `user_metadata`.
- Unauthenticated, cross-guardian, cross-school, expired-token and replay attempts fail in API and database tests.

Verification evidence:

- Platform profiles, donor profiles, hashed guardian invitations and verified guardian-account links are migration-managed at Alembic head `a5da2b77f0d5`.
- The role-aware `/workspace` router, account setup, guardian claim, guardian workspace, donor workspace and school invitation controls are included in the optimized 36-route Next.js build.
- Ruff, web lint, all 46 backend tests and five focused portal authorization tests pass.
- Live Supabase verification passed owner-scoped RLS, revoked Data API grants, audit triggers, hashed single-use invitations, guardian-linked learner isolation, donor isolation and full transaction rollback.
- The pre-existing Support verification still passes the complete case-to-settlement financial workflow after the role migration.
- Current Supabase Auth guidance was checked: authorization remains in server-owned database relationships rather than editable `user_metadata`; secret credentials remain server-side. The October 2026 TLS cipher change does not affect the modern clients used here, and the project does not use the deprecated `@supabase/server` framework adapters.

## Slice S2 - Arrears referral and lawful consent

Status: **COMPLETE**

Implement:

- Deterministic arrears eligibility and priority reasons from ledger facts; do not claim that AI predicts dropout.
- School referral from an overdue learner account with live amount, due date and reason snapshot.
- Guardian invitation delivery state and contact history.
- Versioned privacy notice, verified guardian authority, child age basis, scoped consent and capable-child assent workflow.
- Consent refusal and withdrawal, including immediate unpublication and prevention of new contributions.
- Role-specific loading, empty, error and success states plus audit events.

Completion gate:

- The school can move a real overdue account to guardian consideration without making it public.
- The guardian can accept or decline each optional processing scope and review what donors will see.
- Publication is impossible without active guardian consent and an acceptable learner-assent decision.
- Withdrawal stops fundraising while immutable receipts and audit history remain reproducible.

Verification evidence:

- The school Support workspace now lists referral candidates produced by the canonical arrears calculation, including exact overdue amount, oldest unpaid installment age and deterministic watch/high/urgent reasons; it makes no AI dropout claim.
- A referral can be created only for a live overdue account, the selected learner's guardian and a previously verified guardian portal link. Duplicate learner-period referrals are rejected.
- The guardian workspace shows the versioned plain-language notice and separately records guardian authority, age-verification basis, anonymous publication, Gemma, cross-border processing and the capable learner's view. Decline and withdrawal are first-class audited states.
- Withdrawing consent marks matching draft, review or published cases withdrawn, which immediately prevents new public pledges while leaving posted financial records untouched.
- Live Supabase reached Alembic head `e30afe762c9b`; referral RLS, revoked Data API grants and audit triggers pass verification, and the original Support financial workflow still passes its rolled-back live check.
- Ruff, web lint, all 48 backend tests, focused arrears/referral/consent/cross-guardian/withdrawal tests and the optimized 36-route Next.js build pass.

## Slice S3 - Guardian-authored case and school publication

Status: **COMPLETE**

Implement:

- Guardian drafting against the linked learner's exact fee or monetary-requirement balance.
- Private learner identity display for the linked guardian, with no redundant public identity entry.
- Need category, amount, private context and separately previewed anonymous public summary.
- Draft/save/submit/revise states; school completeness, safeguarding and duplication review.
- Owner approval and publication with four-eyes separation where owner and author differ.
- Duplicate learner/obligation campaign prevention and automatic target reduction when the ledger changes.

Completion gate:

- A guardian can submit a complete case but cannot publish it or exceed the obligation.
- A school can request changes, approve and publish only safe anonymous content.
- Concurrent or duplicate cases cannot over-reserve the same learner obligation.
- Public APIs contain no learner, guardian or private narrative identifiers.

Verification evidence:

- The guardian workspace now shows exact live school-fee and monetary-requirement balances, keeps learner identity private inside the linked account, separates the private school narrative from the anonymous public preview, and supports draft, submit, school change request and revision states.
- The school workspace exposes the private narrative only to authorized staff, permits bursar change requests, reserves final approval and publication for the institution owner, and runs Gemma only when the guardian separately consented to it.
- Partial unique indexes prevent concurrent active campaigns for the same general or requirement obligation, and case targets automatically reduce when other ledger payments reduce the live balance.
- Public campaign responses exclude learner, guardian, account and private-narrative identifiers; identity-bearing public text and cross-guardian access are rejected.
- Ruff, all 53 backend tests, web lint and the optimized 38-route build pass. Supabase reached Alembic head `f42c8e910ab7`; schema, partial-unique-index, RLS, policy and revoked-grant verification passed, followed by the rolled-back end-to-end Support financial verification.

## Slice S4 - Controlled contributions and official receipts

Status: **COMPLETE**

Implement:

- School-configured SchoolPay code, bank and institution-owned mobile-money destinations with verification state and public payment instructions.
- Donor pledge checkout with exact remaining-target protection, idempotency and authenticated ownership when signed in.
- Independent school settlement verification and rejection with reasons.
- One transaction that posts the verified amount to payment, allocation, ledger, requirement, campaign and receipt records.
- Privacy-safe donor receipt view/download and school reissue; no learner identity on donor documents.
- Overpayment, duplicate reference, partial failure, retry, reversal and campaign-funded behaviour.

Completion gate:

- No path sends money to a guardian-owned destination.
- A verified contribution updates the campaign and learner account exactly once.
- Donor and guardian totals agree with the school ledger while each sees only permitted data.
- Failed settlement creates no partial financial state and reversals preserve evidence.

Verification evidence:

- School owners can configure SchoolPay, bank and institution-owned mobile-money destinations; exact institution account-name validation and explicit verification prevent guardian or learner destinations from reaching donors.
- Guest and authenticated-donor checkout uses a client idempotency key, unique settlement references and locked remaining-target checks. Pending money stays separate until a bursar, owner or permitted cashier independently verifies it.
- Verification creates the payment, allocation, learner-ledger credit and sequential school receipt in one transaction. Rejection reasons, receipt reissues and owner-only compensating reversals retain the original evidence and restore campaign and ledger totals.
- Public and authenticated donor receipts contain campaign and school facts but no learner, admission or guardian identity. The donor workspace now lists owned contributions and printable/downloadable receipts.
- Ruff, all 55 backend tests, web lint and the optimized 39-route build pass. Live Supabase reached Alembic head `7ac4d92e1b63`; contribution schema, RLS, revoked grants, indexes and immutability checks passed, followed by the rolled-back end-to-end Support financial workflow.

## Slice S5 - Notifications and outcome assurance

Status: **COMPLETE**

Implement:

- Durable in-app notifications for guardian, donor and school recipients with read state and deep links.
- Events for invitation, consent, submission, changes requested, publication, pledge, verification, rejection, funded, receipt and outcome evidence.
- Guardian acknowledgement plus school fulfilment/enrolment evidence with redaction and human approval.
- Donor-facing campaign timeline, receipt and outcome update without child identity.
- Delivery outbox abstraction so email/SMS can be added later without coupling financial transactions to an external provider.

Completion gate:

- Every consequential state transition produces the correct recipient notifications once.
- Notification retry cannot duplicate financial activity.
- Donors can prove what the school received and how it was allocated without identifying the child.

Verification evidence:

- Guardian, donor and school audiences receive durable, deduplicated in-app notifications at the authoritative workflow transition; school broadcasts retain per-user read state and every notification creates one provider-neutral outbox job in the same transaction.
- Funded campaigns accept private guardian acknowledgements and school fulfilment or enrolment evidence. No statement reaches donors until an owner approves a separately redacted version that passes the existing learner-identity check.
- Donor campaign timelines join pledge creation, independent school verification, official receipt availability and approved anonymous outcomes without exposing learner, admission or guardian identity.
- Ruff and all 77 backend tests pass, including notification deduplication, outbox creation, read isolation, mandatory human outcome review, settlement retry and the pre-existing atomic financial journey. Web lint and the optimized 46-route production build pass.
- Live Supabase reached Alembic head `f6a91c42d7e0`; `verify_support_notifications.py` passed RLS, revoked Data API grants, owner policies, delivery indexes and legacy outcome backfill checks.

## Slice S6 - Gemma assistants and release verification

Status: **COMPLETE**

Implement:

- Guardian assistant limited to explaining consent, helping draft safe campaign text and navigating the guardian workflow.
- Donor assistant grounded only in public campaign/payment/receipt facts and general portal help.
- Existing school review assistant retained as decision support only; no automatic eligibility, fraud or publication decisions.
- Explicit consent gates, prompt minimization, redaction, structured output validation, rate limits, timeout/failure UX and no hidden conversation retention.
- Prompt-injection and data-exfiltration tests; model responses never grant authority or mutate finance directly.
- Full Supabase migration/security verification and multi-role browser/API end-to-end journey.

Completion gate:

- The assistants answer only within their role and data scope, clearly identify uncertainty and fail safely without blocking manual workflows.
- A hostile prompt cannot expose another learner, guardian, donor or school's data.
- The complete referral-to-outcome journey passes with role, tenant, duplicate, rollback and privacy tests.
- The optimized web build, backend suite, database verification and documented production privacy gates pass.

Verification evidence:

- Guardian and donor workspaces now expose dedicated Gemma 4 assistants for only the three documented tasks per role. Guardian use requires stored referral consent plus fresh request consent; donor grounding is limited to public campaign facts or a contribution owned by the signed-in donor.
- Every assistant is stateless and read-only. HarambeeOne retains only user, persona, task, scope, model, outcome and timestamps for rate limiting and operational audit; questions and answers are never stored. Structured responses must explicitly deny mutation authority and are rejected if they contain private identifiers or financial-action claims.
- Prompt-injection phrases, submitted identity and contact data, cross-guardian access, cross-donor contribution access, malformed model output, privacy leakage, unsafe authority claims and more than eight requests in ten minutes fail safely. Gemma timeouts or API failures leave the manual guardian, donor and school workflows available.
- The existing school review remains human decision support, now under the same database-backed rate limit and metadata-only operational record. Gemma cannot consent, determine eligibility, allege fraud, approve publication, verify settlement, issue receipts or write to the ledger.
- Ruff and all 81 backend tests pass, including the complete referral, consent, case, publication, contribution, settlement, receipt, notification and outcome journey plus the new adversarial assistant tests. Web lint and the optimized 48-route production build pass.
- Live Supabase reached Alembic head `a91d38c7e5f2`; `verify_support_assistants.py` passed metadata-only schema, RLS, revoked Data API grants, owner policy, constraints and rate-limit index verification.

## Deferred integrations

- Automated SchoolPay, bank or mobile-money confirmation remains adapter-based until a provider contract and authenticated API are available.
- Email, SMS and WhatsApp delivery use the outbox after a provider is selected; in-app notifications are the guaranteed first channel.
- Public learner names, photographs and exact classes are deliberately out of scope. A later proposal would require a new legal, safeguarding and privacy review rather than a guardian toggle.
