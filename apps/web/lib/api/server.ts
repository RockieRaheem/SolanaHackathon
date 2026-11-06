import { createClient } from '@/lib/supabase/server';
import { cookies } from 'next/headers';

export function backendApiOrigin() {
  return process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:4100';
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
  return fetch(new URL(path, backendApiOrigin()), { ...init, headers, cache: 'no-store' });
}
