import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import { normalizeEmail, passwordProblem, validEmail } from '@/lib/auth-policy';
import { consumeAttempt, jsonFailure, noStore, requestProblem } from '@/lib/auth-request';
import { getSupabaseConfig } from '@/lib/supabase/config';

type PendingCookie = { name: string; value: string; options: CookieOptions };

export async function POST(request: NextRequest) {
  const unsafeRequest = requestProblem(request);
  if (unsafeRequest) return unsafeRequest;

  let body: { action?: unknown; email?: unknown; password?: unknown };
  try {
    body = await request.json();
  } catch {
    return jsonFailure(400, 'invalid_request', 'Enter the requested account information.');
  }

  const action = body.action === 'update' ? 'update' : 'request';
  const email = normalizeEmail(body.email);
  const subject = action === 'request' ? email : 'authenticated-recovery';
  if (action === 'request' && !validEmail(email)) {
    return jsonFailure(422, 'invalid_request', 'Enter a valid email address.');
  }
  const password = typeof body.password === 'string' ? body.password : '';
  const weakPassword = action === 'update' ? passwordProblem(password) : '';
  if (weakPassword) return jsonFailure(422, 'weak_password', weakPassword);

  const retryAfter = consumeAttempt(request, `recovery-${action}`, subject);
  if (retryAfter) {
    return jsonFailure(429, 'over_request_rate_limit', 'Too many attempts. Try again later.', retryAfter);
  }

  const pendingCookies: PendingCookie[] = [];
  const { url, publishableKey } = getSupabaseConfig();
  const supabase = createServerClient(url, publishableKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: cookies => { pendingCookies.push(...cookies); },
    },
  });

  const result = action === 'request'
    ? await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: new URL('/auth/callback?next=/reset-password', request.nextUrl.origin).toString(),
      })
    : await supabase.auth.updateUser({ password });

  if (result.error) {
    return jsonFailure(
      result.error.status ?? 400,
      result.error.code ?? 'recovery_failed',
      'Password recovery could not be completed.',
    );
  }

  if (action === 'update') await supabase.auth.signOut({ scope: 'global' });

  const response = NextResponse.json({ ok: true });
  pendingCookies.forEach(cookie => response.cookies.set(cookie.name, cookie.value, cookie.options));
  return noStore(response);
}
