import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import { getSupabaseConfig } from './config';

const publicRoutes = ['/login', '/signup', '/forgot-password', '/auth/google', '/auth/password', '/auth/callback', '/auth/error', '/support', '/api/support'];
const sessionFreeRoutes = ['/auth/google', '/auth/password', '/auth/callback', '/auth/error', '/support', '/api/support'];

function isPublicRoute(pathname: string) {
  return publicRoutes.some((route) => pathname === route || pathname.startsWith(`${route}/`));
}

function copySessionCookies(target: NextResponse, source: NextResponse) {
  source.cookies.getAll().forEach(cookie => target.cookies.set(cookie));
  return target;
}

function clearSupabaseCookies(request: NextRequest) {
  const response = NextResponse.next({ request });
  request.cookies
    .getAll()
    .filter(cookie => cookie.name.startsWith('sb-'))
    .forEach(cookie => {
      response.cookies.set(cookie.name, '', {
        expires: new Date(0),
        maxAge: 0,
        path: '/',
      });
    });
  return response;
}

export async function updateSession(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  if (sessionFreeRoutes.some((route) => pathname === route || pathname.startsWith(`${route}/`))) {
    return NextResponse.next({ request });
  }

  const recoveringInvalidSession =
    (pathname === '/login' || pathname === '/signup') &&
    request.nextUrl.searchParams.get('error') === 'session_expired';
  if (recoveringInvalidSession) {
    // The API has rejected this browser session. Render authentication and remove
    // every Supabase cookie instead of redirecting the stale session back to /workspace.
    return clearSupabaseCookies(request);
  }

  let response = NextResponse.next({ request });
  const { url, publishableKey } = getSupabaseConfig();
  const supabase = createServerClient(url, publishableKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (cookiesToSet) => {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });

  const { data } = await supabase.auth.getClaims();
  const signedIn = Boolean(data?.claims?.sub);
  if (!signedIn && !isPublicRoute(pathname)) {
    if (pathname.startsWith('/api/')) {
      return NextResponse.json({ detail: 'Sign in required' }, { status: 401 });
    }
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = '/login';
    loginUrl.searchParams.set('next', `${pathname}${request.nextUrl.search}`);
    if (request.cookies.getAll().some(cookie => cookie.name.startsWith('sb-'))) {
      loginUrl.searchParams.set('error', 'session_expired');
    }
    return copySessionCookies(NextResponse.redirect(loginUrl), response);
  }

  if (signedIn && (pathname === '/login' || pathname === '/signup')) {
    const dashboardUrl = request.nextUrl.clone();
    dashboardUrl.pathname = '/workspace';
    dashboardUrl.search = '';
    return copySessionCookies(NextResponse.redirect(dashboardUrl), response);
  }

  return response;
}
