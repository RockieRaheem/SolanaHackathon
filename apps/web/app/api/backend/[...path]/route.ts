import { NextRequest, NextResponse } from 'next/server';
import { authorizedBackendFetch } from '@/lib/api/server';

type RouteContext = { params: Promise<{ path: string[] }> };

async function forward(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const backendPath = `/${path.join('/')}${request.nextUrl.search}`;
  if (!backendPath.startsWith('/api/v1/')) {
    return NextResponse.json({ detail: 'API route not found' }, { status: 404 });
  }

  const headers = new Headers();
  const contentType = request.headers.get('content-type');
  if (contentType) headers.set('Content-Type', contentType);
  const hasBody = !['GET', 'HEAD'].includes(request.method);
  const response = await authorizedBackendFetch(backendPath, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
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
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
