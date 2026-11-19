import { test } from '@playwright/test';
import { signIn } from '../helpers/auth';
import { assertIsolatedSchool } from '../helpers/isolation';

test('mutation suite is bound to the exact isolated E2E school', async ({ page }) => {
  await signIn(
    page,
    process.env.E2E_OWNER_EMAIL ?? '',
    process.env.E2E_OWNER_PASSWORD ?? '',
  );
  await assertIsolatedSchool(page, 'owner');
});
