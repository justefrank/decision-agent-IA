/**
 * Types de l'API, dérivés de `schema.d.ts` (généré depuis l'OpenAPI de decision_api et les contrats de
 * decision_core : `npm run api-types`). Ne pas écrire de types de réponse à la main ailleurs.
 */
import type { components } from './schema';

type S = components['schemas'];

export type AssistantMessage = S['AssistantMessage'];
export type StepEvent = S['StepEvent'];
export type DashboardAnalysis = S['DashboardAnalysis'];
export type ResolvedState = S['ResolvedState'];
export type Fact = S['Fact'];
export type EvidenceStep = S['EvidenceStep'];
export type Chart = S['Chart'];
export type TableData = S['TableData'];
export type ColumnInfo = S['ColumnInfo'];
export type PendingClarification = S['PendingClarification'];
export type ConversationOut = S['ConversationOut'];
export type ConversationDetail = S['ConversationDetail'];
export type MessageOut = S['MessageOut'];

export type Role = 'decideur' | 'analyste' | 'admin';

export interface Me {
  sub: string;
  name: string | null;
  email: string | null;
  roles: Role[];
  role: Role;
  sees_sql: boolean;
}

/** Contrat d'erreur uniforme de l'API : `{"error": {"code", "message", "request_id"}}`. */
export interface ApiErrorBody {
  error: { code: string; message: string; request_id?: string };
}
