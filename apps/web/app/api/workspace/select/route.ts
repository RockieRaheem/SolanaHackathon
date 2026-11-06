import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';
import { authorizedBackendFetch } from '@/lib/api/server';

function safeNext(value: string | null) {
  return value?.startsWith('/') && !value.startsWith('//') ? value : '/dashboard';
}

export async function GET(request: NextRequest) {
  const schoolId = request.nextUrl.searchParams.get('school_id');
  if (!schoolId || !/^[0-9a-f-]{36}$/i.test(schoolId)) {
    return NextResponse.redirect(new URL('/workspace', request.url));
  }
  const access = await authorizedBackendFetch('/api/v1/me/context', {
    headers: { 'X-School-ID': schoolId },
  });
  if (!access.ok) {
    return NextResponse.redirect(new URL('/workspace?error=school_access', request.url));
  }
  const cookieStore = await cookies();
  cookieStore.set('harambee-school-id', schoolId, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: 60 * 60 * 24 * 30,
  });
  return NextResponse.redirect(new URL(safeNext(request.nextUrl.searchParams.get('next')), request.url));
}
