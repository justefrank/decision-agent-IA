/** Forme de `GET /api/dashboard` (réponse libre côté OpenAPI : décrite ici) et de `POST /api/dashboard/analysis`. */
import type { DashboardAnalysis } from '@/api/types';

export interface PeriodInfo {
  start: string;
  end: string;
  label?: string | null;
}

export interface Tile {
  metric: string;
  label: string;
  unit: string;
  available: boolean;
  value?: number | null;
  previous?: number | null;
  rendered?: string | null;
  rendered_previous?: string | null;
  delta_abs?: number | null;
  rendered_delta_abs?: string | null;
  delta_pct?: number | null;
  rendered_delta_pct?: string | null;
  delta_pp?: number | null;
  rendered_delta_pp?: string | null;
  /** current, compare, ecart, variation, ecart_pp → identifiant de fait */
  fact_ids?: Record<string, string>;
}

export interface DashboardData {
  period: PeriodInfo;
  compare_period: PeriodInfo;
  region: string | null;
  tiles: Tile[];
  errors: string[];
  semantic_version: string;
}

export interface AnalysisResponse {
  id: string;
  reused: boolean;
  generated_at: string;
  data_hash: string;
  analysis: DashboardAnalysis;
}
