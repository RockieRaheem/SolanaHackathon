import { expect, test } from '@playwright/test';

test.describe('public security boundary', () => {
  test('health endpoint is reachable without exposing implementation headers', async ({ request }) => {
    const response = await request.get('/api/health');
    expect(response.status()).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      ok: true,
      service: 'harambeeone-web',
    });
    expect(response.headers()['x-powered-by']).toBeUndefined();
  });

  test('protected school workspace redirects a signed-out user to login', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login\?/);
    const current = new URL(page.url());
    expect(current.searchParams.get('next')).toBe('/dashboard');
    await expect(page.getByRole('heading', { name: 'Sign in to your workspace' })).toBeVisible();
  });

  test('browser responses carry the required baseline security headers', async ({ request }) => {
    const response = await request.get('/login');
    expect(response.status()).toBe(200);
    const headers = response.headers();
    expect(headers['x-content-type-options']).toBe('nosniff');
    expect(headers['x-frame-options']).toBe('DENY');
    expect(headers['referrer-policy']).toBe('strict-origin-when-cross-origin');
    expect(headers['permissions-policy']).toContain('camera=()');
    expect(headers['content-security-policy']).toBeTruthy();
  });

  test('invalid password login fails without leaving the authentication boundary', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email address').fill(`not-a-user-${Date.now()}@example.invalid`);
    await page.locator('input[name="password"]').fill('invalid-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('alert')).toBeVisible({ timeout: 20_000 });
    await expect(page).toHaveURL(/\/login(?:\?|$)/);
  });
});
