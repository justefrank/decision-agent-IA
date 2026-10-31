import { Button, Icon } from '@/shared/ui';

import { EXAMPLE_QUESTIONS, type Message } from './copy';
import type { TurnError } from './useAsk';

export function ClarificationCard({
  message,
  active,
  onPick,
}: {
  message: Message;
  active: boolean;
  onPick: (label: string) => void;
}) {
  const c = message.clarification;
  if (!c) return <p className="cv-text">{message.text}</p>;
  return (
    <section className="cv-reply" data-kind="clarification" aria-label="Précision demandée">
      <p className="cv-reply-title">{c.question}</p>
      <div className="cv-options" role="group" aria-label="Choix possibles">
        {c.options.map((o) => (
          <Button key={o.label} variant="secondary" disabled={!active} onClick={() => onPick(o.label)}>
            {o.label}
          </Button>
        ))}
      </div>
      <p className="ui-help">Vous pouvez aussi répondre avec votre propre message.</p>
    </section>
  );
}

export function RefusalCard({
  message,
  active,
  onAsk,
}: {
  message: Message;
  active: boolean;
  onAsk: (q: string) => void;
}) {
  const suggestions = message.follow_up.length ? message.follow_up : EXAMPLE_QUESTIONS.slice(0, 3);
  return (
    <section className="cv-reply" data-kind="refusal" aria-label="Question non traitée">
      <p className="cv-reply-title">Cette question ne peut pas être traitée</p>
      <p className="cv-text">{message.text}</p>
      <p className="cv-reply-sub">L’outil répond sur les transactions Wave Sénégal : volume, valeur transférée, revenus de frais, clients actifs, agents actifs et taux d’échec, par période, région, type de transaction ou segment. Par exemple :</p>
      <div className="cv-followups" role="group" aria-label="Questions possibles">
        {suggestions.map((q) => (
          <button key={q} type="button" className="cv-chip" disabled={!active} onClick={() => onAsk(q)}>
            {q}
          </button>
        ))}
      </div>
    </section>
  );
}

export function ErrorCard({
  message,
  detail,
  onRetry,
  canRetry,
}: {
  message?: string;
  detail?: TurnError;
  onRetry?: () => void;
  canRetry: boolean;
}) {
  return (
    <section className="cv-reply" data-kind="error" role="alert">
      <p className="cv-reply-title">
        <Icon name="alert" size={18} />
        {detail?.kind === 'cancelled' ? 'Calcul arrêté' : detail?.kind === 'quota' ? 'Limite de questions atteinte' : 'La réponse n’a pas pu être produite'}
      </p>
      {detail?.kind === 'cancelled' ? null : <p className="cv-text">{detail?.message ?? message}</p>}
      {onRetry && detail?.kind !== 'quota' ? (
        <div>
          <Button variant="secondary" icon="refresh" disabled={!canRetry} onClick={onRetry}>
            Réessayer
          </Button>
        </div>
      ) : null}
    </section>
  );
}
