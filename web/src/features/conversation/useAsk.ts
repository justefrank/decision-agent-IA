/**
 * Poser une question : ajoute la question au fil tout de suite, crée la conversation si besoin, lit le flux
 * SSE (étapes puis `final` ou `error`) et tient l'historique à jour. L'état du fil est local au composant
 * (remonté à chaque changement de conversation) ; le serveur reste la source au rechargement.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/api/client";
import { postSse } from "@/api/sse";
import type { AssistantMessage, StepEvent } from "@/api/types";
import { announce } from "@/shared/ui";

import {
  conversationsKey,
  createConversation,
  getConversation,
} from "./conversationApi";

export interface TurnError {
  kind:
    | "quota"
    | "busy"
    | "unavailable"
    | "network"
    | "interrupted"
    | "cancelled"
    | "generic";
  message: string;
}

export interface Turn {
  id: string;
  question: string;
  status: "pending" | "done" | "failed";
  steps: StepEvent[];
  message?: AssistantMessage;
  /** Identifiant du message côté serveur (nécessaire au signalement). */
  messageId?: string;
  traceId?: string | null;
  error?: TurnError;
}

let counter = 0;
const nextId = () => `t${++counter}`;

/** « HH:MM » en heure locale ; l'heure vient de `retry_at`, à défaut de `Retry-After`. */
function quotaMessage(e: ApiError): string {
  const at = e.retryAt
    ? new Date(e.retryAt)
    : e.retryAfterS !== undefined
      ? new Date(Date.now() + e.retryAfterS * 1000)
      : null;
  if (at === null || Number.isNaN(at.getTime()))
    return "Limite de questions atteinte. Vous pourrez poser une nouvelle question demain.";
  const hhmm = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(at);
  return `Limite de questions atteinte. Vous pourrez poser une nouvelle question à ${hhmm} (heure locale).`;
}

export function describeError(e: unknown): TurnError {
  if (e instanceof ApiError) {
    if (e.status === 429 && e.code === "too_many_streams")
      return {
        kind: "busy",
        message: `Une réponse est déjà en cours. ${
          e.retryAfterS !== undefined
            ? `Vous pourrez poser une nouvelle question dans ${e.retryAfterS} ${e.retryAfterS > 1 ? "secondes" : "seconde"}.`
            : "Attendez qu’elle se termine, puis posez votre question."
        }`,
      };
    if (e.status === 429)
      return { kind: "quota", message: quotaMessage(e) };
    if (e.status === 503)
      return {
        kind: "unavailable",
        message:
          "L’agent est momentanément indisponible. Réessayez dans un instant.",
      };
    if (e.status === 0) return { kind: "network", message: e.message };
    if (e.status === 422) return { kind: "generic", message: e.message };
    return {
      kind: "generic",
      message: "La réponse n’a pas pu être produite. Réessayez.",
    };
  }
  return {
    kind: "network",
    message:
      "Connexion au serveur impossible. Vérifiez votre réseau, puis réessayez.",
  };
}

export function useAsk({
  conversationId,
  initial = [],
  onCreated,
}: {
  conversationId: string | undefined;
  initial?: Turn[];
  /** Appelé une fois la conversation créée et le flux terminé : le parent met l'adresse à jour. */
  onCreated?: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [live, setLive] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const idRef = useRef<string | undefined>(conversationId);
  const busyRef = useRef(false);

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const patch = useCallback((id: string, p: Partial<Turn>) => {
    setLive((ts) => ts.map((t) => (t.id === id ? { ...t, ...p } : t)));
  }, []);

  const resolveMessageId = useCallback(async (cid: string, turnId: string) => {
    try {
      const detail = await getConversation(cid);
      setLive((ts) =>
        ts.map((t) => {
          if (t.id !== turnId || !t.traceId) return t;
          const m = detail.messages.find(
            (x) => x.role === "assistant" && x.trace_id === t.traceId,
          );
          return m ? { ...t, messageId: m.id } : t;
        }),
      );
    } catch {
      /* le signalement retentera au moment de l'envoi */
    }
  }, []);

  const ask = useCallback(
    async (raw: string, replace?: string) => {
      const question = raw.trim();
      if (!question || busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      const turn: Turn = {
        id: nextId(),
        question,
        status: "pending",
        steps: [],
      };
      if (replace) setHidden((h) => [...h, replace]);
      setLive((ts) => [...ts.filter((t) => t.id !== replace), turn]);
      const controller = new AbortController();
      abortRef.current = controller;
      let createdHere: string | undefined;
      let finished = false;
      try {
        if (!idRef.current) {
          const c = await createConversation();
          idRef.current = c.id;
          createdHere = c.id;
          void qc.invalidateQueries({ queryKey: conversationsKey });
        }
        const cid = idRef.current;
        announce("Question envoyée.");
        const aborted = new Promise<never>((_, reject) =>
          controller.signal.addEventListener("abort", () =>
            reject(new DOMException("Arrêté", "AbortError")),
          ),
        );
        await Promise.race([
          aborted,
          postSse(
            `/conversations/${cid}/messages`,
            { question },
            (ev) => {
              let data: unknown;
              try {
                data = JSON.parse(ev.data);
              } catch {
                return;
              }
              if (ev.event === "step") {
                const step = data as StepEvent;
                setLive((ts) =>
                  ts.map((t) =>
                    t.id === turn.id ? { ...t, steps: [...t.steps, step] } : t,
                  ),
                );
                announce(step.label);
              } else if (ev.event === "final") {
                finished = true;
                const message = data as AssistantMessage;
                patch(turn.id, {
                  status: "done",
                  message,
                  traceId: message.trace_id,
                  steps: [],
                });
                announce("Réponse prête.");
              } else if (ev.event === "error") {
                finished = true;
                const err = data as { message?: string };
                patch(turn.id, {
                  status: "failed",
                  steps: [],
                  error: {
                    kind: "generic",
                    message:
                      err.message ?? "La réponse n’a pas pu être produite.",
                  },
                });
                announce("La réponse n’a pas pu être produite.");
              }
            },
            controller.signal,
          ),
        ]);
        if (!finished) {
          patch(turn.id, {
            status: "failed",
            steps: [],
            error: {
              kind: "interrupted",
              message:
                "La connexion a été coupée avant la fin de la réponse. Réessayez.",
            },
          });
          announce("La connexion a été coupée avant la fin de la réponse.");
        }
      } catch (e) {
        if (controller.signal.aborted || (e as Error).name === "AbortError") {
          patch(turn.id, {
            status: "failed",
            steps: [],
            error: { kind: "cancelled", message: "Calcul arrêté." },
          });
          announce("Calcul arrêté.");
        } else {
          const error = describeError(e);
          patch(turn.id, { status: "failed", steps: [], error });
          announce(error.message);
        }
      } finally {
        busyRef.current = false;
        setBusy(false);
        abortRef.current = null;
        void qc.invalidateQueries({ queryKey: conversationsKey });
        if (createdHere) onCreated?.(createdHere);
      }
      // Le signalement a besoin de l'identifiant serveur du message : on le retrouve par `trace_id`.
      if (finished && idRef.current)
        void resolveMessageId(idRef.current, turn.id);
    },
    [qc, patch, onCreated, resolveMessageId],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const lookupMessageId = useCallback(
    async (turn: Turn): Promise<string | null> => {
      if (turn.messageId) return turn.messageId;
      const cid = idRef.current;
      if (!cid || !turn.traceId) return null;
      const detail = await getConversation(cid);
      return (
        detail.messages.find(
          (x) => x.role === "assistant" && x.trace_id === turn.traceId,
        )?.id ?? null
      );
    },
    [],
  );

  // Les tours du serveur dont la réponse vient d'être posée ici sont remplacés par la version locale.
  const liveTraces = new Set(live.map((t) => t.traceId).filter(Boolean));
  const turns = [
    ...initial.filter(
      (t) =>
        !hidden.includes(t.id) && (!t.traceId || !liveTraces.has(t.traceId)),
    ),
    ...live,
  ];
  return { turns, busy, ask, stop, lookupMessageId };
}

/** Fil reconstruit depuis `GET /conversations/{id}` : une question suivie de sa réponse (ou sans réponse). */
export function turnsFromDetail(
  messages: {
    id: string;
    role: string;
    content: string;
    message?: AssistantMessage | null;
    trace_id?: string | null;
  }[],
): Turn[] {
  const out: Turn[] = [];
  for (const m of messages) {
    if (m.role === "user") {
      out.push({
        id: m.id,
        question: m.content,
        status: "failed",
        steps: [],
        error: {
          kind: "interrupted",
          message:
            "Cette question est restée sans réponse. Posez-la à nouveau.",
        },
      });
    } else if (m.role === "assistant") {
      const last = out[out.length - 1];
      if (!last || last.message) continue;
      last.status = m.message ? "done" : "failed";
      last.error = m.message
        ? undefined
        : {
            kind: "generic",
            message: m.content || "La réponse n’a pas pu être produite.",
          };
      last.message = m.message ?? undefined;
      last.messageId = m.id;
      last.traceId = m.trace_id ?? m.message?.trace_id ?? null;
    }
  }
  return out;
}
