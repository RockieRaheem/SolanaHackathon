# Security & Privacy Baseline

## Implemented tenant controls

- Supabase access tokens are verified by the web gateway and independently by the Python API.
- Every operational endpoint resolves the active institution from `school_memberships`.
- Caller-provided school IDs are checked against membership and resource-ID lookups are tenant-scoped.
- Server-side permissions cover owner, bursar, cashier, and auditor roles.
- Public-schema tables have tenant-aware Supabase RLS policies; Data API grants remain revoked by default.
- Private RLS helper functions explicitly revoke execution from `PUBLIC`.
- Financial and requirements audit events record the authenticated user's email or immutable user ID.
- Academic periods are tenant-owned, expose only one operational period per school, and use database triggers to reject enrollment, billing, requirements, and payment mutations after closure.
- Browser code receives only the Supabase publishable key; database and service-role credentials stay server-side.
- Authentication uses Supabase SSR cookies and PKCE; protected pages validate signed claims before rendering.
- Credential, recovery, and logout mutations are same-origin, size-limited, non-cacheable server routes.
- Password creation and reset require 12 characters with uppercase, lowercase, numeric, and symbol characters.
- Login, signup, and recovery endpoints apply application-level IP-plus-account throttling in addition to Supabase rate limits.
- Signup and recovery responses avoid disclosing whether an email address already has an account.
- Password recovery invalidates all existing sessions and requires a fresh login.
- Global response headers deny framing, MIME sniffing, unnecessary browser capabilities, and unsafe referrer disclosure.

## Required Supabase production settings

- Keep **Confirm email** enabled and configure a production SMTP provider; the built-in sender is for development only.
- Match the dashboard password policy to the application: minimum 12 characters with uppercase, lowercase, number, and symbol.
- Enable leaked-password protection where the Supabase plan supports it.
- Configure only exact production and local `/auth/callback` redirect URLs; never use wildcard production redirects.
- Enable security notification emails for password and identity changes.
- Review Auth rate limits and enable Cloudflare Turnstile or hCaptcha before public launch.
- Require MFA and a short session inactivity timeout for owners, bursars, and other privileged users before real deployment.

Verification lives in `tests/test_tenant_authorization.py` and
`scripts/verify_tenant_security.py`; academic-period controls are verified by
`tests/test_academic_periods.py` and `scripts/verify_academic_periods.py`. Authenticated operational verification scripts require a
short-lived `SUPABASE_TEST_ACCESS_TOKEN` for a dedicated test user.

Before production use with real students or funds:

- MFA for privileged school, sponsor and platform users.
- Strict tenant isolation in every backend query and storage key.
- Server-side RBAC/ABAC; UI permissions alone are not security.
- TLS in transit; encryption at rest for DB, object storage and backups.
- Secrets manager for production credentials.
- Immutable/append-only audit events for consequential financial actions.
- Idempotency for payment, settlement and webhook commands.
- Signed webhooks and replay protection.
- Backup restore exercises and incident-response runbooks.
- OWASP ASVS-based secure development checks and independent penetration testing.
- Independent Solana programme audit before meaningful mainnet value is placed in programme-controlled accounts.
- No student names, NINs, phone numbers, dates of birth, marks, school identifiers, invoice details, or private documents on Solana.
- AI providers receive only the minimum authorised context and must not be treated as the source of financial truth.
