/**
 * Client HTTP : jeton en en-tête (jamais en query string ni en cookie), erreurs uniformes en `ApiError`.
 * Le jeton est fourni par l'authentification (mémoire seulement), via `setTokenProvider`.
 */
import type { ApiErrorBody } from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;

  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

type TokenProvider = () => Promise<string | null>;
let tokenProvider: TokenProvider = async () => null;
const unauthorizedListeners = new Set<() => void>();

export function setTokenProvider(provider: TokenProvider): void {
  tokenProvider = provider;
}

/** Appelé quand l'API répond 401 : l'authentification affiche « session expirée ». */
export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

export const API_BASE = '/api';

export async function authHeaders(extra?: HeadersInit): Promise<Headers> {
  const headers = new Headers(extra);
  const token = await tokenProvider();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  return headers;
}

export async function toApiError(res: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> = {};
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    /* corps vide ou non JSON */
  }
  const err = body.error;
  if (res.status === 401) unauthorizedListeners.forEach((l) => l());
  return new ApiError(
    res.status,
    err?.code ?? 'error',
    err?.message ?? defaultMessage(res.status),
    err?.request_id,
  );
}

function defaultMessage(status: number): string {
  if (status === 401) return 'Votre session a expiré. Reconnectez-vous.';
  if (status === 403) return "Vous n'avez pas accès à cette page.";
  if (status === 404) return 'Élément introuvable.';
  if (status === 429) return 'Limite de questions atteinte pour aujourd’hui.';
  if (status >= 500) return 'Le service est momentanément indisponible. Réessayez dans un instant.';
  return 'La requête a échoué.';
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const h = await authHeaders(headers);
  if (json !== undefined) h.set('Content-Type', 'application/json');
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: h,
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new ApiError(0, 'network', 'Connexion au serveur impossible. Vérifiez votre réseau.');
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  const type = res.headers.get('Content-Type') ?? '';
  return (type.includes('application/json') ? await res.json() : await res.text()) as T;
}
