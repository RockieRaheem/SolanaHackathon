type ResponseSnapshot = {
  body: ArrayBuffer;
  headers: [string, string][];
  status: number;
  statusText: string;
};

type CacheEntry = {
  expiresAt: number;
  response: Promise<ResponseSnapshot>;
};

const responseCache = new Map<string, CacheEntry>();
const CACHE_WINDOW_MS = 2_000;
let sessionRedirectStarted = false;

function redirectExpiredSession(response: Response) {
  if (response.status !== 401 || typeof window === 'undefined' || sessionRedirectStarted) return;
  const currentPath = `${window.location.pathname}${window.location.search}`;
  const publicAuthRoute = /^\/(login|signup|forgot-password|reset-password|auth)(\/|$)/.test(
    window.location.pathname,
  );
  if (publicAuthRoute) return;
  sessionRedirectStarted = true;
  clearClientResponseCache();
  const params = new URLSearchParams({ error: 'session_expired', next: currentPath });
  window.location.replace(`/login?${params.toString()}`);
}

function requestDetails(input: RequestInfo | URL, init?: RequestInit) {
  const request = input instanceof Request ? input : null;
  const method = (init?.method ?? request?.method ?? 'GET').toUpperCase();
  const url = request?.url ?? input.toString();
  return { method, url };
}

function responseFrom(snapshot: ResponseSnapshot) {
  return new Response(snapshot.body.slice(0), {
    headers: snapshot.headers,
    status: snapshot.status,
    statusText: snapshot.statusText,
  });
}

export function clearClientResponseCache() {
  responseCache.clear();
}

export function markSessionRecovered() {
  sessionRedirectStarted = false;
  clearClientResponseCache();
}

/**
 * Coalesces identical browser reads over a tiny window. This prevents React's
 * development checks and rapidly remounted screens from hitting the API twice.
 * Writes always invalidate the cache before reaching the server.
 */
export async function clientFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const { method, url } = requestDetails(input, init);
  if (method !== 'GET') {
    clearClientResponseCache();
    const response = await globalThis.fetch(input, init);
    redirectExpiredSession(response);
    return response;
  }

  const now = Date.now();
  const cached = responseCache.get(url);
  if (cached && cached.expiresAt > now) return responseFrom(await cached.response);
  if (cached) responseCache.delete(url);

  const response = globalThis.fetch(input, init).then(async result => {
    const snapshot = {
      body: await result.arrayBuffer(),
      headers: Array.from(result.headers.entries()) as [string, string][],
      status: result.status,
      statusText: result.statusText,
    };
    const entry = responseCache.get(url);
    if (entry) entry.expiresAt = Date.now() + CACHE_WINDOW_MS;
    return snapshot;
  });
  responseCache.set(url, { expiresAt: Number.POSITIVE_INFINITY, response });

  try {
    const restoredResponse = responseFrom(await response);
    redirectExpiredSession(restoredResponse);
    return restoredResponse;
  } catch (error) {
    responseCache.delete(url);
    throw error;
  }
}
