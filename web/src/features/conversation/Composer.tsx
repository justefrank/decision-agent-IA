import { useContext, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';

import { fmtInt } from '@/shared/format';
import { Button } from '@/shared/ui';

import { AuthContext } from '@/auth/AuthProvider';

import { DEFAULT_MAX_QUESTION } from './copy';

export function Composer({
  busy,
  onSend,
  onStop,
  prefill = '',
}: {
  prefill?: string;
  busy: boolean;
  onSend: (q: string) => void;
  onStop: () => void;
}) {
  const max = useContext(AuthContext)?.me?.question_max_chars ?? DEFAULT_MAX_QUESTION;
  const [value, setValue] = useState(prefill.slice(0, max));
  const ref = useRef<HTMLTextAreaElement>(null);
  const id = useId();
  // Question reprise d'une autre page (ex. approfondissement) : pré-remplie, jamais envoyée toute seule.
  useEffect(() => {
    const el = ref.current;
    if (el && prefill) {
      el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
      el.focus();
    }
  }, [prefill]);
  const trimmed = value.trim();

  const send = () => {
    if (!trimmed || busy) return;
    onSend(trimmed);
    setValue('');
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  return (
    <form
      className="cv-composer"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <label htmlFor={id} className="sr-only">
        Votre question
      </label>
      <div className="cv-composer-box">
        <textarea
          id={id}
          ref={ref}
          className="cv-input"
          rows={1}
          maxLength={max}
          value={value}
          placeholder="Posez une question sur les transactions"
          aria-describedby={`${id}-hint`}
          onChange={(e) => {
            setValue(e.target.value);
            const el = e.target;
            el.style.height = 'auto';
            el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
          }}
          onKeyDown={onKey}
        />
        <div className="cv-composer-foot">
          <p id={`${id}-hint`} className="cv-count num">
            <span className="cv-keys">Entrée envoie, Maj+Entrée saute une ligne.</span>{' '}
            <span data-near={value.length >= max * 0.9}>
              {fmtInt(value.length)} / {fmtInt(max)}
            </span>
          </p>
          {busy ? (
            <Button variant="secondary" icon="stop" onClick={onStop}>
              Arrêter
            </Button>
          ) : (
            <Button type="submit" icon="send" disabled={!trimmed}>
              Envoyer
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}
