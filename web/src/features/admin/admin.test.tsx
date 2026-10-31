import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import type { ReactElement } from 'react';
import { describe, expect, it } from 'vitest';

import {
  AdminAuditPage,
  AdminEvalPage,
  AdminFeedbackPage,
  AdminKpiPage,
  AdminOverviewPage,
  AdminSecurityPage,
  AdminSemanticPage,
  AdminSettingsPage,
} from './AdminPages';
import { honestSentence, wilson } from './EvalPage';
import { A, failing, forbidden, json, renderAt, server, setupMsw } from './testUtils';

setupMsw();

const HEALTH = { status: 'ok', db: 'ok', mcp: 'ok', agent: 'ok' };
const OVERVIEW = {
  range: '7d',
  since: '2026-10-17T00:00:00Z',
  questions: 42,
  traces: 40,
  answers: 40,
  latency_ms: { p50: 8200, p90: 34000 },
  cost_usd: { total: 1.2345, per_trace: 0.031 },
  tokens: { in: 120000, out: 8000, cache_read: 90000, cache_write: 1000, cache_read_rate: 0.42 },
  tool_calls: 80,
  llm_calls: 120,
  errors: 2,
  guard: { blocked: 3, block_rate: 0.0375 },
  health: HEALTH,
};

/** Chaque page : chargement, erreur et 403 (même message que le garde de routes). */
const PAGES: { name: string; ui: ReactElement; path: string; main: string }[] = [
  { name: 'Exploitation', ui: <AdminOverviewPage />, path: 'overview', main: 'overview?range=7d' },
  { name: 'Audit', ui: <AdminAuditPage />, path: 'audit/queries', main: 'audit/queries' },
  { name: 'Évaluation', ui: <AdminEvalPage />, path: 'eval/runs', main: 'eval/runs' },
  { name: 'Signalements', ui: <AdminFeedbackPage />, path: 'feedback', main: 'feedback' },
  { name: 'KPI', ui: <AdminKpiPage />, path: 'kpis', main: 'kpis' },
  { name: 'Sémantique', ui: <AdminSemanticPage />, path: 'semantic/tables', main: 'semantic/tables' },
  { name: 'Sécurité', ui: <AdminSecurityPage />, path: 'security', main: 'security?range=7d' },
  { name: 'Paramètres', ui: <AdminSettingsPage />, path: 'settings', main: 'settings' },
];

describe.each(PAGES)('$name : états communs', ({ ui, main }) => {
  it('affiche un chargement accessible', async () => {
    server.use(http.get(A(main.split('?')[0]!), () => new Promise(() => {})));
    renderAt(ui);
    expect(await screen.findByText('Chargement…')).toBeInTheDocument();
  });

  it('affiche « Accès réservé » si l’API répond 403', async () => {
    server.use(forbidden(main.split('?')[0]!), forbidden('settings'));
    renderAt(ui);
    expect(await screen.findByRole('heading', { name: 'Accès réservé' })).toBeInTheDocument();
  });

  it('affiche l’erreur avec une action de relance', async () => {
    server.use(failing(main.split('?')[0]!), forbidden('settings'));
    renderAt(ui);
    expect(await screen.findByRole('alert')).toHaveTextContent('Le service ne répond pas.');
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument();
  });
});

describe('Exploitation', () => {
  it('compare les délais aux cibles avec icône et texte', async () => {
    server.use(json('overview', OVERVIEW));
    renderAt(<AdminOverviewPage />);
    expect(await screen.findByText('Sous la cible de 15,0 s')).toBeInTheDocument();
    expect(screen.getByText('Au-dessus de la cible de 30,0 s')).toBeInTheDocument();
    expect(screen.getAllByText('En service')).toHaveLength(3);
  });

  it('dit honnêtement qu’il n’y a pas d’activité', async () => {
    server.use(
      json('overview', {
        ...OVERVIEW,
        questions: 0,
        traces: 0,
        answers: 0,
        latency_ms: { p50: null, p90: null },
        health: { ...HEALTH, agent: 'down' },
      }),
    );
    renderAt(<AdminOverviewPage />);
    expect(await screen.findByRole('heading', { name: 'Aucune activité sur cette période' })).toBeInTheDocument();
    expect(screen.getByText('Hors service')).toBeInTheDocument();
  });

  it('recharge pour la plage choisie', async () => {
    let asked = '';
    server.use(
      http.get(A('overview'), ({ request }) => {
        asked = new URL(request.url).searchParams.get('range') ?? '';
        return HttpResponse.json(OVERVIEW);
      }),
    );
    renderAt(<AdminOverviewPage />);
    await userEvent.click(await screen.findByRole('button', { name: '30 jours' }));
    await waitFor(() => expect(asked).toBe('30d'));
  });
});

const TRACE = {
  trace_id: 'a1b2c3d4e5f60718',
  ts: '2026-10-20T10:00:00Z',
  user_ref: 'u-1',
  question_hash: 'f00dfeedcafe1234abcd',
  question: 'Combien de clients à Dakar ?',
  calls: 3,
  tool_calls: 1,
  llm_calls: 2,
  duration_ms: 5400,
  cost_usd: 0.02,
  blocked: false,
  has_error: false,
  tools: ['llm', 'query_metric'],
};

describe('Journal d’audit', () => {
  it('n’affiche jamais le texte d’une question, seulement un condensat', async () => {
    server.use(json('audit/queries', { total: 1, page: 1, page_size: 25, items: [TRACE] }));
    renderAt(<AdminAuditPage />);
    expect(await screen.findByText('f00dfeedca')).toBeInTheDocument();
    expect(screen.queryByText(/Combien de clients/)).not.toBeInTheDocument();
  });

  it('ouvre le détail dans un tiroir en prévenant que l’ouverture est journalisée', async () => {
    server.use(
      json('audit/queries', { total: 1, page: 1, page_size: 25, items: [TRACE] }),
      json('audit/queries/a1b2c3d4e5f60718', {
        trace_id: TRACE.trace_id,
        user_ref: 'u-1',
        question_hash: TRACE.question_hash,
        total_duration_ms: 5400,
        total_cost_usd: 0.02,
        steps: [
          {
            id: 1, ts: TRACE.ts, step: 1, attempt: 0, tool: 'run_query', status: 'ok', error_class: null,
            sql: 'SELECT count(*) FROM analytics.dim_client LIMIT 1000', row_count: 1, truncated: false,
            duration_ms: 320, model_served: null, tokens_in: null, tokens_out: null, tokens_cache_read: null,
            tokens_cache_write: null, cost_usd: null,
          },
        ],
      }),
    );
    renderAt(<AdminAuditPage />, { path: '/admin/audit/:traceId?', route: '/admin/audit' });
    await userEvent.click(await screen.findByRole('button', { name: /Ouvrir le détail de la trace a1b2c3d4e5f60718/ }));
    const drawer = await screen.findByRole('dialog', { name: 'Détail d’un appel' });
    expect(within(drawer).getByText(/enregistrée dans le journal d’accès/)).toBeInTheDocument();
    expect(await within(drawer).findByText(/SELECT count\(\*\) FROM analytics\.dim_client/)).toBeInTheDocument();
  });

  it('annonce un journal vide', async () => {
    server.use(json('audit/queries', { total: 0, page: 1, page_size: 25, items: [] }));
    renderAt(<AdminAuditPage />);
    expect(await screen.findByRole('heading', { name: 'Aucun appel enregistré' })).toBeInTheDocument();
  });

  it('envoie les filtres choisis', async () => {
    const seen: string[] = [];
    server.use(
      http.get(A('audit/queries'), ({ request }) => {
        seen.push(new URL(request.url).search);
        return HttpResponse.json({ total: 0, page: 1, page_size: 25, items: [] });
      }),
    );
    renderAt(<AdminAuditPage />);
    await userEvent.selectOptions(await screen.findByLabelText('Statut'), 'blocked');
    await userEvent.click(screen.getByRole('button', { name: 'Filtrer' }));
    await waitFor(() => expect(seen.at(-1)).toContain('status=blocked'));
    expect(await screen.findByRole('heading', { name: 'Aucun appel ne correspond' })).toBeInTheDocument();
  });
});

const RUN = {
  id: 7,
  ts: '2026-10-21T09:00:00Z',
  split: 'test',
  prompt_version: 'p3',
  semantic_version: 's1',
  model_id: 'claude-sonnet-5-5',
  git_sha: 'abcdef1234567',
  n: 40,
  n_correct: 30,
  ci_low: 0.59,
  ci_high: 0.86,
  pass3: 0.75,
  pass1: 0.82,
  ablation: 'none',
  report: {
    passes: 3,
    score: {
      pass3: { k: 30, n: 40, rate: 0.75, wilson95: [0.597, 0.858] },
      pass1: { mean: 0.82, bootstrap95: [0.72, 0.9] },
      consistency: { '3/3': 30, '2/3': 4, '1/3': 2, '0/3': 4 },
    },
    categories: {
      kpi: { n: 8, pass3: 7, pass1: 0.95, conclusion_possible: true },
      suivi: { n: 4, pass3: 2, pass1: 0.6, conclusion_possible: false },
    },
    latency_ms: { p50: 9000, p90: 21000, max: 33000, n: 120 },
    cost: { usd_total: 4.5, usd_per_question_pass: 0.0375, usd_per_success: 0.05 },
    failures_by_category: { suivi: { periode: 2 } },
  },
};

describe('Évaluation', () => {
  it('liste les exécutions et propose make eval quand il n’y en a aucune', async () => {
    server.use(json('eval/runs', { items: [] }));
    renderAt(<AdminEvalPage />);
    expect(await screen.findByRole('heading', { name: 'Aucune évaluation enregistrée' })).toBeInTheDocument();
    expect(screen.getByText(/make eval SPLIT=dev/)).toBeInTheDocument();
  });

  it('liste les exécutions avec leur intervalle', async () => {
    server.use(json('eval/runs', { items: [{ ...RUN, report: undefined }] }));
    renderAt(<AdminEvalPage />, { path: '/admin/evaluation', route: '/admin/evaluation' });
    expect(await screen.findByText(/30 sur 40 \(75,0\s%\)/)).toBeInTheDocument();
    expect(screen.getByText('Non démontrée')).toBeInTheDocument();
  });

  it('écrit une phrase honnête quand la borne basse reste sous 80 %', async () => {
    server.use(json('eval/runs/7', { run: RUN, by_category: {}, results: [] }));
    renderAt(<AdminEvalPage />, { path: '/admin/evaluation/:runId', route: '/admin/evaluation/7' });
    expect(await screen.findByText(/La cible de 80 % n’est pas atteinte/)).toBeInTheDocument();
    expect(screen.getByText('Cible non démontrée')).toBeInTheDocument();
    expect(screen.getByText(/de 59,7 % à 85,8 %/)).toBeInTheDocument();
  });

  it('refuse de conclure sous 8 questions et masque les questions du jeu de test', async () => {
    server.use(
      json('eval/runs/7', {
        run: RUN,
        by_category: {},
        results: [{ question_id: 'T01', category: 'suivi', trap: null, passes: 1, got: { reasons: ['periode'] } }],
      }),
    );
    renderAt(<AdminEvalPage />, { path: '/admin/evaluation/:runId', route: '/admin/evaluation/7' });
    expect(await screen.findByText('Pas de conclusion sous 8 questions')).toBeInTheDocument();
    expect(screen.getByText('Échantillon suffisant pour lire le taux')).toBeInTheDocument();
    expect(screen.queryByText('T01')).not.toBeInTheDocument();
    expect(screen.getByText('3 sur 3 passes réussies')).toBeInTheDocument();
  });

  it('calcule la phrase selon la borne basse', () => {
    expect(honestSentence(34, 40).kind).toBe('warn');
    expect(honestSentence(400, 400).kind).toBe('ok');
    expect(honestSentence(10, 40).kind).toBe('bad');
    expect(honestSentence(0, 0).kind).toBe('warn');
    const [lo, hi] = wilson(30, 40);
    expect(lo).toBeCloseTo(0.597, 2);
    expect(hi).toBeCloseTo(0.858, 2);
  });
});

const FB = {
  id: '0b8f0c3e-0000-4000-8000-000000000001',
  ts: '2026-10-22T08:00:00Z',
  category: 'chiffre_faux',
  comment: 'Le total est bizarre',
  consent_question: false,
  question_text: null,
  status: 'nouveau',
  reject_reason: null,
  promoted_to_dev: false,
  handled_at: null,
  trace_id: 'abc123',
};

const ANSWER = {
  kind: 'answer',
  text: 'La valeur transférée en septembre 2026 est de 1,23 milliard FCFA.',
  period: { start: '2026-09-01', end: '2026-09-30', label: 'septembre 2026' },
  scope: 'Tout le Sénégal',
  tables: ['analytics.fact_transaction'],
  chart: { type: 'kpi', y: [] },
  facts: [{ id: 'f1', value: 1230000000, unit: 'xof', label: 'Valeur transférée', result_index: 0, rendered: '1,23 milliard FCFA' }],
  evidence: [
    { kind: 'table', label: 'Transactions' },
    { kind: 'filtre', label: 'Transactions réussies' },
    { kind: 'periode', label: 'septembre 2026' },
    { kind: 'operation', label: 'Somme des montants' },
  ],
  sql: ['SELECT sum(amount_xof) FROM analytics.fact_transaction'],
  certified: true,
};
const detailOf = (over: Record<string, unknown> = {}) => {
  const rest: Partial<typeof FB> = { ...FB };
  delete rest.question_text;
  return { ...rest, question: null, answer: ANSWER, ...over };
};
const detailHandler = (over: Record<string, unknown> = {}, hits?: string[]) =>
  http.get(A(`feedback/${FB.id}`), () => {
    hits?.push(FB.id);
    return HttpResponse.json(detailOf(over) as never);
  });

describe('Signalements', () => {
  it('sans consentement : la question est remplacée par une phrase, la réponse et ses preuves sont lisibles', async () => {
    const hits: string[] = [];
    server.use(json('feedback', { total: 1, page: 1, page_size: 25, items: [FB] }), detailHandler({}, hits));
    renderAt(<AdminFeedbackPage />);
    await userEvent.click(await screen.findByRole('button', { name: /Ouvrir le signalement/ }));
    const drawer = await screen.findByRole('dialog', { name: 'Signalement' });
    expect(within(drawer).getByText('L’ouverture de ce détail est journalisée.')).toBeInTheDocument();
    expect(await within(drawer).findByText('L’utilisateur n’a pas autorisé l’affichage de sa question.')).toBeInTheDocument();
    const answer = await within(drawer).findByRole('article', { name: 'Réponse signalée' });
    expect(within(answer).getByText('1,23 milliard FCFA')).toBeInTheDocument();
    expect(within(answer).getByText('septembre 2026', { selector: 'span' })).toBeInTheDocument();
    expect(within(answer).getByText('Tout le Sénégal')).toBeInTheDocument();
    const proof: [string, string][] = [
      ['Table', 'Transactions'],
      ['Filtre', 'Transactions réussies'],
      ['Période', 'septembre 2026'],
      ['Opération', 'Somme des montants'],
    ];
    for (const [label, value] of proof) {
      const term = within(answer).getByText(label, { selector: 'dt' });
      expect(term.nextElementSibling).toHaveTextContent(value);
    }
    // le SQL est dans un volet replié
    const toggle = within(answer).getByText('Voir le calcul (SQL)');
    expect(toggle.closest('details')).not.toHaveAttribute('open');
    await userEvent.click(toggle);
    expect(toggle.closest('details')).toHaveAttribute('open');
    expect(within(answer).getByText(/SELECT sum\(amount_xof\)/)).toBeInTheDocument();
    expect(within(drawer).getByRole('button', { name: 'Ajouter au jeu de développement' })).toBeDisabled();
    expect(within(drawer).getByText(/jamais dans le jeu de test/)).toBeInTheDocument();
    expect(hits).toHaveLength(1);
  });

  it('avec consentement : affiche la question', async () => {
    server.use(
      json('feedback', { total: 1, page: 1, page_size: 25, items: [{ ...FB, consent_question: true, question_text: 'Valeur transférée en septembre ?' }] }),
      detailHandler({ consent_question: true, question: 'Valeur transférée en septembre ?' }),
    );
    renderAt(<AdminFeedbackPage />);
    await userEvent.click(await screen.findByRole('button', { name: /Ouvrir le signalement/ }));
    const drawer = await screen.findByRole('dialog', { name: 'Signalement' });
    expect(await within(drawer).findByText('Valeur transférée en septembre ?', { selector: 'p' })).toBeInTheDocument();
    expect(within(drawer).queryByText(/n’a pas autorisé/)).not.toBeInTheDocument();
  });

  it('une erreur de chargement du détail laisse les actions disponibles', async () => {
    server.use(
      json('feedback', { total: 1, page: 1, page_size: 25, items: [FB] }),
      http.get(A(`feedback/${FB.id}`), () => HttpResponse.json({ error: { code: 'boom', message: 'Le service ne répond pas.' } }, { status: 400 })),
    );
    renderAt(<AdminFeedbackPage />);
    await userEvent.click(await screen.findByRole('button', { name: /Ouvrir le signalement/ }));
    const drawer = await screen.findByRole('dialog', { name: 'Signalement' });
    expect(await within(drawer).findByText('Le service ne répond pas.')).toBeInTheDocument();
    expect(within(drawer).getByRole('button', { name: 'Marquer comme traité' })).toBeEnabled();
  });

  it('exige un motif pour rejeter, puis l’envoie', async () => {
    const bodies: unknown[] = [];
    server.use(
      json('feedback', { total: 1, page: 1, page_size: 25, items: [FB] }),
      detailHandler(),
      http.patch(A(`feedback/${FB.id}`), async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({ ...FB, status: 'rejete' });
      }),
    );
    renderAt(<AdminFeedbackPage />);
    await userEvent.click(await screen.findByRole('button', { name: /Ouvrir le signalement/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Rejeter' }));
    const dialog = await screen.findByRole('dialog', { name: 'Rejeter ce signalement' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Rejeter' }));
    expect(await within(dialog).findByText(/Indiquez le motif du rejet/)).toBeInTheDocument();
    expect(bodies).toHaveLength(0);
    await userEvent.type(within(dialog).getByLabelText('Motif du rejet'), 'Question hors périmètre');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Rejeter' }));
    await waitFor(() => expect(bodies).toEqual([{ action: 'rejeter', reason: 'Question hors périmètre' }]));
  });

  it('marque un signalement comme traité et l’annonce', async () => {
    server.use(
      json('feedback', { total: 1, page: 1, page_size: 25, items: [FB] }),
      detailHandler(),
      http.patch(A(`feedback/${FB.id}`), () => HttpResponse.json({ ...FB, status: 'traite' })),
    );
    renderAt(<AdminFeedbackPage />);
    await userEvent.click(await screen.findByRole('button', { name: /Ouvrir le signalement/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Marquer comme traité' }));
    expect(await screen.findByText('Signalement marqué comme traité.')).toBeInTheDocument();
  });

  it('affiche un état vide', async () => {
    server.use(json('feedback', { total: 0, page: 1, page_size: 25, items: [] }));
    renderAt(<AdminFeedbackPage />);
    expect(await screen.findByRole('heading', { name: 'Aucun signalement' })).toBeInTheDocument();
  });
});

describe('Catalogue et sémantique', () => {
  it('filtre les indicateurs en local et montre la procédure', async () => {
    server.use(
      json('kpis', {
        semantic_version: 'v9',
        metrics: {
          taux_echec: { label: 'Taux d’échec', description: 'Part des échecs.', unit: 'ratio', sql: 'COUNT(*)' },
          agents_actifs: { label: 'Agents actifs', description: 'Points de service.', unit: 'count', sql: 'COUNT(DISTINCT x)' },
        },
        dimensions: {},
        regions: ['Dakar'],
        limits: { max_metrics: 6, max_group_by: 2, max_rank_limit: 50 },
      }),
      json('settings', { semantic_version: 'v9', config: {}, runtime: {}, change_procedure: { how: '', url: 'docs/PROCEDURE.md' } }),
    );
    renderAt(<AdminKpiPage />);
    expect(await screen.findByText(/ouvrez une demande de modification \(PR Git\)/)).toBeInTheDocument();
    expect(await screen.findByText('docs/PROCEDURE.md')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Chercher un indicateur ou un axe'), 'agents');
    expect(screen.queryByRole('heading', { name: 'Taux d’échec' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Agents actifs' })).toBeInTheDocument();
  });

  it('lit le glossaire', async () => {
    server.use(
      json('semantic/tables', { semantic_version: 'v9', name: 'tables', source: 'semantic/tables.yaml', content: { schema: 'analytics', tables: {} } }),
      json('semantic/glossary', { semantic_version: 'v9', name: 'glossary', source: 'semantic/glossary.yaml', content: { terms: [{ term: 'agent actif', rule: 'Au moins une transaction.' }] } }),
      forbidden('settings'),
    );
    renderAt(<AdminSemanticPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Glossaire' }));
    expect(await screen.findByText('Au moins une transaction.')).toBeInTheDocument();
    expect(screen.getByText(/Demandez à un administrateur/)).toBeInTheDocument();
  });
});

describe('Sécurité et paramètres', () => {
  const SEC = {
    range: '7d',
    guard_blocks: [{ error_class: 'forbidden_table', count: 3 }],
    guard_blocks_by_day: [],
    role_matrix: { admin: ['analyste', 'sécurité'] },
    rights_test: {
      available: true,
      how: 'make rights-test écrit le rapport.',
      report: {
        generated_at: '2026-10-24T19:00:00Z',
        checks: [
          { phase: 'avant', label: 'SELECT analytics.dim_client', ok: true },
          { phase: 'avant', label: 'DROP TABLE refusé', ok: false },
        ],
      },
    },
    recent_audit_access: [],
    sessions: 'Console Keycloak.',
    health: HEALTH,
  };

  it('affiche chaque contrôle avec icône et texte, OK ou KO', async () => {
    server.use(json('security', SEC));
    renderAt(<AdminSecurityPage />);
    expect(await screen.findByText('1 contrôle en échec')).toBeInTheDocument();
    expect(screen.getByText('OK')).toBeInTheDocument();
    expect(screen.getByText('KO')).toBeInTheDocument();
    expect(screen.getByText('forbidden_table')).toBeInTheDocument();
  });

  it('relit le rapport sur demande', async () => {
    let calls = 0;
    server.use(
      json('security', { ...SEC, rights_test: { available: false, report: null, how: 'make rights-test' } }),
      http.post(A('security/rights-test'), () => {
        calls += 1;
        return HttpResponse.json({ available: true, ok: true, failed: 0, how: '', report: { checks: [{ label: 'Lecture seule', ok: true }] } });
      }),
    );
    renderAt(<AdminSecurityPage />);
    expect(await screen.findByText('Aucun rapport')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Relire le rapport' }));
    expect(await screen.findByText('Tous les contrôles réussis')).toBeInTheDocument();
    expect(calls).toBe(1);
  });

  it('montre les paramètres sans secret', async () => {
    server.use(
      json('settings', {
        semantic_version: 'v9',
        config: { quota: { questions_per_user_per_day: 200 } },
        runtime: { llm_model: 'claude-sonnet-5-5', llm_fallbacks: false },
        change_procedure: { how: 'Lecture seule.', url: 'docs/PROC.md' },
      }),
    );
    renderAt(<AdminSettingsPage />);
    expect(await screen.findByText('claude-sonnet-5-5')).toBeInTheDocument();
    expect(screen.getByText('200')).toBeInTheDocument();
    expect(screen.getByText('docs/PROC.md')).toBeInTheDocument();
  });
});
