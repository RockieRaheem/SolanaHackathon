import { NextRequest, NextResponse } from 'next/server';
import { backendApiOrigin } from '@/lib/api/server';

type RouteContext = { params: Promise<{ path: string[] }> };

async function forward(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const suffix = path.join('/');
  if (!suffix || suffix.includes('..')) {
    return NextResponse.json({ detail: 'Public support route not found' }, { status: 404 });
  }
  const target = new URL(`/api/v1/support/public/${suffix}${request.nextUrl.search}`, backendApiOrigin());
  const headers = new Headers({ Accept: 'application/json' });
  const contentType = request.headers.get('content-type');
  if (contentType) headers.set('Content-Type', contentType);
  const response = await fetch(target, {
    method: request.method,
    headers,
    body: request.method === 'POST' ? await request.arrayBuffer() : undefined,
    cache: 'no-store',
  });
  return new NextResponse(response.body, {
    status: response.status,
    headers: {
      'Content-Type': response.headers.get('content-type') ?? 'application/json',
      'Cache-Control': 'no-store',
    },
  });
}

export const GET = forward;
export const POST = forward;
