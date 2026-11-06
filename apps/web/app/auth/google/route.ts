import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import { getSupabaseConfig } from '@/lib/supabase/config';

type PendingCookie = { name:string; value:string; options:CookieOptions };

function safeNext(value:string|null) {
  return value?.startsWith('/') && !value.startsWith('//') ? value : '/workspace';
}

export async function GET(request:NextRequest) {
  const next = safeNext(request.nextUrl.searchParams.get('next'));
  const callbackUrl = new URL('/auth/callback', request.nextUrl.origin);
  callbackUrl.searchParams.set('next', next);
  const pendingCookies:PendingCookie[] = [];
  const { url, publishableKey } = getSupabaseConfig();
  const supabase = createServerClient(url, publishableKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: cookies => { pendingCookies.push(...cookies); },
    },
  });

  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: callbackUrl.toString(), skipBrowserRedirect: true },
  });

  if (error || !data.url) {
    console.error('[auth/google] OAuth initiation failed', error?.code ?? 'missing_redirect_url', error?.message ?? 'No provider URL returned');
    const loginUrl = new URL('/login', request.nextUrl.origin);
    loginUrl.searchParams.set('error', 'oauth_failed');
    return NextResponse.redirect(loginUrl);
  }

  const response = NextResponse.redirect(data.url);
  pendingCookies.forEach(cookie => response.cookies.set(cookie.name, cookie.value, cookie.options));
  return response;
}
