import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import type { Me, Role } from '@/api/types';
import { AuthContext, type AuthState } from '@/auth/AuthProvider';

import { DashboardPage } from './DashboardPage';
import type { AnalysisResponse, DashboardData, Tile } from './types';

const NN = ' ';
const t = (v: string) => v.replaceAll(NN, ' '); // le DOM est normalisé par Testing Library
const tile = (over: Partial<Tile> & Pick<Tile, 'metric' | 'label'>): Tile => ({
  unit: 'count',
  available: true,
  value: 100,
  previous: 90,
  rendered: '100',
  rendered_previous: '90',
  delta_abs: 10,
  rendered_delta_abs: '+10',
  delta_pct: 11.1,
  rendered_delta_pct: `+11,1${NN}%`,
  delta_pp: null,
  fact_ids: {},
  ...over,
});

function dashboard(over: Partial<DashboardData> = {}): DashboardData {
  return {
    period: { start: '2026-09-01', end: '2026-09-30', label: 'septembre 2026' },
    compare_period: { start: '2026-08-01', end: '2026-08-31', label: 'août 2026' },
    region: null,
    errors: [],
    semantic_version: 'v1',
    tiles: [
      tile({
        metric: 'volume_transactions',
        label: 'Volume de transactions',
        rendered: `6${NN}950`,
        rendered_previous: `6${NN}794`,
        rendered_delta_abs: '+156',
        rendered_delta_pct: `+2,3${NN}%`,
        fact_ids: { current: 'f1', compare: 'f7', variation: 'd2' },
      }),
      tile({
        metric: 'clients_actifs',
        label: 'Clients actifs',
        rendered: `1${NN}808`,
        rendered_delta_pct: `−1,7${NN}%`,
        delta_pct: -1.7,
        fact_ids: { current: 'f4' },
      }),
      tile({
        metric: 'taux_echec',
        label: 'Taux d’échec',
        unit: 'ratio',
        rendered: `5,9${NN}%`,
        rendered_previous: `6,4${NN}%`,
        delta_pct: null,
        rendered_delta_pct: null,
        delta_abs: null,
        delta_pp: -0.45,
        rendered_delta_pp: `−0,5${NN}pt`,
        fact_ids: { current: 'f6', ecart_pp: 'd11' },
      }),
    ],
    ...over,
  };
}

function analysisBody(over: Partial<AnalysisResponse['analysis']> = {}, reused = false): AnalysisResponse {
  return {
    id: 'a1',
    reused,
    generated_at: new Date().toISOString(),
    data_hash: 'h',
    analysis: {
      period: { start: '2026-09-01', end: '2026-09-30', label: 'septembre 2026' },
      region: null,
      lead: 'Le volume de transactions progresse en septembre 2026.',
      findings: [
        {
          tag: 'Hausse',
          text: 'Le volume atteint 6 950 transactions.',
          confidence: 'elevee',
          sources: ['f1', 'd2'],
          hypothesis: 'La saison pourrait expliquer cette hausse.',
        },
        {
          tag: 'Écart',
          text: 'Kolda s’écarte de la moyenne.',
          confidence: 'hypothese',
          sources: ['f40'],
          hypothesis: null,
        },
      ],
      follow_up: ['Quelles régions ont le plus fort taux d’échec ?'],
      facts: [{ id: 'f40', value: 0.09, unit: 'ratio', label: 'Taux d’échec — Kolda', result_index: 1, rendered: '9 %' }],
      semantic_version: 'v1',
      model_id: 'm',
      available: true,
      ...over,
    },
  };
}

const requests: string[] = [];
let lastAnalysisBody: unknown = null;
const server = setupServer(
  http.get('*/api/dashboard', ({ request }) => {
    requests.push(new URL(request.url).search);
    return HttpResponse.json(dashboard());
  }),
);
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
  const realFetch = globalThis.fetch; // déjà intercepté par MSW
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) =>
    realFetch(typeof input === 'string' && input.startsWith('/') ? `http://localhost${input}` : input, init),
  );
});
afterEach(() => {
  server.resetHandlers();
  requests.length = 0;
  lastAnalysisBody = null;
});
afterAll(() => {
  server.close();
  vi.unstubAllGlobals();
});

function Probe() {
  const loc = useLocation();
  return <output data-testid="loc">{loc.pathname + loc.search}</output>;
}
function Questions() {
  const loc = useLocation();
  return <p>Page questions : {(loc.state as { prefill?: string } | null)?.prefill}</p>;
}

function renderPage(role: Role = 'decideur', url = '/indicateurs') {
  const auth = {
    status: 'authenticated',
    me: { sub: 'u', name: 'U', email: null, roles: [role], role, sees_sql: role !== 'decideur' } satisfies Me,
  } as unknown as AuthState;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter initialEntries={[url]}>
          <Probe />
          <Routes>
            <Route path="/indicateurs" element={<DashboardPage />} />
            <Route path="/questions" element={<Questions />} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

async function generate(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole('table');
  await user.click(await screen.findByRole('button', { name: 'Générer l’analyse' }));
}

const analysisHandler = (body: () => AnalysisResponse, wait = 0) =>
  http.post('*/api/dashboard/analysis', async ({ request }) => {
    lastAnalysisBody = await request.json();
    if (wait) await delay(wait);
    return HttpResponse.json(body());
  });

describe('relevé des indicateurs', () => {
  it('affiche une ligne par indicateur, avec écart signé et écart du taux d’échec en points', async () => {
    renderPage();
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row');
    expect(rows).toHaveLength(4); // en-tête + 3 indicateurs
    const volume = within(screen.getByRole('row', { name: /Volume de transactions/ }));
    expect(volume.getByText(t(`6${NN}950`))).toBeInTheDocument();
    expect(volume.getByText(t(`6${NN}794`))).toBeInTheDocument();
    expect(volume.getByText(t(`+2,3${NN}%`))).toBeInTheDocument();
    expect(volume.getByText(/en hausse/)).toBeInTheDocument();
    const clients = within(screen.getByRole('row', { name: /Clients actifs/ }));
    expect(clients.getByText(t(`−1,7${NN}%`))).toBeInTheDocument();
    expect(clients.getByText(/en baisse/)).toBeInTheDocument();
    const taux = within(screen.getByRole('row', { name: /Taux d’échec/ }));
    expect(taux.getByText(t(`−0,5${NN}pt`))).toBeInTheDocument();
    expect(taux.getByText('écart en points')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Relevé de septembre 2026' })).toBeInTheDocument();
  });

  it('synchronise période et région avec l’URL et recharge le relevé', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole('table');
    const periode = screen.getByLabelText('Période');
    expect(within(periode).getAllByRole('option')).toHaveLength(18);
    await user.selectOptions(periode, '2026-03');
    await user.selectOptions(screen.getByLabelText('Région'), 'Kolda');
    expect(screen.getByTestId('loc')).toHaveTextContent('/indicateurs?periode=2026-03&region=Kolda');
    await waitFor(() => expect(requests).toContain('?period=2026-03&region=Kolda'));
    // revenir au mois de référence retire le paramètre
    await user.selectOptions(screen.getByLabelText('Période'), '2026-09');
    expect(screen.getByTestId('loc')).toHaveTextContent('/indicateurs?region=Kolda');
  });

  it('lit la période et la région depuis l’URL', async () => {
    renderPage('decideur', '/indicateurs?periode=2026-03&region=Kolda');
    await waitFor(() => expect(requests).toContain('?period=2026-03&region=Kolda'));
    expect(screen.getByLabelText('Région')).toHaveValue('Kolda');
    expect(await screen.findByLabelText('Période')).toHaveValue('2026-03');
  });

  it('montre un indicateur indisponible avec sa raison sans casser le reste', async () => {
    server.use(
      http.get('*/api/dashboard', () => {
        const d = dashboard({ errors: ['Période de comparaison hors des données.'] });
        d.tiles[1] = { metric: 'clients_actifs', label: 'Clients actifs', unit: 'count', available: false };
        return HttpResponse.json(d);
      }),
    );
    renderPage();
    const row = within(await screen.findByRole('row', { name: /Clients actifs/ }));
    expect(row.getByText('Indisponible')).toBeInTheDocument();
    expect(row.getByText('Période de comparaison hors des données.')).toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /Volume de transactions/ })).getByText(t(`6${NN}950`))).toBeInTheDocument();
  });

  it('annonce un tableau de bord momentanément indisponible sur 503', async () => {
    server.use(
      http.get('*/api/dashboard', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'x' } }, { status: 503 }),
      ),
    );
    renderPage();
    expect(await screen.findByText('Tableau de bord momentanément indisponible')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument();
  });

  it('affiche une erreur avec Réessayer, et recharge au clic', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('*/api/dashboard', () =>
        HttpResponse.json({ error: { code: 'invalid_period', message: 'Période invalide.' } }, { status: 422 }),
      ),
    );
    renderPage();
    expect(await screen.findByText('Période invalide.')).toBeInTheDocument();
    server.use(http.get('*/api/dashboard', () => HttpResponse.json(dashboard())));
    await user.click(screen.getByRole('button', { name: 'Réessayer' }));
    expect(await screen.findByRole('table')).toBeInTheDocument();
  });
});

describe('analyse de l’agent', () => {
  it('montre les étapes pendant la génération puis le résultat', async () => {
    const user = userEvent.setup();
    server.use(analysisHandler(() => analysisBody(), 400));
    renderPage('analyste');
    await generate(user);
    expect(await screen.findByText('Analyse en cours')).toBeInTheDocument();
    expect(screen.getByText('Lecture des indicateurs')).toBeInTheDocument();
    expect(screen.getByText('Comparaison avec la période précédente')).toBeInTheDocument();
    expect(screen.getByText('Recherche d’écarts par région')).toBeInTheDocument();
    expect(await screen.findByText('Le volume de transactions progresse en septembre 2026.')).toBeInTheDocument();
    expect(lastAnalysisBody).toEqual({ period: '2026-09', region: null, regenerate: false });
    expect(screen.queryByText('Analyse en cours')).not.toBeInTheDocument();
  });

  it('étiquette les constats : confiance en toutes lettres et hypothèse bien visible', async () => {
    const user = userEvent.setup();
    server.use(analysisHandler(() => analysisBody()));
    renderPage('analyste');
    await generate(user);
    expect(await screen.findByText('Hausse')).toBeInTheDocument();
    expect(screen.getByText('Confiance élevée')).toBeInTheDocument();
    // hypothèse portée par le constat (champ `hypothesis`) : mot « Hypothèse » + mention de non-vérification
    expect(screen.getByText('La saison pourrait expliquer cette hausse.')).toBeInTheDocument();
    expect(screen.getByText('Non vérifiée dans les données.')).toBeInTheDocument();
    // constat dont la confiance est « hypothèse »
    expect(screen.getAllByText('Écart').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Hypothèse').length).toBeGreaterThanOrEqual(2);
  });

  it('met en évidence la ligne du relevé citée par une source', async () => {
    const user = userEvent.setup();
    server.use(analysisHandler(() => analysisBody()));
    renderPage('analyste');
    await generate(user);
    const src = await screen.findByRole('button', { name: 'Voir la ligne Volume de transactions dans le relevé' });
    expect(screen.getByRole('row', { name: /Volume de transactions/ })).not.toHaveAttribute('data-highlight');
    await user.click(src);
    expect(screen.getByRole('row', { name: /Volume de transactions/ })).toHaveAttribute('data-highlight', 'true');
    // un fait régional absent du relevé reste lisible mais n’est pas cliquable
    expect(screen.getByText('Taux d’échec — Kolda')).toBeInTheDocument();
  });

  it('ouvre /questions avec la question d’approfondissement pré-remplie', async () => {
    const user = userEvent.setup();
    server.use(analysisHandler(() => analysisBody()));
    renderPage('decideur');
    await generate(user);
    await user.click(await screen.findByRole('button', { name: /Quelles régions ont le plus fort taux d’échec/ }));
    expect(await screen.findByText('Page questions : Quelles régions ont le plus fort taux d’échec ?')).toBeInTheDocument();
    expect(screen.getByTestId('loc')).toHaveTextContent('/questions');
  });

  it('ne propose pas la régénération au décideur, mais réaffiche l’analyse existante', async () => {
    const user = userEvent.setup();
    server.use(analysisHandler(() => analysisBody({}, true)));
    renderPage('decideur');
    await generate(user);
    expect(await screen.findByText(/Analyse déjà produite le/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Régénérer l’analyse' })).not.toBeInTheDocument();
  });

  it('propose la régénération à l’analyste, avec un délai de 60 s entre deux générations', async () => {
    const user = userEvent.setup();
    server.use(analysisHandler(() => analysisBody()));
    renderPage('analyste');
    await generate(user);
    const regen = await screen.findByRole('button', { name: 'Régénérer l’analyse' });
    expect(regen).toBeDisabled();
    expect(screen.getByText(/Nouvelle génération possible dans \d+ s/)).toBeInTheDocument();
  });

  it('régénère avec regenerate=true quand le délai est passé', async () => {
    const user = userEvent.setup();
    server.use(analysisHandler(() => ({ ...analysisBody(), generated_at: '2026-09-30T10:00:00Z' })));
    renderPage('admin');
    await generate(user);
    await user.click(await screen.findByRole('button', { name: 'Régénérer l’analyse' }));
    await waitFor(() => expect(lastAnalysisBody).toEqual({ period: '2026-09', region: null, regenerate: true }));
  });

  it('explique clairement un 429 et laisse le relevé affiché', async () => {
    const user = userEvent.setup();
    server.use(
      http.post('*/api/dashboard/analysis', () =>
        HttpResponse.json({ error: { code: 'rate_limited', message: 'x' } }, { status: 429 }),
      ),
    );
    renderPage('analyste');
    await generate(user);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/Patientez une minute/);
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(within(alert).getByRole('button', { name: 'Réessayer' })).toBeInTheDocument();
  });

  it('signale une analyse indisponible sans toucher au relevé', async () => {
    const user = userEvent.setup();
    server.use(
      analysisHandler(() =>
        analysisBody({ available: false, findings: [], lead: 'Analyse indisponible.', follow_up: [] }),
      ),
    );
    renderPage('decideur');
    await generate(user);
    expect(await screen.findByRole('heading', { name: 'Analyse indisponible' })).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('explique un 503 de l’analyse', async () => {
    const user = userEvent.setup();
    server.use(
      http.post('*/api/dashboard/analysis', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'x' } }, { status: 503 }),
      ),
    );
    renderPage('decideur');
    await generate(user);
    expect(await screen.findByRole('alert')).toHaveTextContent(/momentanément indisponible/);
  });
});
