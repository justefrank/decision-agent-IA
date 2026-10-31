/**
 * Lecture d'un flux SSE émis par un POST (`fetch` + `ReadableStream`) : `EventSource` ne permet ni POST ni
 * en-tête `Authorization`. Événements de l'API : `step` (StepEvent), `final` (AssistantMessage), `error`.
 */
import { API_BASE, authHeaders, toApiError } from './client';

export interface SseEvent {
  event: string;
  data: string;
}

/** Découpe un texte SSE en événements ; renvoie aussi le reste incomplet. Exporté pour les tests. */
export function parseSse(buffer: string): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = [];
  const normalized = buffer.replace(/\r\n?/g, '\n');
  const blocks = normalized.split('\n\n');
  const rest = blocks.pop() ?? '';
  for (const block of blocks) {
    let event = 'message';
    const data: string[] = [];
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue; // commentaire : maintien de connexion
      const idx = line.indexOf(':');
      const field = idx === -1 ? line : line.slice(0, idx);
      const value = idx === -1 ? '' : line.slice(idx + 1).replace(/^ /, '');
      if (field === 'event') event = value;
      else if (field === 'data') data.push(value);
    }
    if (data.length) events.push({ event, data: data.join('\n') });
  }
  return { events, rest };
}

export async function postSse(
  path: string,
  body: unknown,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = await authHeaders({ 'Content-Type': 'application/json', Accept: 'text/event-stream' });
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw await toApiError(res);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseSse(buffer);
    buffer = rest;
    events.forEach(onEvent);
  }
  const { events } = parseSse(buffer + '\n\n');
  events.forEach(onEvent);
}
