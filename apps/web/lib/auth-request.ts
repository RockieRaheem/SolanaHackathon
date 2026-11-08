import { createHash } from 'node:crypto';
import { NextResponse, type NextRequest } from 'next/server';

type Attempt = { count: number; resetAt: number };

const attempts = new Map<string, Attempt>();
const WINDOW_MS = 10 * 60 * 1000;
const MAX_ATTEMPTS = 8;
const MAX_BODY_BYTES = 16 * 1024;

function clientAddress(request: NextRequest) {
  return request.headers.get('x-real-ip')
    ?? request.headers.get('x-forwarded-for')?.split(',')[0]?.trim()
    ?? 'unknown';
}

function fingerprint(request: NextRequest, scope: string, subject = '') {
  return createHash('sha256')
    .update(`${scope}|${clientAddress(request)}|${subject.toLowerCase()}`)
    .digest('hex');
}

export function requestProblem(request: NextRequest) {
  const origin = request.headers.get('origin');
  if (!origin || origin !== request.nextUrl.origin) {
    return jsonFailure(403, 'invalid_origin', 'This request could not be verified. Refresh and try again.');
  }
  const contentLength = Number(request.headers.get('content-length') ?? '0');
  if (!Number.isFinite(contentLength) || contentLength > MAX_BODY_BYTES) {
    return jsonFailure(413, 'request_too_large', 'The authentication request is too large.');
  }
  return null;
}

export function consumeAttempt(request: NextRequest, scope: string, subject = '') {
  const now = Date.now();
  if (attempts.size > 5_000) {
    for (const [key, attempt] of attempts) {
      if (attempt.resetAt <= now) attempts.delete(key);
    }
  }
  const key = fingerprint(request, scope, subject);
  const current = attempts.get(key);
  if (!current || current.resetAt <= now) {
    attempts.set(key, { count: 1, resetAt: now + WINDOW_MS });
    return null;
  }
  if (current.count >= MAX_ATTEMPTS) {
    return Math.max(1, Math.ceil((current.resetAt - now) / 1000));
  }
  current.count += 1;
  return null;
}

export function clearAttempts(request: NextRequest, scope: string, subject = '') {
  attempts.delete(fingerprint(request, scope, subject));
}

export function jsonFailure(status: number, code: string, detail: string, retryAfter?: number) {
  const response = NextResponse.json({ code, detail, retryAfter }, { status });
  response.headers.set('Cache-Control', 'no-store, max-age=0');
  response.headers.set('Pragma', 'no-cache');
  if (retryAfter) response.headers.set('Retry-After', String(retryAfter));
  return response;
}

export function noStore(response: NextResponse) {
  response.headers.set('Cache-Control', 'no-store, max-age=0');
  response.headers.set('Pragma', 'no-cache');
  return response;
}
