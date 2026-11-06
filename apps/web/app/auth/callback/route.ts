import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import { getSupabaseConfig } from '@/lib/supabase/config';

type PendingCookie = { name:string; value:string; options:CookieOptions };

function safeNext(value:string|null) {
  return value?.startsWith('/') && !value.startsWith('//') ? value : '/workspace';
}

function loginError(request:NextRequest, code:string) {
  const loginUrl = new URL('/login', request.nextUrl.origin);
  loginUrl.searchParams.set('error', code);
  return NextResponse.redirect(loginUrl);
}

export async function GET(request:NextRequest) {
  const providerError = request.nextUrl.searchParams.get('error_description');
  if (providerError) {
    console.error('[auth/callback] Provider rejected sign-in', providerError);
    return loginError(request, 'oauth_failed');
  }

  const code = request.nextUrl.searchParams.get('code');
  if (!code) return loginError(request, 'flow_state_not_found');

  const pendingCookies:PendingCookie[] = [];
  const { url, publishableKey } = getSupabaseConfig();
  const supabase = createServerClient(url, publishableKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: cookies => { pendingCookies.push(...cookies); },
    },
  });
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    console.error('[auth/callback] Code exchange failed', error.code ?? 'exchange_failed', error.message);
    return loginError(request, error.code === 'flow_state_expired' ? 'flow_state_expired' : 'oauth_failed');
  }

  const response = NextResponse.redirect(new URL(safeNext(request.nextUrl.searchParams.get('next')), request.nextUrl.origin));
  pendingCookies.forEach(cookie => response.cookies.set(cookie.name, cookie.value, cookie.options));
  return response;
}
