import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import { normalizeEmail, passwordProblem, safeNextPath, validEmail } from '@/lib/auth-policy';
import { clearAttempts, consumeAttempt, jsonFailure, noStore, requestProblem } from '@/lib/auth-request';
import { getSupabaseConfig } from '@/lib/supabase/config';

type PendingCookie = { name: string; value: string; options: CookieOptions };
type Credentials = {
  mode?: unknown;
  email?: unknown;
  password?: unknown;
  fullName?: unknown;
  nextPath?: unknown;
};

export async function POST(request: NextRequest) {
  const unsafeRequest = requestProblem(request);
  if (unsafeRequest) return unsafeRequest;

  let credentials: Credentials;
  try {
    credentials = await request.json();
  } catch {
    return jsonFailure(400, 'invalid_request', 'Enter your email address and password.');
  }

  const mode = credentials.mode === 'signup' ? 'signup' : 'login';
  const email = normalizeEmail(credentials.email);
  const password = typeof credentials.password === 'string' ? credentials.password : '';
  const fullName = typeof credentials.fullName === 'string' ? credentials.fullName.trim() : '';
  if (!validEmail(email) || !password) {
    return jsonFailure(422, 'invalid_request', 'Enter a valid email address and password.');
  }
  if (mode === 'signup' && (fullName.length < 2 || fullName.length > 100)) {
    return jsonFailure(422, 'invalid_request', 'Enter your full name.');
  }
  const weakPassword = mode === 'signup' ? passwordProblem(password) : '';
  if (weakPassword) return jsonFailure(422, 'weak_password', weakPassword);

  const retryAfter = consumeAttempt(request, mode, email);
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

  const callbackUrl = new URL('/auth/callback', request.nextUrl.origin);
  callbackUrl.searchParams.set('next', safeNextPath(credentials.nextPath));
  const result = mode === 'login'
    ? await supabase.auth.signInWithPassword({ email, password })
    : await supabase.auth.signUp({
        email,
        password,
        options: { data: { full_name: fullName }, emailRedirectTo: callbackUrl.toString() },
      });

  if (result.error) {
    if (mode === 'signup' && ['email_exists', 'user_already_exists'].includes(result.error.code ?? '')) {
      clearAttempts(request, mode, email);
      return noStore(NextResponse.json({ authenticated: false, confirmationRequired: true }));
    }
    return jsonFailure(
      result.error.status ?? 400,
      result.error.code ?? 'authentication_failed',
      'Authentication could not be completed.',
    );
  }
  if (mode === 'login' && !result.data.session) {
    return jsonFailure(401, 'session_not_created', 'A secure session could not be created.');
  }

  clearAttempts(request, mode, email);
  const response = NextResponse.json({
    authenticated: Boolean(result.data.session),
    confirmationRequired: mode === 'signup' && !result.data.session,
  });
  pendingCookies.forEach(cookie => response.cookies.set(cookie.name, cookie.value, cookie.options));
  return noStore(response);
}