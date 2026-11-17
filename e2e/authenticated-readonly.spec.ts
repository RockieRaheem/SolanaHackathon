import { expect, test } from '@playwright/test';
import { signIn } from './helpers/auth';

const email = process.env.E2E_BURSAR_EMAIL ?? '';
const password = process.env.E2E_BURSAR_PASSWORD ?? '';

test('dedicated bursar account can read the core financial workspaces', async ({ page }) => {
  await signIn(page, email, password);

  const workspaces = [
    ['/dashboard', 'Bursar command'],
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
