# Production readiness

HarambeeOne is not declared production-ready by a successful build. Release requires current evidence for browser journeys, capacity, security, recovery, regulated payments and legal review. The canonical phase status is in `docs/MVP_ROADMAP.md`.

## Browser verification

Safe signed-out security checks:

```powershell
pnpm.cmd test:e2e
```

Playwright normally uses its pinned Chromium runtime. On a Windows workstation where browser extraction is blocked by endpoint protection, the same Chromium engine can be exercised through an installed supported channel:

```powershell
$env:E2E_BROWSER_CHANNEL='chrome' # or msedge
pnpm.cmd test:e2e
```

The system-channel fallback retains traces and screenshots but disables video because the pinned Playwright FFmpeg helper may not be installed. CI should use the pinned Playwright Chromium runtime for reproducibility and full video evidence.

Authenticated read-only checks use a dedicated bursar account in a non-production Supabase project:

```powershell
$env:E2E_BURSAR_EMAIL='e2e-bursar@example.test'
$env:E2E_BURSAR_PASSWORD='use-a-secret-store'
pnpm.cmd test:e2e:auth
```

Never commit credentials. CI must supply them from its secret store.

## Mutation safety gate

Financial browser journeys are deliberately refused unless every safety marker is present:

```powershell
$env:E2E_ALLOW_MUTATIONS='true'
$env:E2E_ISOLATED_ENVIRONMENT='true'
$env:E2E_SCHOOL_MARKER='E2E-HARAMBEEONE'
pnpm.cmd test:e2e:mutating
```

The target must be a dedicated resettable database and Supabase project containing no real learner, guardian, donor or financial data. A future reset command must validate the same school marker before deleting test records. Do not point mutation tests at local development data shared with demonstrations, staging used by people, or production.

Playwright keeps traces, screenshots and video for failed tests in ignored local artifact directories. CI should upload `playwright-report/` and `test-results/` on failure.

## External release blockers

The repository cannot supply these approvals by code:

- contracted licensed Ugandan collection and settlement providers;
- Ugandan payments, privacy and safeguarding legal review;
- independent application and infrastructure security assessment;
- production Supabase, SMTP, CAPTCHA, RPC, monitoring and secret-manager ownership;
- documented treasury and key-management authority before any Solana mainnet use.

Until those controls have named owners and evidence, use synthetic school data and Solana devnet only.
