import type { StepEvent } from '@/api/types';
import { Icon } from '@/shared/ui';

/** Étapes annoncées par le serveur (libellés validés). L'annonce vocale se fait ailleurs, une à la fois. */
export function StepsList({ steps }: { steps: StepEvent[] }) {
  return (
    <div className="cv-steps" data-busy="true">
      <ol aria-label="Étapes du calcul">
        {steps.length === 0 ? (
          <li data-state="current">
            <span className="cv-step-mark" aria-hidden="true" />
            La question est envoyée
          </li>
        ) : (
          steps.map((s, i) => {
            const current = i === steps.length - 1;
            return (
              <li key={s.step} data-state={current ? 'current' : 'done'}>
                {current ? <span className="cv-step-mark" aria-hidden="true" /> : <Icon name="check" size={14} />}
                <span>{s.label}</span>
                {current ? <span className="sr-only"> (en cours)</span> : null}
              </li>
            );
          })
        )}
      </ol>
    </div>
  );
}
