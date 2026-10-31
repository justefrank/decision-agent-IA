import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import { api, ApiError } from './client';

const server = setupServer();
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
  const realFetch = globalThis.fetch;
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) =>
    realFetch(typeof input === 'string' && input.startsWith('/') ? `http://localhost${input}` : input, init),
  );
});
afterEach(() => server.resetHandlers());
afterAll(() => {
  server.close();
  vi.unstubAllGlobals();
});

async function failure(res: () => Response): Promise<ApiError> {
  server.use(http.get('*/api/x', () => res()));
  try {
    await api('/x');
  } catch (e) {
    return e as ApiError;
  }
  throw new Error('une erreur était attendue');
}

describe('ApiError', () => {
  it('lit Retry-After et retry_at sur un 429', async () => {
    const e = await failure(() =>
      HttpResponse.json(
        { error: { code: 'quota_exceeded', message: 'Quota atteint.', request_id: 'r1', retry_at: '2026-10-31T00:00:00Z' } },
        { status: 429, headers: { 'Retry-After': '1234' } },
      ),
    );
    expect(e).toMatchObject({ status: 429, code: 'quota_exceeded', requestId: 'r1', retryAfterS: 1234, retryAt: '2026-10-31T00:00:00Z' });
  });

  it('retry_at et Retry-After restent absents quand l’API ne les donne pas', async () => {
    const e = await failure(() => HttpResponse.json({ error: { code: 'forbidden', message: 'Non.' } }, { status: 403 }));
    expect(e.retryAfterS).toBeUndefined();
    expect(e.retryAt).toBeUndefined();
  });

  it('ignore un Retry-After qui n’est pas un nombre de secondes', async () => {
    const e = await failure(() =>
      HttpResponse.json({ error: { code: 'too_many_streams', message: 'x' } }, { status: 429, headers: { 'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT' } }),
    );
    expect(e.retryAfterS).toBeUndefined();
  });
});
