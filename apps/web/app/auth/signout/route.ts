import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import { noStore, requestProblem } from '@/lib/auth-request';
import { getSupabaseConfig } from '@/lib/supabase/config';

type PendingCookie = { name: string; value: string; options: CookieOptions };

export async function POST(request: NextRequest) {
  const unsafeRequest = requestProblem(request);
  if (unsafeRequest) return unsafeRequest;

  const pendingCookies: PendingCookie[] = [];
  const { url, publishableKey } = getSupabaseConfig();
  const supabase = createServerClient(url, publishableKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: cookies => { pendingCookies.push(...cookies); },
    },
  });
  await supabase.auth.signOut({ scope: 'local' });

  const response = NextResponse.json({ signedOut: true });
  pendingCookies.forEach(cookie => response.cookies.set(cookie.name, cookie.value, cookie.options));
  return noStore(response);
}
