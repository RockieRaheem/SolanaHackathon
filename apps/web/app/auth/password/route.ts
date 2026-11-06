import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import { getSupabaseConfig } from '@/lib/supabase/config';

type PendingCookie = { name: string; value: string; options: CookieOptions };
type Credentials = {
  mode?: unknown;
  email?: unknown;
  password?: unknown;
  fullName?: unknown;
  nextPath?: unknown;
};

function safePath(value: unknown) {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : '/workspace';
}

function failure(status: number, code: string, detail: string) {
  return NextResponse.json({ code, detail }, { status });
}

export async function POST(request: NextRequest) {
  let credentials: Credentials;
  try {
    credentials = await request.json();
  } catch {
    return failure(400, 'invalid_request', 'Enter your email address and password.');
  }

  const mode = credentials.mode === 'signup' ? 'signup' : 'login';
  const email = typeof credentials.email === 'string' ? credentials.email.trim().toLowerCase() : '';
  const password = typeof credentials.password === 'string' ? credentials.password : '';
  const fullName = typeof credentials.fullName === 'string' ? credentials.fullName.trim() : '';
  if (!email || !password) return failure(422, 'invalid_request', 'Enter your email address and password.');
  if (mode === 'signup' && (!fullName || password.length < 10 || !/[A-Za-z]/.test(password) || !/\d/.test(password))) {
    return failure(422, 'weak_password', 'Use at least 10 characters with a letter and a number.');
  }

  const pendingCookies: PendingCookie[] = [];
  const { url, publishableKey } = getSupabaseConfig();
  const supabase = createServerClient(url, publishableKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: cookies => {
        pendingCookies.push(...cookies);
      },
    },
  });

  const callbackUrl = new URL('/auth/callback', request.nextUrl.origin);
  callbackUrl.searchParams.set('next', safePath(credentials.nextPath));
  const result = mode === 'login'
    ? await supabase.auth.signInWithPassword({ email, password })
    : await supabase.auth.signUp({
        email,
        password,
        options: { data: { full_name: fullName }, emailRedirectTo: callbackUrl.toString() },
      });

  if (result.error) {
    return failure(
      result.error.status ?? 400,
      result.error.code ?? 'authentication_failed',
      'Authentication could not be completed.',
    );
  }
  if (mode === 'login' && !result.data.session) {
    return failure(401, 'session_not_created', 'A secure session could not be created.');
  }

  const response = NextResponse.json({
    authenticated: Boolean(result.data.session),
    confirmationRequired: mode === 'signup' && !result.data.session,
  });
  pendingCookies.forEach(cookie => response.cookies.set(cookie.name, cookie.value, cookie.options));
  response.headers.set('Cache-Control', 'no-store');
  return response;
}
