# HarambeeOne Architecture

## Product boundary

HarambeeOne has one active product area: **Bursar Operations**. It covers the minimum learner identity and placement data needed for finance, fee setup, learner ledgers, collections, receipts, arrears, statement reconciliation, finance reports and audit evidence.

Sponsor administration and programmable settlement are deferred product areas. They must not expand the active interface or implementation workload until the bursar product passes its end-to-end completion gate. General school administration and academics remain outside the product.

## Delivery gate

Sponsor and settlement development can resume only after learner accounts, fee setup, collections, receipts, arrears, reconciliation, reporting and audit workflows are complete, production-built and covered by backend verification.

## Core rule

The operational PostgreSQL ledger is authoritative for school finance. Personally identifiable learner information remains in the protected operational database.

## Financial truth

- Provider transaction = immutable source event.
- Payment allocation = how a source event is applied to a learner.
- Ledger entries = authoritative explanation of the learner balance.
- Reconciliation = evidence that a provider transaction was matched to the correct learner account.

## Production topology

```text
Next.js browser interface
  -> same-origin Next.js API gateway
  -> FastAPI workflow and authorization service
  -> Supabase PostgreSQL ledger, tenant controls, and audit evidence
```

Supabase Auth provides the session identity, but operational authorization is derived by FastAPI from school membership and resource ownership. Provider adapters connect SchoolPay, banks, Mobile Money, and future messaging services without becoming the financial system of record.

## Period close boundary

Closing a period is a database transaction, not a visual status change. The service locks the period, re-runs the financial controls, freezes learner and school totals, records the authenticated actor and audit event, and assigns a deterministic evidence hash before committing the closed status. Snapshot-backed periods remain immutable; balance carry-forward and controlled reopening use later compensating workflows rather than rewriting the close.

## Repository boundaries

The active runtime is `apps/web` plus `apps/backend`. The NestJS service in `apps/api`, Stitch mock-ups, Support source documents, and Soroban package are retained references or deferred experiments. See the [repository guide](REPOSITORY_GUIDE.md) for detailed ownership.

## Automation boundary

Automation can read authorised finance data, explain, recommend and flag. It cannot bypass business rules, approve financial changes or merge uncertain learner identities.
