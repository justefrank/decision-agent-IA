import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import type { AssistantMessage } from '@/api/types';
import { AuthContext, type AuthState } from '@/auth/AuthProvider';
import { LiveRegion } from '@/shared/ui';

import { ConversationPage } from './ConversationPage';
import {
  CONVERSATIONS,
  STEPS,
  clarificationMsg,
  decideurVersion,
  detailOf,
  errorMsg,
  kpiAnswer,
  lineAnswer,
  refusalMsg,
} from './fixtures';

const NEW_ID = '99999999-9999-4999-8999-999999999999';

const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

const server = setupServer();
const realFetch = globalThis.fetch;

beforeAll(() => {
  // Node n'a pas d'origine pour les URL relatives : on les rattache à une origine fictive, comme le navigateur.
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) =>
    realFetch(typeof input === 'string' && input.startsWith('/') ? `http://localhost${input}` : input, init)) as typeof fetch;
  server.listen({ onUnhandledRequest: 'error' });
});
afterEach(() => server.resetHandlers());
afterAll(() => {
  server.close();
  globalThis.fetch = realFetch;
});

interface Calls {
  asked: string[];
  feedback: Record<string, unknown>[];
  deleted: string[];
}

/** Serveur simulé : la réponse au flux est fournie par chaque test. */
function mockApi(
  stream: (question: string) => Response | Promise<Response>,
  opts: { list?: typeof CONVERSATIONS; detail?: AssistantMessage } = {},
): Calls {
  const calls: Calls = { asked: [], feedback: [], deleted: [] };
  let list = opts.list ?? CONVERSATIONS;
  server.use(
    http.get('/api/conversations', () => HttpResponse.json(list)),
    http.post('/api/conversations', () =>
      HttpResponse.json({ id: NEW_ID, title: null, created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:00:00Z' }, { status: 201 }),
    ),
    http.post('/api/conversations/:id/messages', async ({ request }) => {
      const { question } = (await request.json()) as { question: string };
      calls.asked.push(question);
      return stream(question);
    }),
    http.get('/api/conversations/:id', ({ params }) =>
      HttpResponse.json(detailOf({ ...CONVERSATIONS[0]!, id: String(params.id) }, [{ q: 'Question posée', a: opts.detail ?? kpiAnswer }])),
    ),
    http.delete('/api/conversations/:id', ({ params }) => {
      calls.deleted.push(String(params.id));
      list = list.filter((c) => c.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.post('/api/feedback', async ({ request }) => {
      calls.feedback.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ id: 'f1', status: 'nouveau', question_attached: true }, { status: 201 });
    }),
  );
  return calls;
}

const answer = (m: AssistantMessage, withSteps = true) =>
  new HttpResponse((withSteps ? STEPS.map((s) => sse('step', s)).join('') : '') + sse('final', m), {
    headers: { 'Content-Type': 'text/event-stream' },
  });

/** Flux que le test pilote : les étapes arrivent, puis la suite attend `release()`. */
function gatedStream(final: AssistantMessage) {
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    async start(c) {
      c.enqueue(enc.encode(sse('step', STEPS[0])));
      c.enqueue(enc.encode(sse('step', STEPS[1])));
      await gate;
      c.enqueue(enc.encode(sse('final', final)));
      c.close();
    },
  });
  return { response: new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } }), release };
}

function renderPage(entry: string | { pathname: string; state?: unknown } = '/questions', questionMaxChars?: number) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const auth = { status: 'authenticated', me: { question_max_chars: questionMaxChars } } as unknown as AuthState;
  return render(
    <AuthContext.Provider value={questionMaxChars === undefined ? null : auth}>
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <LiveRegion />
        <Routes>
          <Route path="/questions" element={<ConversationPage />} />
          <Route path="/questions/:conversationId" element={<ConversationPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
    </AuthContext.Provider>,
  );
}

const box = () => screen.getByRole('textbox', { name: 'Votre question' });

async function ask(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(box(), `${text}{Enter}`);
}

describe('Page Questions', () => {
  it('accueille avec des exemples cliquables qui posent la question', async () => {
    const calls = mockApi(() => answer(kpiAnswer));
    const user = userEvent.setup();
    renderPage();
    expect(screen.getByText(/Interrogez les transactions Wave Sénégal/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Quelle est la valeur transférée ce mois-ci ?' }));
    await screen.findByText('1,23 milliard FCFA');
    expect(calls.asked).toEqual(['Quelle est la valeur transférée ce mois-ci ?']);
  });

  it('affiche la question tout de suite, les étapes, puis remplace les étapes par le reçu', async () => {
    const g = gatedStream(kpiAnswer);
    mockApi(() => g.response);
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur transférée en septembre ?');
    expect(screen.getByRole('heading', { name: 'Valeur transférée en septembre ?' })).toBeInTheDocument();
    const steps = await screen.findByRole('list', { name: 'Étapes du calcul' });
    await within(steps).findByText('Lecture des indicateurs');
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/Lecture des indicateurs|Analyse de la question/));
    g.release();
    await screen.findByText('1,23 milliard FCFA');
    expect(screen.queryByRole('list', { name: 'Étapes du calcul' })).not.toBeInTheDocument();
    expect(screen.getByText('Calcul certifié')).toBeInTheDocument();
    expect(screen.getByText('Origine du calcul')).toBeInTheDocument();
    expect(screen.getByText('Transactions réussies')).toBeInTheDocument();
  });

  it('envoie avec Entrée, saute une ligne avec Maj+Entrée et compte les caractères', async () => {
    const calls = mockApi(() => answer(kpiAnswer));
    const user = userEvent.setup();
    renderPage();
    await user.type(box(), 'ligne 1{Shift>}{Enter}{/Shift}ligne 2');
    expect(box()).toHaveValue('ligne 1\nligne 2');
    expect(screen.getByText(/15 \/ 1\s?000/)).toBeInTheDocument();
    expect(box()).toHaveAttribute('maxlength', '1000');
    await user.keyboard('{Enter}');
    await screen.findByText('1,23 milliard FCFA');
    expect(calls.asked).toEqual(['ligne 1\nligne 2']);
  });

  it('annule le flux avec « Arrêter »', async () => {
    const g = gatedStream(kpiAnswer);
    mockApi(() => g.response);
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Une question longue');
    await user.click(await screen.findByRole('button', { name: 'Arrêter' }));
    await screen.findByText('Calcul arrêté');
    expect(screen.getByRole('button', { name: 'Envoyer' })).toBeInTheDocument();
    g.release();
  });

  it('un clic sur une précision envoie le choix comme message', async () => {
    let n = 0;
    const calls = mockApi(() => answer(n++ === 0 ? clarificationMsg : kpiAnswer, false));
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Quel est le volume par région ?');
    await user.click(await screen.findByRole('button', { name: 'Région du client' }));
    await screen.findByText('1,23 milliard FCFA');
    expect(calls.asked).toEqual(['Quel est le volume par région ?', 'Région du client']);
  });

  it('un refus dit pourquoi et propose des questions possibles', async () => {
    mockApi(() => answer(refusalMsg, false));
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Combien font les concurrents ?');
    await screen.findByText('Cette question ne peut pas être traitée');
    expect(screen.getByText(/pas d’informations sur les concurrents/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Comment évolue le taux d’échec sur les trois derniers mois ?' })).toBeEnabled();
  });

  it('une erreur du flux affiche un message clair et Réessayer relance la question', async () => {
    let n = 0;
    const calls = mockApi(() =>
      n++ === 0
        ? new HttpResponse(sse('error', { code: 'agent_error', message: 'La réponse n’a pas pu être produite.', trace_id: 't' }), {
            headers: { 'Content-Type': 'text/event-stream' },
          })
        : answer(kpiAnswer, false),
    );
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur transférée ?');
    expect(await screen.findByRole('alert')).toHaveTextContent('La réponse n’a pas pu être produite');
    await user.click(screen.getByRole('button', { name: 'Réessayer' }));
    await screen.findByText('1,23 milliard FCFA');
    expect(calls.asked).toEqual(['Valeur transférée ?', 'Valeur transférée ?']);
    expect(screen.getAllByRole('heading', { name: 'Valeur transférée ?' })).toHaveLength(1);
  });

  it('un message d’erreur de l’agent (kind error) propose Réessayer', async () => {
    mockApi(() => answer(errorMsg, false));
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur ?');
    await screen.findByRole('button', { name: 'Réessayer' });
  });

  it('quota atteint (429) : donne l’heure de retour locale, sans bouton Réessayer', async () => {
    const retryAt = '2026-10-31T00:00:00Z';
    mockApi(() =>
      HttpResponse.json(
        { error: { code: 'quota_exceeded', message: 'Quota quotidien de questions atteint.', retry_at: retryAt } },
        { status: 429, headers: { 'Retry-After': '3600' } },
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur ?');
    const hhmm = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(retryAt));
    expect(
      await screen.findByText(`Limite de questions atteinte. Vous pourrez poser une nouvelle question à ${hhmm} (heure locale).`),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Réessayer' })).not.toBeInTheDocument();
  });

  it('quota atteint sans retry_at : l’heure se déduit de Retry-After', async () => {
    mockApi(() =>
      HttpResponse.json({ error: { code: 'quota_exceeded', message: 'x' } }, { status: 429, headers: { 'Retry-After': '7200' } }),
    );
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur ?');
    expect(await screen.findByText(/nouvelle question à \d{2}:\d{2} \(heure locale\)/)).toBeInTheDocument();
  });

  it('trop de flux simultanés (429) : dit dans combien de secondes réessayer', async () => {
    mockApi(() =>
      HttpResponse.json({ error: { code: 'too_many_streams', message: 'x' } }, { status: 429, headers: { 'Retry-After': '5' } }),
    );
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur ?');
    expect(await screen.findByText(/Vous pourrez poser une nouvelle question dans 5 secondes\./)).toBeInTheDocument();
  });

  it('la limite de la zone de saisie vient de me.question_max_chars', async () => {
    mockApi(() => answer(kpiAnswer));
    renderPage('/questions', 300);
    expect(box()).toHaveAttribute('maxlength', '300');
    expect(screen.getByText(/0 \/ 300/)).toBeInTheDocument();
  });

  it('flux coupé sans réponse : message et Réessayer', async () => {
    mockApi(() => new HttpResponse(sse('step', STEPS[0]), { headers: { 'Content-Type': 'text/event-stream' } }));
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur ?');
    expect(await screen.findByText(/connexion a été coupée/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument();
  });

  it('résultat vide : « Aucune donnée pour… », jamais un zéro', async () => {
    const { emptyAnswer } = await import('./fixtures');
    mockApi(() => answer(emptyAnswer, false));
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Clients actifs à Kédougou ?');
    expect(await screen.findByText(/Aucune donnée pour Septembre 2026, Kédougou\./)).toBeInTheDocument();
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
  });

  it('traduit les mentions en phrases françaises', async () => {
    mockApi(() => answer(lineAnswer, false));
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Taux d’échec ?');
    expect(await screen.findByText('Période non précisée : la période par défaut a été appliquée.')).toBeInTheDocument();
  });
});

describe('Volet « Voir le calcul »', () => {
  it('le décideur ne voit jamais de SQL', async () => {
    mockApi(() => answer(decideurVersion(kpiAnswer), false));
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur ?');
    await screen.findByText('1,23 milliard FCFA');
    expect(screen.queryByRole('button', { name: 'Voir le calcul' })).not.toBeInTheDocument();
    expect(screen.queryByText(/SELECT/)).not.toBeInTheDocument();
  });

  it('l’analyste déplie le SQL et les tables utilisées', async () => {
    mockApi(() => answer(kpiAnswer, false));
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur ?');
    const toggle = await screen.findByRole('button', { name: 'Voir le calcul' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/SUM\(t\.amount_xof\)/)).toBeInTheDocument();
    expect(screen.getByText('fact_transaction, dim_date')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copier le SQL' })).toBeInTheDocument();
  });
});

describe('Signalement', () => {
  it('envoie la catégorie avec le consentement explicite et annonce la confirmation', async () => {
    const calls = mockApi(() => answer(kpiAnswer, false));
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur ?');
    await user.click(await screen.findByRole('button', { name: 'Signaler la réponse' }));
    const dialog = await screen.findByRole('dialog', { name: 'Signaler cette réponse' });
    const consent = within(dialog).getByRole('checkbox', { name: /Joindre ma question/ });
    expect(consent).not.toBeChecked();
    await user.click(within(dialog).getByRole('button', { name: 'Envoyer le signalement' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Choisissez ce qui ne va pas.');
    await user.click(within(dialog).getByRole('radio', { name: 'Le chiffre est faux' }));
    await user.click(consent);
    await user.click(within(dialog).getByRole('button', { name: 'Envoyer le signalement' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(calls.feedback).toHaveLength(1);
    expect(calls.feedback[0]).toMatchObject({ category: 'chiffre_faux', consent_question: true });
    expect(calls.feedback[0]!.message_id).toMatch(/-a0$/);
    expect(await screen.findByText('Signalement envoyé')).toBeInTheDocument();
  });

  it('sans la case cochée, la question n’est pas jointe', async () => {
    const calls = mockApi(() => answer(kpiAnswer, false));
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'Valeur ?');
    await user.click(await screen.findByRole('button', { name: 'Signaler la réponse' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('radio', { name: 'Autre problème' }));
    await user.click(within(dialog).getByRole('button', { name: 'Envoyer le signalement' }));
    await waitFor(() => expect(calls.feedback).toHaveLength(1));
    expect(calls.feedback[0]).toMatchObject({ category: 'autre', consent_question: false });
  });
});

describe('Historique', () => {
  it('liste les conversations et supprime après confirmation', async () => {
    const calls = mockApi(() => answer(kpiAnswer));
    const user = userEvent.setup();
    renderPage();
    const nav = await screen.findByRole('navigation', { name: 'Historique des conversations' });
    expect(await within(nav).findByRole('link', { name: /Taux d’échec par région/ })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: /Conversation sans titre/ })).toBeInTheDocument();
    await user.click(within(nav).getByRole('button', { name: /Supprimer la conversation « Taux d’échec par région »/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Supprimer cette conversation ?' });
    await user.click(within(dialog).getByRole('button', { name: 'Annuler' }));
    expect(calls.deleted).toEqual([]);
    await user.click(within(nav).getByRole('button', { name: /Supprimer la conversation « Taux d’échec par région »/ }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Supprimer' }));
    await waitFor(() => expect(within(nav).queryByRole('link', { name: /Taux d’échec par région/ })).not.toBeInTheDocument());
    expect(calls.deleted).toEqual([CONVERSATIONS[1]!.id]);
  });

  it('ouvre une conversation existante depuis l’adresse et relit ses messages', async () => {
    mockApi(() => answer(kpiAnswer));
    renderPage(`/questions/${CONVERSATIONS[0]!.id}`);
    expect(await screen.findByRole('heading', { name: 'Question posée' })).toBeInTheDocument();
    expect(screen.getByText('1,23 milliard FCFA')).toBeInTheDocument();
  });

  it('pré-remplit la saisie sans l’envoyer (approfondissement depuis les indicateurs)', async () => {
    const calls = mockApi(() => answer(kpiAnswer));
    renderPage({ pathname: '/questions', state: { prefill: 'Pourquoi le taux d’échec baisse ?' } });
    expect(box()).toHaveValue('Pourquoi le taux d’échec baisse ?');
    expect(calls.asked).toEqual([]);
  });
});
