import { NextResponse } from 'next/server';
import { authorizedBackendFetch } from '@/lib/api/server';

async function forward(path: string, init: RequestInit = {}) {
  const response = await authorizedBackendFetch(path, init);
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: {'Content-Type': response.headers.get('Content-Type') ?? 'application/json'},
  });
}

export async function GET() {
  return forward('/api/v1/me/context');
}

export async function POST(request: Request) {
  const created = await authorizedBackendFetch('/api/v1/onboarding/school', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:await request.text(),
  });
  if (!created.ok) {
    return new NextResponse(await created.text(), {
      status: created.status,
      headers: {'Content-Type': created.headers.get('Content-Type') ?? 'application/json'},
    });
  }
  return forward('/api/v1/me/context');
}
