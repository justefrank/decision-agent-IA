import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterAll, afterEach, beforeAll } from 'vitest';

export const server = setupServer();
export const A = (path: string) => `/api/admin/${path}`;

/** Démarre MSW : les chemins relatifs (`/api/...`) sont résolus par MSW contre l'adresse de jsdom. */
export function setupMsw(): void {
  beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
  afterEach(() => server.resetHandlers());
  afterAll(() => server.close());
}

export function renderAt(ui: ReactElement, { path = '/', route = '/' } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const json = (path: string, body: unknown, status = 200) =>
  http.get(A(path), () => HttpResponse.json(body as never, { status }));
export const forbidden = (path: string) =>
  http.get(A(path), () => HttpResponse.json({ error: { code: 'forbidden', message: 'Rôle insuffisant.' } }, { status: 403 }));
export const failing = (path: string) =>
  http.get(A(path), () => HttpResponse.json({ error: { code: 'boom', message: 'Le service ne répond pas.' } }, { status: 400 }));
