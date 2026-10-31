/** Contrats du back-office (l'API renvoie des dict libres : les formes sont décrites ici, une seule fois). */
import { keepPreviousData, useQuery, type UseQueryResult } from '@tanstack/react-query';

import { api, authHeaders, API_BASE, toApiError } from '@/api/client';
import type { AssistantMessage } from '@/api/types';

export type Range = '24h' | '7d' | '30d' | '90d';

export interface Health {
  status: string;
  db?: string;
  mcp?: string;
  agent?: string;
  semantic_version?: string;
}

export interface Overview {
  range: Range;
  since: string;
  questions: number;
  traces: number;
  answers: number;
  latency_ms: { p50: number | null; p90: number | null };
  cost_usd: { total: number; per_trace: number | null };
  tokens: { in: number; out: number; cache_read: number; cache_write: number; cache_read_rate: number | null };
  tool_calls: number;
  llm_calls: number;
  errors: number;
  guard: { blocked: number; block_rate: number | null };
  health: Health;
}

export interface TraceSummary {
  trace_id: string;
  ts: string;
  user_ref: string | null;
  question_hash: string | null;
  calls: number;
  tool_calls: number;
  llm_calls: number;
  duration_ms: number;
  cost_usd: number | null;
  blocked: boolean;
  has_error: boolean;
  tools: string[];
  semantic_version: string | null;
  prompt_version: string | null;
  model_served: string | null;
}
export interface AuditPageData {
  total: number;
  page: number;
  page_size: number;
  items: TraceSummary[];
}

export interface TraceStep {
  id: number;
  ts: string;
  step: number;
  attempt: number;
  tool: string;
  status: string;
  error_class: string | null;
  sql: string | null;
  row_count: number | null;
  truncated: boolean | null;
  duration_ms: number;
  model_served: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  tokens_cache_read: number | null;
  tokens_cache_write: number | null;
  cost_usd: number | null;
}
export interface TraceDetail {
  trace_id: string;
  user_ref: string | null;
  question_hash: string | null;
  steps: TraceStep[];
  total_duration_ms: number;
  total_cost_usd: number;
}

export interface EvalRunRow {
  id: number;
  ts: string;
  split: 'dev' | 'test' | string;
  prompt_version: string | null;
  semantic_version: string | null;
  model_id: string | null;
  git_sha: string | null;
  n: number;
  n_correct: number;
  ci_low: number | null;
  ci_high: number | null;
  pass3: number | null;
  pass1: number | null;
  ablation: string | null;
  report?: EvalReport | null;
}
export interface CategoryCount {
  n: number;
  pass3: number;
  pass1?: number;
  conclusion_possible?: boolean;
}
export interface EvalReport {
  run_id?: string;
  milestone?: string | null;
  ablation?: string;
  ablation_label?: string;
  passes?: number;
  score?: {
    pass3: { k: number; n: number; rate: number; wilson95: [number, number] };
    pass1: { mean: number; bootstrap95: [number, number] };
    honest_sentence?: string;
    consistency?: Record<string, number>;
  };
  categories?: Record<string, CategoryCount>;
  latency_ms?: { p50: number | null; p90: number | null; max: number | null; n: number; note?: string };
  cost?: {
    usd_total: number;
    usd_per_question_pass: number | null;
    usd_per_success: number | null;
    tokens?: Record<string, number>;
  };
  failures_by_category?: Record<string, Record<string, number>>;
  intent?: { false_refusals: number; expected_answers: number };
  trace?: { data_scale?: number | string | null; small_scale_override?: boolean };
  degenerate_references?: string[];
  ablation_comparison?: {
    base_run?: string;
    pass3?: { n: number; delta: number; p_value?: number; descriptive?: boolean; p?: number };
    note?: string;
  };
}
export interface EvalResultRow {
  question_id: string;
  category: string | null;
  trap: string | null;
  passes: number;
  got: { reasons?: string[]; kinds?: string[] } | null;
}
export interface EvalDetail {
  run: EvalRunRow;
  by_category: Record<string, { n: number; pass3: number }>;
  results: EvalResultRow[];
}

export type FeedbackStatus = 'nouveau' | 'traite' | 'rejete';
export interface FeedbackItem {
  id: string;
  ts: string;
  category: string;
  comment: string | null;
  consent_question: boolean;
  question_text: string | null;
  status: FeedbackStatus;
  reject_reason: string | null;
  promoted_to_dev: boolean;
  handled_at: string | null;
  trace_id: string | null;
}
/** `GET /admin/feedback/{id}` : la réponse signalée avec sa chaîne de preuve ; la question seulement avec consentement. */
export interface FeedbackDetail extends Omit<FeedbackItem, 'question_text'> {
  question: string | null;
  answer: AssistantMessage | null;
}
export interface FeedbackPage {
  total: number;
  page: number;
  page_size: number;
  items: FeedbackItem[];
}

export interface Metric {
  label: string;
  description: string;
  unit: string | null;
  sql: string;
  additive?: boolean;
  default_region_kind?: string | null;
  default_period?: string | null;
}
export interface Dimension {
  label: string;
  column?: string;
  values?: string[];
  where?: string;
}
export interface KpiCatalog {
  semantic_version: string;
  metrics: Record<string, Metric>;
  dimensions: Record<string, Dimension>;
  grains?: Record<string, string> | null;
  regions: string[];
  limits: Record<string, number>;
}

export interface SemanticFile<T> {
  semantic_version: string;
  name: string;
  content: T;
  source: string;
}
export interface Column {
  type: string;
  description?: string;
  key?: string;
  references?: string;
  values?: string[];
  unit?: string;
}
export interface TablesContent {
  schema: string;
  tables: Record<string, { grain?: string; description?: string; columns: Record<string, Column> }>;
}
export interface GlossaryContent {
  terms: { term: string; rule: string }[];
  field_policy?: unknown;
}
export interface ExamplesContent {
  examples: {
    id: string;
    question: string;
    piege?: string;
    appel?: { outil?: string; arguments?: unknown; sql?: string };
    reponse?: string;
  }[];
}

export interface RightsCheck {
  phase?: string;
  label: string;
  ok: boolean;
}
export interface RightsReport {
  generated_at?: string;
  role?: string;
  ok?: boolean;
  failed?: number;
  checks?: RightsCheck[];
}
export interface Security {
  range: Range;
  guard_blocks: { error_class: string; count: number }[];
  guard_blocks_by_day: { day: string; blocked: number; tool_calls: number }[];
  role_matrix: Record<string, string[]>;
  rights_test: { available: boolean; report: RightsReport | null; how: string };
  recent_audit_access: { ts: string; actor_role: string; action: string; target_trace_id: string | null }[];
  sessions: string;
  health: Health;
}
export interface RightsTestResult {
  available: boolean;
  ok?: boolean;
  failed?: number;
  report?: RightsReport;
  how: string;
}

export interface Settings {
  semantic_version: string;
  config: Record<string, unknown>;
  runtime: Record<string, unknown>;
  change_procedure: { how: string; url: string | null };
}

export function useAdmin<T>(key: unknown[], path: string, { enabled = true, keep = false } = {}): UseQueryResult<T> {
  return useQuery<T>({
    queryKey: ['admin', ...key],
    queryFn: () => api<T>(`/admin/${path}`),
    enabled,
    placeholderData: keep ? keepPreviousData : undefined,
    retry: (count, err) => {
      const status = (err as { status?: number }).status ?? 0;
      return status === 0 || status >= 500 ? count < 1 : false;
    },
    staleTime: 15_000,
  });
}

/** Télécharge un fichier protégé : `fetch` avec jeton, puis `Blob` (le jeton ne passe jamais dans l'URL). */
export async function downloadAuthenticated(path: string, filename: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { headers: await authHeaders() });
  if (!res.ok) throw await toApiError(res);
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}
