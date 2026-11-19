import { expect, test } from '@playwright/test';
import { signIn } from './helpers/auth';
import { assertIsolatedSchool } from './helpers/isolation';

const accounts = [
  {
    role: 'owner',
    email: process.env.E2E_OWNER_EMAIL ?? '',
    password: process.env.E2E_OWNER_PASSWORD ?? '',
  },
  {
    role: 'bursar',
    email: process.env.E2E_BURSAR_EMAIL ?? '',
    password: process.env.E2E_BURSAR_PASSWORD ?? '',
  },
  {
    role: 'cashier',
    email: process.env.E2E_CASHIER_EMAIL ?? '',
    password: process.env.E2E_CASHIER_PASSWORD ?? '',
  },
  {
    role: 'auditor',
    email: process.env.E2E_AUDITOR_EMAIL ?? '',
    password: process.env.E2E_AUDITOR_PASSWORD ?? '',
  },
] as const;

for (const account of accounts) {
  test(`${account.role} session resolves to its server-authorized school role`, async ({ page }) => {
    await signIn(page, account.email, account.password);

    const school = await assertIsolatedSchool(page, account.role);

    const canReadControls = account.role !== 'cashier';
    const auditResponse = await page.request.get(
      `/api/backend/api/v1/audit-events?school_id=${school.id}&limit=1`,
    );
    expect(auditResponse.status()).toBe(canReadControls ? 200 : 403);

    const reportsResponse = await page.request.get(
      `/api/backend/api/v1/reports/centre?school_id=${school.id}`,
    );
    expect(reportsResponse.status()).toBe(canReadControls ? 200 : 403);

    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/dashboard(?:\?|$)/);
    await expect(page.getByRole('heading', { name: 'Bursar command' }).first()).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
  });
}

test('dedicated bursar account can read the core financial workspaces', async ({ page }) => {
  const bursar = accounts.find((account) => account.role === 'bursar');
  expect(bursar).toBeDefined();
  await signIn(page, bursar!.email, bursar!.password);
  await assertIsolatedSchool(page, 'bursar');

  const workspaces = [
    ['/students', 'Student registry'],
    ['/payments', 'Payment desk'],
    ['/reconciliation', 'Reconciliation & cash-up'],
    ['/arrears', 'Collections worklist'],
    ['/reports', 'Financial reports'],
  ] as const;

  for (const [path, heading] of workspaces) {
    await page.goto(path);
    await expect(page).toHaveURL(new RegExp(`${path.replace('/', '\\/')}(?:\\?|$)`));
    await expect(page.getByRole('heading', { name: heading }).first()).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
  }
});
