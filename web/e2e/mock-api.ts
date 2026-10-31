/**
 * Simulation complète de l'API (`/api/**`) pour les tests de bout en bout : aucune dépendance à l'API réelle.
 * Les réponses de l'agent viennent de `src/features/conversation/fixtures.ts` ; les formes du tableau de bord et du
 * back-office reprennent celles des tests Vitest (`DashboardPage.test.tsx`, `admin.test.tsx`).
 * Le flux SSE passe par `e2e/sse-server.mjs` (Playwright ne sait pas diffuser en continu) : la requête est
 * réécrite pour porter la séquence à émettre.
 */
import type { Page, Route } from '@playwright/test';

import type { AssistantMessage, ConversationOut, Me, Role } from '../src/api/types';
import {
  CONVERSATIONS,
  STEPS,
  barAnswer,
  clarificationMsg,
  decideurVersion,
  detailOf,
  donutAnswer,
  emptyAnswer,
  errorMsg,
  kpiAnswer,
  lineAnswer,
  refusalMsg,
  simplifiedAnswer,
  tableAnswer,
} from '../src/features/conversation/fixtures';
import type { AnalysisResponse, DashboardData, Tile } from '../src/features/dashboard/types';

const NN = ' ';

export const ME: Record<Role, Me> = {
  decideur: { sub: 'e2e-decideur', name: 'Awa Diallo', email: null, roles: ['decideur'], role: 'decideur', sees_sql: false },
  analyste: { sub: 'e2e-analyste', name: 'Moussa Ndiaye', email: null, roles: ['analyste'], role: 'analyste', sees_sql: true },
  admin: { sub: 'e2e-admin', name: 'Fatou Sow', email: null, roles: ['admin'], role: 'admin', sees_sql: true },
};

/** Questions types : chacune mène à un type de réponse. */
export const Q = {
  kpi: 'Quelle est la valeur transférée en septembre ?',
  line: 'Comment évolue le taux d’échec ?',
  bar: 'Quelles régions ont le plus de transactions ?',
  donut: 'Quelle est la répartition des revenus de frais ?',
  table: 'Donne-moi la liste des agents les plus actifs',
  simplified: 'Valeur transférée, version simplifiée',
  empty: 'Combien de clients actifs à Kédougou ?',
  clarification: 'Quel est le volume par région ?',
  refusal: 'Que font les concurrents de Wave ?',
  error: 'Question qui échoue côté agent',
} as const;

/** Conversations « graines » : une par type de réponse, ouvertes directement (/questions/<id>) sans flux SSE. */
export const SEEDED = {
  kpi: ['bbbbbbbb-bbbb-4bbb-8bbb-000000000001', Q.kpi],
  line: ['bbbbbbbb-bbbb-4bbb-8bbb-000000000002', Q.line],
  bar: ['bbbbbbbb-bbbb-4bbb-8bbb-000000000003', Q.bar],
  donut: ['bbbbbbbb-bbbb-4bbb-8bbb-000000000004', Q.donut],
  table: ['bbbbbbbb-bbbb-4bbb-8bbb-000000000005', Q.table],
  simplified: ['bbbbbbbb-bbbb-4bbb-8bbb-000000000006', Q.simplified],
  empty: ['bbbbbbbb-bbbb-4bbb-8bbb-000000000007', Q.empty],
  clarification: ['bbbbbbbb-bbbb-4bbb-8bbb-000000000008', Q.clarification],
  refusal: ['bbbbbbbb-bbbb-4bbb-8bbb-000000000009', Q.refusal],
  error: ['bbbbbbbb-bbbb-4bbb-8bbb-00000000000a', Q.error],
} as const satisfies Record<string, readonly [string, string]>;
export type SeededKind = keyof typeof SEEDED;

export function answerFor(question: string): AssistantMessage {
  if (question === Q.line) return lineAnswer;
  if (question === Q.bar || question === 'Région de l’agent' || question === 'Et par région ?') return barAnswer;
  if (question === Q.donut) return donutAnswer;
  if (question === Q.table) return tableAnswer;
  if (question === Q.simplified) return simplifiedAnswer;
  if (question === Q.empty) return emptyAnswer;
  if (question === Q.clarification) return clarificationMsg;
  if (question === Q.refusal) return refusalMsg;
  if (question === Q.error) return errorMsg;
  return kpiAnswer;
}

const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
const monthLabel = (ym: string) => {
  const [y, m] = ym.split('-').map(Number) as [number, number];
  return `${MONTHS[m - 1]} ${y}`;
};
const prevMonth = (ym: string) => {
  const [y, m] = ym.split('-').map(Number) as [number, number];
  const d = new Date(Date.UTC(y, m - 2, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
};
const monthRange = (ym: string) => {
  const [y, m] = ym.split('-').map(Number) as [number, number];
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return { start: `${ym}-01`, end: `${ym}-${String(last).padStart(2, '0')}`, label: monthLabel(ym) };
};

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

export function dashboardFor(period: string, region: string | null): DashboardData {
  return {
    period: monthRange(period),
    compare_period: monthRange(prevMonth(period)),
    region,
    errors: [],
    semantic_version: 'v1',
    tiles: [
      tile({ metric: 'volume_transactions', label: 'Volume de transactions', rendered: `6${NN}950`, rendered_previous: `6${NN}794`, rendered_delta_abs: '+156', rendered_delta_pct: `+2,3${NN}%`, fact_ids: { current: 'f1', compare: 'f7', variation: 'd2' } }),
      tile({ metric: 'valeur_transferee', label: 'Valeur transférée', unit: 'xof', rendered: `1,23${NN}milliard FCFA`, rendered_previous: `1,18${NN}milliard FCFA`, rendered_delta_abs: `+50${NN}millions FCFA`, rendered_delta_pct: `+4,3${NN}%`, fact_ids: { current: 'f2' } }),
      tile({ metric: 'revenus_frais', label: 'Revenus de frais', unit: 'xof', rendered: `101${NN}millions FCFA`, rendered_previous: `104${NN}millions FCFA`, delta_pct: -2.9, rendered_delta_abs: `−3${NN}millions FCFA`, rendered_delta_pct: `−2,9${NN}%`, fact_ids: { current: 'f3' } }),
      tile({ metric: 'clients_actifs', label: 'Clients actifs', rendered: `1${NN}808`, rendered_previous: `1${NN}839`, rendered_delta_abs: '−31', delta_pct: -1.7, rendered_delta_pct: `−1,7${NN}%`, fact_ids: { current: 'f4' } }),
      tile({ metric: 'agents_actifs', label: 'Agents actifs', rendered: '312', rendered_previous: '312', rendered_delta_abs: '0', delta_pct: 0, rendered_delta_pct: `0${NN}%`, fact_ids: { current: 'f5' } }),
      tile({ metric: 'taux_echec', label: 'Taux d’échec', unit: 'ratio', rendered: `5,9${NN}%`, rendered_previous: `6,4${NN}%`, delta_pct: null, rendered_delta_pct: null, delta_abs: null, delta_pp: -0.45, rendered_delta_pp: `−0,5${NN}pt`, fact_ids: { current: 'f6', ecart_pp: 'd11' } }),
    ],
  };
}

export function analysisFor(period: string, region: string | null): AnalysisResponse {
  return {
    id: 'a1',
    reused: false,
    generated_at: new Date().toISOString(),
    data_hash: 'h',
    analysis: {
      period: monthRange(period),
      region,
      lead: `Le volume de transactions progresse en ${monthLabel(period)}.`,
      findings: [
        { tag: 'Hausse', text: 'Le volume atteint 6 950 transactions.', confidence: 'elevee', sources: ['f1', 'd2'], hypothesis: 'La saison pourrait expliquer cette hausse.' },
        { tag: 'Écart', text: 'Kolda s’écarte de la moyenne.', confidence: 'hypothese', sources: ['f40'], hypothesis: null },
      ],
      follow_up: ['Quelles régions ont le plus fort taux d’échec ?'],
      facts: [{ id: 'f40', value: 0.09, unit: 'ratio', label: 'Taux d’échec — Kolda', result_index: 1, rendered: '9 %' }],
      semantic_version: 'v1',
      model_id: 'm',
      available: true,
    },
  } as AnalysisResponse;
}

const HEALTH = { status: 'ok', db: 'ok', mcp: 'ok', agent: 'ok' };
const OVERVIEW = {
  range: '7d', since: '2026-10-17T00:00:00Z', questions: 42, traces: 40, answers: 40,
  latency_ms: { p50: 8200, p90: 34000 }, cost_usd: { total: 1.2345, per_trace: 0.031 },
  tokens: { in: 120000, out: 8000, cache_read: 90000, cache_write: 1000, cache_read_rate: 0.42 },
  tool_calls: 80, llm_calls: 120, errors: 2, guard: { blocked: 3, block_rate: 0.0375 }, health: HEALTH,
};
const TRACE = {
  trace_id: 'a1b2c3d4e5f60718', ts: '2026-10-20T10:00:00Z', user_ref: 'u-1', question_hash: 'f00dfeedcafe1234abcd',
  calls: 3, tool_calls: 1, llm_calls: 2, duration_ms: 5400, cost_usd: 0.02, blocked: false, has_error: false,
  tools: ['llm', 'query_metric'], semantic_version: 'v1', prompt_version: 'p3', model_served: 'claude-sonnet-5-5',
};
const TRACE_DETAIL = {
  trace_id: TRACE.trace_id, user_ref: 'u-1', question_hash: TRACE.question_hash, total_duration_ms: 5400, total_cost_usd: 0.02,
  steps: [{
    id: 1, ts: TRACE.ts, step: 1, attempt: 0, tool: 'run_query', status: 'ok', error_class: null,
    sql: 'SELECT count(*) FROM analytics.dim_client LIMIT 1000', row_count: 1, truncated: false, duration_ms: 320,
    model_served: null, tokens_in: null, tokens_out: null, tokens_cache_read: null, tokens_cache_write: null, cost_usd: null,
  }],
};
const RUN = {
  id: 7, ts: '2026-10-21T09:00:00Z', split: 'test', prompt_version: 'p3', semantic_version: 's1', model_id: 'claude-sonnet-5-5',
  git_sha: 'abcdef1234567', n: 40, n_correct: 30, ci_low: 0.59, ci_high: 0.86, pass3: 0.75, pass1: 0.82, ablation: 'none',
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
const FEEDBACK = {
  id: '0b8f0c3e-0000-4000-8000-000000000001', ts: '2026-10-22T08:00:00Z', category: 'chiffre_faux', comment: 'Le total est bizarre',
  consent_question: true, question_text: 'Quelle est la valeur transférée en septembre ?', status: 'nouveau', reject_reason: null,
  promoted_to_dev: false, handled_at: null, trace_id: 'abc123',
};
const SETTINGS = {
  semantic_version: 'v9',
  config: { quota: { questions_per_user_per_day: 200 } },
  runtime: { llm_model: 'claude-sonnet-5-5', llm_fallbacks: false },
  change_procedure: { how: 'Lecture seule.', url: 'docs/PROCEDURE.md' },
};
const KPIS = {
  semantic_version: 'v9',
  metrics: {
    taux_echec: { label: 'Taux d’échec', description: 'Part des transactions échouées.', unit: 'ratio', sql: 'COUNT(*) FILTER (WHERE status <> \'succes\')::float / COUNT(*)' },
    agents_actifs: { label: 'Agents actifs', description: 'Points de service ayant transigé.', unit: 'count', sql: 'COUNT(DISTINCT agent_key)' },
  },
  dimensions: { region: { label: 'Région', column: 'region', values: ['Dakar', 'Thiès'] } },
  regions: ['Dakar', 'Thiès'],
  limits: { max_metrics: 6, max_group_by: 2, max_rank_limit: 50 },
};
const SECURITY = {
  range: '7d',
  guard_blocks: [{ error_class: 'forbidden_table', count: 3 }],
  guard_blocks_by_day: [],
  role_matrix: { admin: ['analyste', 'sécurité'], analyste: ['audit'] },
  rights_test: {
    available: true,
    how: 'make rights-test écrit le rapport.',
    report: {
      generated_at: '2026-10-24T19:00:00Z',
      checks: [
        { phase: 'avant', label: 'SELECT analytics.dim_client', ok: true },
        { phase: 'avant', label: 'DROP TABLE refusé', ok: true },
      ],
    },
  },
  recent_audit_access: [{ ts: '2026-10-24T10:00:00Z', actor_role: 'admin', action: 'open_trace', target_trace_id: 'a1b2c3d4e5f60718' }],
  sessions: 'Console Keycloak.',
  health: HEALTH,
};
const TABLES = {
  semantic_version: 'v9', name: 'tables', source: 'semantic/tables.yaml',
  content: {
    schema: 'analytics',
    tables: {
      fact_transaction: {
        grain: 'Une ligne par transaction', description: 'Transactions Wave.',
        columns: { amount_xof: { type: 'bigint', description: 'Montant en FCFA', unit: 'xof' }, status: { type: 'text', values: ['succes', 'echec'] } },
      },
    },
  },
};
const GLOSSARY = { semantic_version: 'v9', name: 'glossary', source: 'semantic/glossary.yaml', content: { terms: [{ term: 'agent actif', rule: 'Au moins une transaction dans le mois.' }] } };
const EXAMPLES = { semantic_version: 'v9', name: 'examples', source: 'semantic/examples.yaml', content: { examples: [{ id: 'e1', question: 'Combien de clients à Dakar ?', reponse: 'Réponse type.' }] } };

export interface MockApi {
  /** Questions posées à l'agent, dans l'ordre. */
  asked: string[];
  /** Signalements reçus. */
  feedbacks: Record<string, unknown>[];
  /** Chaînes de requête de GET /api/dashboard. */
  dashboardQueries: string[];
  /** Corps des POST /api/dashboard/analysis. */
  analysisBodies: Record<string, unknown>[];
  /** Appels /api non simulés (le test échoue s'il y en a). */
  unhandled: string[];
  /** Les appels suivants répondent 401 (session expirée). */
  expire(): void;
}

export async function installMockApi(page: Page, role: Role = 'decideur'): Promise<MockApi> {
  const state = { expired: false };
  const mock: MockApi = {
    asked: [], feedbacks: [], dashboardQueries: [], analysisBodies: [], unhandled: [],
    expire: () => { state.expired = true; },
  };
  const conversations: ConversationOut[] = CONVERSATIONS.map((c) => ({ ...c }));
  const turns = new Map<string, { q: string; a: AssistantMessage }[]>();
  turns.set(CONVERSATIONS[0]!.id, [{ q: 'Quelle est la valeur transférée en septembre ?', a: { ...kpiAnswer, trace_id: 'tr-hist-1' } }]);
  for (const [id, q] of Object.values(SEEDED)) turns.set(id, [{ q, a: { ...answerFor(q), trace_id: `tr-seed-${id.slice(-2)}` } }]);
  let seq = 0;

  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  const err = (route: Route, status: number, code: string, message: string) =>
    json(route, { error: { code, message, request_id: 'e2e' } }, status);
  const forRole = (m: AssistantMessage) => (role === 'decideur' ? decideurVersion(m) : m);

  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.slice('/api'.length);
    const method = req.method();

    if (state.expired) return err(route, 401, 'unauthorized', 'Votre session a expiré. Reconnectez-vous.');

    if (path === '/me') return json(route, ME[role]);

    // Conversations
    if (path === '/conversations' && method === 'GET') return json(route, conversations);
    if (path === '/conversations' && method === 'POST') {
      seq += 1;
      const id = `99999999-9999-4999-8999-${String(seq).padStart(12, '0')}`;
      const c: ConversationOut = { id, title: null, created_at: '2026-10-30T08:00:00Z', updated_at: '2026-10-30T08:00:00Z' };
      conversations.unshift(c);
      turns.set(id, []);
      return json(route, c, 201);
    }
    const msgs = path.match(/^\/conversations\/([^/]+)\/messages$/);
    if (msgs && method === 'POST') {
      const question = (req.postDataJSON() as { question: string }).question;
      mock.asked.push(question);
      seq += 1;
      const answer = { ...forRole(answerFor(question)), trace_id: `tr-e2e-${seq}` };
      const list = turns.get(msgs[1]!) ?? [];
      list.push({ q: question, a: answer });
      turns.set(msgs[1]!, list);
      const c = conversations.find((x) => x.id === msgs[1]);
      if (c && !c.title) c.title = question;
      // Le serveur SSE local diffuse les étapes puis la réponse (voir en-tête).
      return route.continue({
        postData: JSON.stringify({ steps: answer.kind === 'error' ? [] : STEPS, final: answer, stepDelayMs: 350, finalDelayMs: 500 }),
      });
    }
    const conv = path.match(/^\/conversations\/([^/]+)$/);
    if (conv && method === 'GET') {
      const c = conversations.find((x) => x.id === conv[1])
        ?? (turns.has(conv[1]!) ? { id: conv[1]!, title: null, created_at: '2026-10-23T08:00:00Z', updated_at: '2026-10-23T08:01:00Z' } : undefined);
      if (!c) return err(route, 404, 'not_found', 'Conversation introuvable.');
      return json(route, detailOf(c, (turns.get(c.id) ?? []).map((t) => ({ q: t.q, a: forRole(t.a) }))));
    }
    if (conv && method === 'DELETE') {
      const i = conversations.findIndex((x) => x.id === conv[1]);
      if (i >= 0) conversations.splice(i, 1);
      return route.fulfill({ status: 204 });
    }

    if (path === '/feedback' && method === 'POST') {
      const body = req.postDataJSON() as Record<string, unknown>;
      mock.feedbacks.push(body);
      return json(route, { id: 'fb-1', status: 'nouveau', question_attached: Boolean(body.consent_question) }, 201);
    }

    // Tableau de bord
    if (path === '/dashboard' && method === 'GET') {
      mock.dashboardQueries.push(url.search);
      return json(route, dashboardFor(url.searchParams.get('period') ?? '2026-09', url.searchParams.get('region')));
    }
    if (path === '/dashboard/analysis' && method === 'POST') {
      const body = req.postDataJSON() as { period: string; region: string | null };
      mock.analysisBodies.push(body);
      return json(route, analysisFor(body.period, body.region));
    }

    // Back-office
    if (path.startsWith('/admin/')) {
      const a = path.slice('/admin/'.length);
      if (role === 'decideur') return err(route, 403, 'forbidden', 'Rôle insuffisant.');
      if (a === 'overview') return json(route, { ...OVERVIEW, range: url.searchParams.get('range') ?? '7d' });
      if (a === 'audit/queries') return json(route, { total: 1, page: 1, page_size: 25, items: [TRACE] });
      if (a === `audit/queries/${TRACE.trace_id}`) return json(route, TRACE_DETAIL);
      if (a === 'eval/runs') return json(route, { items: [{ ...RUN, report: undefined }] });
      if (a === 'eval/runs/7') return json(route, { run: RUN, by_category: { kpi: { n: 8, pass3: 7 } }, results: [] });
      if (a === 'feedback') return json(route, { total: 1, page: 1, page_size: 25, items: [FEEDBACK] });
      if (a === 'kpis') return json(route, KPIS);
      if (a === 'semantic/tables') return json(route, TABLES);
      if (a === 'semantic/glossary') return json(route, GLOSSARY);
      if (a === 'semantic/examples') return json(route, EXAMPLES);
      if (role !== 'admin' && (a.startsWith('security') || a === 'settings')) {
        return err(route, 403, 'forbidden', 'Rôle insuffisant.');
      }
      if (a === 'security') return json(route, { ...SECURITY, range: url.searchParams.get('range') ?? '7d' });
      if (a === 'settings') return json(route, SETTINGS);
    }

    mock.unhandled.push(`${method} ${path}${url.search}`);
    return err(route, 404, 'not_found', 'Route non simulée.');
  });

  return mock;
}
