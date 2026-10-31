/** Réponses réalistes (chiffres plausibles pour Wave Sénégal) : tests Vitest et captures Playwright. */
import type { AssistantMessage, ConversationDetail, ConversationOut, StepEvent } from '@/api/types';

const NULL_STATE: AssistantMessage['resolved_state'] = {
  metrics: null,
  period: null,
  compare_to: null,
  region_kind: null,
  scope: null,
  group_by: null,
  certified: true,
  pending_clarification: null,
};

/** Message complet : les champs que le serveur renvoie toujours (à `null` ou vides) sont renseignés. */
function mk(p: Partial<AssistantMessage> & Pick<AssistantMessage, 'text'>): AssistantMessage {
  return {
    kind: 'answer',
    period: { start: '2026-09-01', end: '2026-09-30', label: 'Septembre 2026' },
    scope: 'National',
    table: null,
    truncated: false,
    chart: null,
    tables: ['fact_transaction', 'dim_date'],
    sql: null,
    evidence: [],
    facts: [],
    caveats: [],
    certified: true,
    simplified: false,
    clarification: null,
    follow_up: [],
    resolved_state: NULL_STATE,
    trace_id: 'tr-1',
    ...p,
  };
}

export const SQL_TEXT = `SELECT SUM(t.amount_xof) AS valeur_transferee
FROM fact_transaction t
JOIN dim_date d ON d.date_key = t.date_key
WHERE d.date >= DATE '2026-09-01' AND d.date < DATE '2026-10-01'
  AND t.status = 'succes';`;

export const kpiAnswer: AssistantMessage = mk({
  kind: 'answer',
  text: 'La valeur transférée en septembre 2026 est de 1,23 milliard FCFA, en hausse de 4,3 % par rapport à août.',
  facts: [
    { id: 'f1', value: 1234567890, unit: 'xof', label: 'Valeur transférée', result_index: 0, rendered: '1,23 milliard FCFA' },
    { id: 'd1', value: 4.3, unit: 'pct', label: 'Variation sur un mois', result_index: null, rendered: '+4,3 %' },
  ],
  chart: { type: 'kpi', x: null, y: ['valeur_transferee'], series: null },
  table: { columns: [{ name: 'valeur_transferee', type: 'bigint', role: 'measure', unit: 'xof', label: 'Valeur transférée', free_text: false }], rows: [[1234567890]] },
  evidence: [
    { kind: 'table', label: 'Transactions réussies' },
    { kind: 'filtre', label: 'Statut : réussie' },
    { kind: 'periode', label: 'Du 1er au 30 septembre 2026' },
    { kind: 'operation', label: 'Somme des montants' },
  ],
  follow_up: ['Et par région ?', 'Comment évolue cette valeur depuis trois mois ?'],
  sql: [SQL_TEXT],
});

export const lineAnswer: AssistantMessage = mk({
  text: 'Le taux d’échec reste entre 1,9 % et 2,6 % sur les trois derniers mois, avec un pic en juillet.',
  caveats: ['defaut_periode_applique'],
  chart: { type: 'line', x: 'mois', y: ['taux_echec', 'taux_echec_prec'], series: null },
  table: {
    columns: [
      { name: 'mois', type: 'date', role: 'time', unit: 'date', label: 'Mois', free_text: false },
      { name: 'taux_echec', type: 'double', role: 'measure', unit: 'ratio', label: 'Taux d’échec', free_text: false },
      { name: 'taux_echec_prec', type: 'double', role: 'measure', unit: 'ratio', label: 'Taux d’échec, période précédente', free_text: false },
    ],
    rows: [
      ['2026-04-01', 0.021, 0.024],
      ['2026-05-01', 0.019, 0.022],
      ['2026-06-01', 0.022, 0.021],
      ['2026-07-01', 0.026, 0.023],
      ['2026-08-01', 0.023, 0.02],
      ['2026-09-01', 0.0205, 0.022],
    ],
  },
  evidence: [
    { kind: 'table', label: 'Transactions' },
    { kind: 'periode', label: 'Avril à septembre 2026, par mois' },
    { kind: 'operation', label: 'Part des transactions échouées' },
  ],
  follow_up: ['Quelles régions ont le plus d’échecs ?'],
  sql: [SQL_TEXT],
});

export const barAnswer: AssistantMessage = mk({
  text: 'Dakar arrive en tête avec 412 300 transactions en septembre 2026, devant Thiès et Touba.',
  chart: { type: 'bar', x: 'region', y: ['volume'], series: null },
  table: {
    columns: [
      { name: 'region', type: 'text', role: 'dimension', unit: 'text', label: 'Région', free_text: false },
      { name: 'volume', type: 'bigint', role: 'measure', unit: 'count', label: 'Volume de transactions', free_text: false },
    ],
    rows: [
      ['Dakar', 412300],
      ['Thiès', 188450],
      ['Touba (Diourbel)', 161200],
      ['Saint-Louis', 97320],
      ['Kaolack', 88110],
    ],
  },
  evidence: [
    { kind: 'table', label: 'Transactions réussies' },
    { kind: 'filtre', label: 'Région de l’agent' },
    { kind: 'operation', label: 'Nombre de transactions, cinq premières régions' },
  ],
  follow_up: ['Et le mois précédent ?'],
  sql: [SQL_TEXT],
});

export const donutAnswer: AssistantMessage = mk({
  text: 'Les retraits représentent près de la moitié des revenus de frais de septembre 2026.',
  chart: { type: 'donut', x: 'type', y: ['revenus'], series: null },
  table: {
    columns: [
      { name: 'type', type: 'text', role: 'dimension', unit: 'text', label: 'Type de transaction', free_text: false },
      { name: 'revenus', type: 'bigint', role: 'measure', unit: 'xof', label: 'Revenus de frais', free_text: false },
    ],
    rows: [
      ['Retrait', 48200000],
      ['Transfert', 31800000],
      ['Paiement marchand', 12400000],
      ['Facture', 6100000],
      ['Recharge', 2900000],
    ],
  },
  evidence: [
    { kind: 'table', label: 'Frais de transaction' },
    { kind: 'operation', label: 'Somme des frais par type' },
  ],
  sql: [SQL_TEXT],
});

export const tableAnswer: AssistantMessage = mk({
  text: 'Voici les 100 premières lignes ; le résultat complet est plus long.',
  truncated: true,
  caveats: ['resultat_tronque', 'calcul_ad_hoc'],
  certified: false,
  chart: { type: 'table', x: null, y: [], series: null },
  table: {
    columns: [
      { name: 'agent', type: 'text', role: 'dimension', unit: 'text', label: 'Agent', free_text: false },
      { name: 'region', type: 'text', role: 'dimension', unit: 'text', label: 'Région', free_text: false },
      { name: 'volume', type: 'bigint', role: 'measure', unit: 'count', label: 'Transactions', free_text: false },
      { name: 'valeur', type: 'bigint', role: 'measure', unit: 'xof', label: 'Valeur transférée', free_text: false },
    ],
    rows: [
      ['Agent 0412', 'Dakar', 3120, 48100000],
      ['Agent 0188', 'Thiès', 2874, 39800000],
      ['Agent 0931', 'Touba (Diourbel)', 2511, 36250000],
      ['Agent 0077', 'Saint-Louis', 1904, 21400000],
      ['Agent 0560', 'Kaolack', 1650, 19900000],
    ],
  },
  evidence: [
    { kind: 'table', label: 'Transactions, agents' },
    { kind: 'operation', label: 'Calcul ad hoc (SQL généré, non certifié)' },
  ],
  sql: [SQL_TEXT],
});

export const simplifiedAnswer: AssistantMessage = {
  ...kpiAnswer,
  text: 'Valeur transférée, Septembre 2026, National : 1,23 milliard FCFA. (Réponse simplifiée.)',
  simplified: true,
  caveats: ['reponse_simplifiee'],
  follow_up: [],
};

export const emptyAnswer: AssistantMessage = mk({
  text: 'Aucun client actif ne correspond à cette demande.',
  scope: 'Kédougou',
  caveats: ['resultat_vide'],
  chart: { type: 'kpi', x: null, y: [], series: null },
  table: { columns: [{ name: 'clients', type: 'bigint', role: 'measure', unit: 'count', label: 'Clients actifs', free_text: false }], rows: [] },
  evidence: [{ kind: 'table', label: 'Clients' }, { kind: 'periode', label: 'Septembre 2026' }],
});

export const clarificationMsg: AssistantMessage = mk({
  kind: 'clarification',
  text: 'Que voulez-vous dire par « région » ?',
  period: null,
  scope: null,
  certified: false,
  clarification: {
    original_question: 'Quel est le volume par région ?',
    missing: ['region_kind'],
    question: 'Que voulez-vous dire par « région » ?',
    options: [
      { label: 'Région de l’agent', patch: { region_kind: 'region_agent' } },
      { label: 'Région du client', patch: { region_kind: 'region_client' } },
    ],
  },
});

export const refusalMsg: AssistantMessage = mk({
  kind: 'refusal',
  text: 'Les données ne contiennent pas d’informations sur les concurrents de Wave.',
  period: null,
  scope: null,
  certified: false,
  caveats: ['refus_hors_perimetre'],
});

export const errorMsg: AssistantMessage = mk({
  kind: 'error',
  text: 'La réponse n’a pas pu être produite.',
  period: null,
  scope: null,
  certified: false,
});

export const decideurVersion = (m: AssistantMessage): AssistantMessage => ({ ...m, sql: null });

export const STEPS: StepEvent[] = [
  { step: 1, kind: 'intent', label: 'Analyse de la question', tool: null },
  { step: 2, kind: 'tool', label: 'Lecture des indicateurs', tool: 'query_metric' },
  { step: 3, kind: 'validation', label: 'Vérification des chiffres', tool: null },
];

export const CONVERSATIONS: ConversationOut[] = [
  { id: '11111111-1111-4111-8111-111111111111', title: 'Valeur transférée en septembre', created_at: '2026-10-20T08:00:00Z', updated_at: '2026-10-23T09:30:00Z' },
  { id: '22222222-2222-4222-8222-222222222222', title: 'Taux d’échec par région', created_at: '2026-10-18T08:00:00Z', updated_at: '2026-10-19T16:05:00Z' },
  { id: '33333333-3333-4333-8333-333333333333', title: null, created_at: '2026-10-10T08:00:00Z', updated_at: '2026-10-10T08:10:00Z' },
];

export function detailOf(c: ConversationOut, turns: { q: string; a: AssistantMessage }[]): ConversationDetail {
  return {
    ...c,
    messages: turns.flatMap((t, i) => [
      { id: `${c.id.slice(0, 8)}-u${i}`, role: 'user', content: t.q, message: null, trace_id: null, created_at: c.created_at },
      { id: `${c.id.slice(0, 8)}-a${i}`, role: 'assistant', content: t.a.text, message: t.a, trace_id: t.a.trace_id ?? null, created_at: c.updated_at },
    ]),
  } as ConversationDetail;
}
