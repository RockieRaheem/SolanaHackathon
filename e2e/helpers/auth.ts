import { expect, type Page } from '@playwright/test';

export async function signIn(page: Page, email: string, password: string) {
  await page.goto('/login?next=/dashboard');
  await page.getByLabel('Email address').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/, { timeout: 20_000 });
}
