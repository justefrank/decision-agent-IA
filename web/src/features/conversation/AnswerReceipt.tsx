/**
 * Une réponse est un reçu : chiffre clé souligné de jaune, phrase, graphique choisi par le code, chaîne de
 * preuve en lignes de ticket, mentions, sceau (certifié / ad hoc) et actions. Le SQL n'apparaît que s'il est
 * présent dans le message (le serveur le retire pour le décideur).
 */
import { useId, useState } from 'react';

import { fmtDate } from '@/shared/format';
import { Button, Icon, announce } from '@/shared/ui';

import { caveatSentences, copyText, EVIDENCE_LABEL, type Message } from './copy';
import type { FeedbackInput } from './conversationApi';
import { ChevronGlyph, CopyGlyph } from './glyphs';
import { ReceiptChart } from './ReceiptChart';
import { ReportDialog } from './ReportDialog';

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function useCopied() {
  const [copied, setCopied] = useState(false);
  const copy = async (text: string, what: string) => {
    const ok = await copyToClipboard(text);
    announce(ok ? `${what} copié.` : 'Copie impossible : sélectionnez le texte à la main.');
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  };
  return { copied, copy };
}

function SqlPanel({ sql, tables }: { sql: string[]; tables: string[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const { copied, copy } = useCopied();
  return (
    <div className="cv-sql">
      <button type="button" className="cv-sql-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <ChevronGlyph />
        Voir le calcul
      </button>
      {open ? (
        <div id={id} className="cv-sql-body">
          {sql.map((q, i) => (
            <div key={i} className="cv-sql-block">
              {/* Bloc défilant horizontalement : focalisable pour être lisible au clavier (WCAG 2.1.1). */}
              {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
              <pre className="ui-code" tabIndex={0} aria-label={sql.length > 1 ? `Requête SQL ${i + 1}` : 'Requête SQL'}>
                <code>{q}</code>
              </pre>
            </div>
          ))}
          <div className="cv-sql-foot">
            {tables.length ? (
              <p>
                Tables utilisées : <b>{tables.join(', ')}</b>
              </p>
            ) : (
              <span />
            )}
            <Button variant="secondary" size="sm" onClick={() => void copy(sql.join('\n\n'), 'SQL')}>
              <CopyGlyph />
              {copied ? 'SQL copié' : 'Copier le SQL'}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function AnswerReceipt({
  message,
  onAsk,
  onReport,
  canAsk,
  showFollowUp,
}: {
  message: Message;
  onAsk: (q: string) => void;
  onReport: (f: FeedbackInput) => Promise<void>;
  canAsk: boolean;
  showFollowUp: boolean;
}) {
  const proofId = useId();
  const [reportOpen, setReportOpen] = useState(false);
  const [reported, setReported] = useState(false);
  const { copied, copy } = useCopied();
  const notes = caveatSentences(message.caveats);
  const empty = message.caveats.includes('resultat_vide') || (message.chart?.type !== 'kpi' && message.table !== null && message.table !== undefined && message.table.rows.length === 0);
  const period = message.period ? (message.period.label ?? `${fmtDate(message.period.start)} au ${fmtDate(message.period.end)}`) : null;
  const figure = message.chart?.type === 'kpi' && !empty ? message.facts.find((f) => f.rendered) : undefined;
  const sql = message.sql ?? [];

  return (
    <article className="cv-receipt" aria-label="Réponse">
      <div className="cv-receipt-body">
        {period || message.scope ? (
          <p className="cv-where">
            {period ? <span>{period}</span> : null}
            {message.scope ? <span>{message.scope}</span> : null}
          </p>
        ) : null}

        {empty ? (
          <p className="cv-empty">
            Aucune donnée pour {period ?? 'cette période'}
            {message.scope ? `, ${message.scope}` : ''}.
          </p>
        ) : figure ? (
          <div className="cv-figure-block">
            <p className="cv-figure num">{figure.rendered}</p>
            <p className="cv-figure-label">{figure.label}</p>
          </div>
        ) : null}

        <p className="cv-text">{message.text}</p>

        {!empty ? (
          <div className="cv-chart">
            <ReceiptChart message={message} />
          </div>
        ) : null}

        {notes.length ? (
          <ul className="cv-notes" aria-label="Mentions">
            {notes.map((n) => (
              <li key={n}>
                <Icon name="alert" size={16} />
                <span>{n}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {message.evidence.length ? (
          <section className="cv-proof" aria-labelledby={proofId}>
            <h3 id={proofId}>Origine du calcul</h3>
            <dl>
              {message.evidence.map((e, i) => (
                <div key={i} className="cv-proof-row">
                  <dt>{EVIDENCE_LABEL[e.kind]}</dt>
                  <dd>{e.label}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        <div className="cv-seal-row">
          {message.certified ? (
            <span className="cv-seal" data-kind="certified">
              <Icon name="shield" size={16} />
              Calcul certifié
            </span>
          ) : (
            <span className="cv-seal" data-kind="adhoc">
              <Icon name="flask" size={16} />
              Calcul ad hoc
            </span>
          )}
          <div className="cv-actions">
            <Button variant="ghost" size="sm" onClick={() => void copy(copyText(message), 'Réponse')}>
              <CopyGlyph />
              {copied ? 'Réponse copiée' : 'Copier la réponse'}
            </Button>
            {reported ? (
              <span className="cv-reported" role="status">
                <Icon name="check" size={16} />
                Signalement envoyé
              </span>
            ) : (
              <Button variant="ghost" size="sm" icon="flag" onClick={() => setReportOpen(true)}>
                Signaler la réponse
              </Button>
            )}
          </div>
        </div>

        {sql.length ? <SqlPanel sql={sql} tables={message.tables} /> : null}
      </div>

      {showFollowUp && message.follow_up.length ? (
        <div className="cv-followups" role="group" aria-label="Questions de suivi">
          {message.follow_up.map((q) => (
            <button key={q} type="button" className="cv-chip" disabled={!canAsk} onClick={() => onAsk(q)}>
              {q}
            </button>
          ))}
        </div>
      ) : null}

      <ReportDialog
        open={reportOpen}
        onOpenChange={setReportOpen}
        onSubmit={async (f) => {
          await onReport(f);
          setReported(true);
          announce('Signalement envoyé. Merci.');
        }}
      />
    </article>
  );
}
