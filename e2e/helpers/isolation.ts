import { expect, type APIResponse, type Page } from '@playwright/test';

type SchoolContext = {
  id: string;
  name: string;
  role: 'owner' | 'bursar' | 'cashier' | 'auditor';
  permissions: string[];
};

async function parseContext(response: APIResponse): Promise<SchoolContext> {
  expect(response.status()).toBe(200);
  return await response.json() as SchoolContext;
}

export async function assertIsolatedSchool(
  page: Page,
  expectedRole?: SchoolContext['role'],
): Promise<SchoolContext> {
  const expectedId = process.env.E2E_SCHOOL_ID ?? '';
  const marker = process.env.E2E_SCHOOL_MARKER ?? '';
  const context = await parseContext(await page.request.get('/api/current-school'));

  expect(context.id, 'authenticated account must belong to the exact E2E school').toBe(expectedId);
  expect(context.name, 'E2E school name must carry the configured isolation marker').toContain(marker);
  if (expectedRole) {
    expect(context.role).toBe(expectedRole);
  }
  expect(context.permissions.length).toBeGreaterThan(0);
  return context;
}
