/**
 * La réponse signalée, vue de l'analyste : un reçu simplifié (chiffre ou texte, période, périmètre,
 * chaîne de preuve) et le SQL dans un volet repliable. Pas d'actions (copier, signaler, suites) : on relit.
 */
import { useId } from 'react';

import type { AssistantMessage } from '@/api/types';
import { caveatSentences, EVIDENCE_LABEL, normalize } from '@/features/conversation/copy';
import { fmtDate } from '@/shared/format';
import { Icon } from '@/shared/ui';

export function ReportedAnswer({ answer }: { answer: AssistantMessage }) {
  const m = normalize(answer);
  const proofId = useId();
  const sqlId = useId();
  const period = m.period ? (m.period.label ?? `${fmtDate(m.period.start)} au ${fmtDate(m.period.end)}`) : null;
  const figure = m.chart?.type === 'kpi' ? m.facts.find((f) => f.rendered) : undefined;
  const notes = caveatSentences(m.caveats);
  const sql = m.sql ?? [];
  return (
    <article className="adm-answer" aria-label="Réponse signalée">
      {period || m.scope ? (
        <p className="adm-answer-where">
          {period ? <span>{period}</span> : null}
          {m.scope ? <span>{m.scope}</span> : null}
        </p>
      ) : null}
      {figure ? (
        <p className="adm-answer-figure num">
          {figure.rendered} <span className="adm-answer-figure-label">{figure.label}</span>
        </p>
      ) : null}
      <p>{m.text}</p>
      {notes.length ? (
        <ul className="adm-answer-notes" aria-label="Mentions">
          {notes.map((n) => (
            <li key={n}>
              <Icon name="alert" size={16} />
              <span>{n}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {m.evidence.length ? (
        <section aria-labelledby={proofId}>
          <h4 id={proofId}>Chaîne de preuve</h4>
          <dl className="adm-answer-proof">
            {m.evidence.map((e, i) => (
              <div key={i}>
                <dt>{EVIDENCE_LABEL[e.kind]}</dt>
                <dd>{e.label}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : (
        <p className="adm-note">Cette réponse ne porte aucune chaîne de preuve.</p>
      )}
      {sql.length ? (
        <details className="adm-answer-sql">
          <summary>Voir le calcul (SQL)</summary>
          <div id={sqlId}>
            {sql.map((q, i) => (
              // Bloc défilant : focalisable pour se lire au clavier (WCAG 2.1.1).
              // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
              <pre key={i} className="ui-code" tabIndex={0} aria-label={sql.length > 1 ? `Requête SQL ${i + 1}` : 'Requête SQL'}>
                <code>{q}</code>
              </pre>
            ))}
          </div>
        </details>
      ) : null}
    </article>
  );
}
