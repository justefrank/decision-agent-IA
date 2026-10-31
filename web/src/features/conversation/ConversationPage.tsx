import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';

import { Button, Drawer, EmptyState, ErrorState, PageHead, Skeleton } from '@/shared/ui';

import { AnswerReceipt } from './AnswerReceipt';
import { Composer } from './Composer';
import { conversationKey, getConversation, postFeedback, type FeedbackInput } from './conversationApi';
import { EXAMPLE_QUESTIONS, normalize } from './copy';
import { History } from './History';
import { ClarificationCard, ErrorCard, RefusalCard } from './Replies';
import { StepsList } from './StepsList';
import { turnsFromDetail, useAsk, type Turn } from './useAsk';

import './conversation.css';

function Welcome({ onAsk }: { onAsk: (q: string) => void }) {
  return (
    <section className="cv-welcome" aria-labelledby="cv-welcome-t">
      <h2 id="cv-welcome-t">Posez votre question, le chiffre arrive avec sa preuve</h2>
      <p>
        Interrogez les transactions Wave Sénégal en français. Chaque chiffre est calculé sur les données, jamais deviné,
        et vous voyez d’où il vient.
      </p>
      <h3>Pour commencer</h3>
      <ul className="cv-examples">
        {EXAMPLE_QUESTIONS.map((q) => (
          <li key={q}>
            <button type="button" onClick={() => onAsk(q)}>
              {q}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TurnView({
  turn,
  isLast,
  busy,
  onAsk,
  onRetry,
  onReport,
}: {
  turn: Turn;
  isLast: boolean;
  busy: boolean;
  onAsk: (q: string) => void;
  onRetry: (t: Turn) => void;
  onReport: (t: Turn, f: FeedbackInput) => Promise<void>;
}) {
  const m = turn.message ? normalize(turn.message) : undefined;
  const active = isLast && !busy;
  return (
    <section className="cv-turn" aria-labelledby={`q-${turn.id}`} data-turn={turn.id}>
      <h2 id={`q-${turn.id}`} className="cv-q">
        {turn.question}
      </h2>
      {turn.status === 'pending' ? (
        <StepsList steps={turn.steps} />
      ) : turn.status === 'failed' || !m ? (
        <ErrorCard detail={turn.error} onRetry={() => onRetry(turn)} canRetry={!busy} />
      ) : m.kind === 'clarification' ? (
        <ClarificationCard message={m} active={active} onPick={onAsk} />
      ) : m.kind === 'refusal' ? (
        <RefusalCard message={m} active={active} onAsk={onAsk} />
      ) : m.kind === 'error' ? (
        <ErrorCard message={m.text} onRetry={() => onRetry(turn)} canRetry={!busy} />
      ) : (
        <AnswerReceipt message={m} onAsk={onAsk} canAsk={active} showFollowUp={isLast} onReport={(f) => onReport(turn, f)} />
      )}
    </section>
  );
}

function ConversationView({
  paramId,
  adoptedId,
  onCreated,
  onNew,
  prefill,
}: {
  prefill: string;
  paramId: string | undefined;
  adoptedId: string | undefined;
  onCreated: (id: string) => void;
  onNew: () => void;
}) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const conversationId = paramId ?? adoptedId;
  const detail = useQuery({
    queryKey: conversationKey(paramId ?? ''),
    queryFn: () => getConversation(paramId!),
    enabled: Boolean(paramId),
    refetchOnWindowFocus: false,
    staleTime: 0,
    gcTime: 0,
  });
  const initial = detail.data ? turnsFromDetail(detail.data.messages) : [];
  const { turns, busy, ask, stop, lookupMessageId } = useAsk({ conversationId, initial, onCreated });

  const lastRef = useRef<string | null>(null);
  const lastId = turns[turns.length - 1]?.id ?? null;
  useEffect(() => {
    if (lastId && lastId !== lastRef.current && turns.length > initial.length) {
      document
        .querySelector(`[data-turn="${lastId}"]`)
        ?.scrollIntoView?.({ block: 'start', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    }
    lastRef.current = lastId;
  }, [lastId, turns.length, initial.length]);

  const onAsk = useCallback((q: string) => void ask(q), [ask]);
  const onRetry = useCallback((t: Turn) => void ask(t.question, t.id), [ask]);
  const onReport = useCallback(
    async (t: Turn, f: FeedbackInput) => {
      const id = await lookupMessageId(t);
      if (!id) throw new Error('Cette réponse est introuvable côté serveur. Rechargez la page, puis réessayez.');
      await postFeedback(id, f);
    },
    [lookupMessageId],
  );

  const loading = Boolean(paramId) && detail.isPending;

  return (
    <div className="cv">
      <div className="cv-main">
        <PageHead
          title="Questions"
          actions={
            <>
              <Button variant="secondary" icon="plus" onClick={onNew}>
                Nouvelle conversation
              </Button>
              <span className="cv-hist-btn">
                <Button variant="secondary" icon="history" onClick={() => setHistoryOpen(true)}>
                  Historique
                </Button>
              </span>
            </>
          }
        />
        <div className="cv-thread">
          {loading ? (
            <div className="cv-loading" aria-busy="true">
              <Skeleton height={28} width="60%" />
              <Skeleton height={180} />
            </div>
          ) : detail.isError ? (
            <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />
          ) : turns.length === 0 ? (
            paramId ? (
              <EmptyState title="Conversation vide">Posez une première question ci-dessous.</EmptyState>
            ) : (
              <Welcome onAsk={onAsk} />
            )
          ) : (
            turns.map((t, i) => (
              <TurnView key={t.id} turn={t} isLast={i === turns.length - 1} busy={busy} onAsk={onAsk} onRetry={onRetry} onReport={onReport} />
            ))
          )}
        </div>
        <Composer prefill={prefill} busy={busy} onSend={onAsk} onStop={stop} />
      </div>
      <aside className="cv-history">
        <History activeId={conversationId} onDeletedActive={onNew} />
      </aside>
      <Drawer open={historyOpen} onOpenChange={setHistoryOpen} title="Historique des conversations">
        <History activeId={conversationId} onDeletedActive={onNew} onNavigate={() => setHistoryOpen(false)} />
      </Drawer>
    </div>
  );
}

/**
 * Le fil est remonté à chaque changement de conversation. Quand la conversation vient d'être créée ici,
 * l'adresse est mise à jour sans naviguer : la réponse reste à l'écran et un rechargement la retrouve.
 */
export function ConversationPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as { prefill?: unknown } | null;
  const prefill = typeof state?.prefill === 'string' ? state.prefill : '';
  const [adoptedId, setAdoptedId] = useState<string>();
  const [epoch, setEpoch] = useState(0);
  const [seen, setSeen] = useState(conversationId);
  if (seen !== conversationId) {
    setSeen(conversationId);
    setAdoptedId(undefined);
  }
  return (
    <ConversationView
      key={`${conversationId ?? 'new'}-${epoch}`}
      paramId={conversationId}
      prefill={prefill}
      adoptedId={adoptedId}
      onCreated={(id) => {
        setAdoptedId(id);
        window.history.replaceState(window.history.state, '', `/questions/${id}`);
      }}
      onNew={() => {
        setAdoptedId(undefined);
        setEpoch((e) => e + 1);
        if (conversationId) navigate('/questions');
        else window.history.replaceState(window.history.state, '', '/questions');
      }}
    />
  );
}
