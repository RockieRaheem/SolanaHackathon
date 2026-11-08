import { createClient } from '@/lib/supabase/server';
import { cookies } from 'next/headers';

const BACKEND_REQUEST_TIMEOUT_MS = 15_000;
const BACKEND_UNAVAILABLE = 'The HarambeeOne API is not responding. Stop duplicate dev servers, then restart pnpm dev.';

export function backendApiOrigin() {
  return process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:4101';
}

export async function backendFetch(path: string, init: RequestInit = {}) {
  if (!path.startsWith('/api/v1/')) {
    throw new Error('Only HarambeeOne API routes may be requested');
  }
  try {
    return await fetch(new URL(path, backendApiOrigin()), {
      ...init,
      cache: 'no-store',
      signal: init.signal ?? AbortSignal.timeout(BACKEND_REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    console.error('HarambeeOne backend request failed', {
      path,
      cause: error instanceof Error ? error.message : 'unknown error',
    });
    return Response.json(
      { detail: BACKEND_UNAVAILABLE, code: 'BACKEND_UNAVAILABLE' },
      { status: 503 },
    );
  }
}

export async function authorizedBackendFetch(path: string, init: RequestInit = {}) {
  if (!path.startsWith('/api/v1/')) {
    throw new Error('Only HarambeeOne API routes may be requested');
  }

  const supabase = await createClient();
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData.session?.access_token;
  if (!token) return Response.json({ detail: 'Sign in required' }, { status: 401 });

  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token}`);
  headers.set('Accept', 'application/json');
  const activeSchoolId = (await cookies()).get('harambee-school-id')?.value;
  if (activeSchoolId && !headers.has('X-School-ID')) headers.set('X-School-ID', activeSchoolId);
  return backendFetch(path, { ...init, headers });
}
