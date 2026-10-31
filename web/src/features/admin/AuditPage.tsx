import { useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router';

import { api } from '@/api/client';
import { fmtDateTime, fmtInt, fmtMs } from '@/shared/format';
import { announce, Button, Drawer, EmptyState, Field, Icon, PageHead } from '@/shared/ui';

import {
  downloadAuthenticated,
  useAdmin,
  type AuditPageData,
  type TraceDetail,
  type TraceStep,
  type TraceSummary,
} from './adminApi';
import { Ledger, Line, Loaded, Mark, Pager, isForbidden, shortId, usd } from './common';
import { AccessDenied } from '@/features/auth/AuthPages';

const PAGE_SIZE = 25;
const TOOLS = [
  { value: '', label: 'Tous les outils' },
  { value: 'llm', label: 'Appel au modèle (llm)' },
  { value: 'query_metric', label: 'Indicateur certifié (query_metric)' },
  { value: 'run_query', label: 'Requête SQL (run_query)' },
  { value: 'describe_schema', label: 'Lecture du schéma (describe_schema)' },
];

interface Filters {
  tool: string;
  status: string;
  from: string;
  to: string;
  trace: string;
}
const NO_FILTER: Filters = { tool: '', status: '', from: '', to: '', trace: '' };

function qs(f: Filters, extra: Record<string, string | number> = {}): string {
  const p = new URLSearchParams();
  if (f.tool) p.set('tool', f.tool);
  if (f.status) p.set('status', f.status);
  if (f.from) p.set('from', `${f.from}T00:00:00Z`);
  if (f.to) {
    const d = new Date(`${f.to}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + 1); // la date de fin est incluse
    p.set('to', d.toISOString());
  }
  if (f.trace.trim()) p.set('trace_id', f.trace.trim());
  for (const [k, v] of Object.entries(extra)) p.set(k, String(v));
  return p.toString();
}

function traceStatus(t: TraceSummary) {
  if (t.blocked) return <Mark kind="bad">Bloqué</Mark>;
  if (t.has_error) return <Mark kind="warn">Erreur</Mark>;
  return <Mark kind="ok">Réussi</Mark>;
}

function stepStatus(s: string) {
  if (s === 'ok') return <Mark kind="ok">Réussi</Mark>;
  if (s === 'blocked') return <Mark kind="bad">Bloqué</Mark>;
  return <Mark kind="warn">Erreur</Mark>;
}

function Step({ s }: { s: TraceStep }) {
  const tokens = [s.tokens_in, s.tokens_out, s.tokens_cache_read].some((v) => v)
    ? `${fmtInt(s.tokens_in)} en entrée · ${fmtInt(s.tokens_out)} en sortie · ${fmtInt(s.tokens_cache_read)} lus du cache`
    : null;
  return (
    <li className="adm-step">
      <div className="adm-step-head">
        <strong>
          Étape {s.step}
          {s.attempt > 0 ? `, essai ${s.attempt + 1}` : ''} : {s.tool}
        </strong>
        {stepStatus(s.status)}
      </div>
      <Ledger label={`Étape ${s.step}`}>
        <Line label="Durée" value={fmtMs(s.duration_ms)} />
        {s.error_class ? <Line label="Motif" value={s.error_class} /> : null}
        {s.row_count !== null ? (
          <Line label="Lignes" value={`${fmtInt(s.row_count)}${s.truncated ? ' (tronqué)' : ''}`} />
        ) : null}
        {tokens ? <Line label="Jetons" value={tokens} /> : null}
        {s.cost_usd !== null ? <Line label="Coût" value={usd(s.cost_usd)} /> : null}
      </Ledger>
      {s.sql ? (
        <>
          <p className="adm-note">SQL exécuté, après réécriture par le garde</p>
          <pre className="ui-code">
            {s.sql}
          </pre>
        </>
      ) : null}
    </li>
  );
}

function DetailBody({ traceId }: { traceId: string }) {
  const q = useQuery<TraceDetail>({
    queryKey: ['admin', 'audit-detail', traceId],
    queryFn: () => api<TraceDetail>(`/admin/audit/queries/${encodeURIComponent(traceId)}`),
    retry: false,
    staleTime: Infinity,
  });
  return (
    <>
      <p className="adm-warn">
        <Icon name="alert" size={16} />
        <span>L’ouverture de ce détail est enregistrée dans le journal d’accès, avec votre identité et l’heure.</span>
      </p>
      <Loaded query={q} rows={5}>
        {(d) => (
          <>
            <Ledger label="Résumé de l’appel">
              <Line label="Trace" value={<code>{d.trace_id}</code>} />
              <Line label="Utilisateur" value={d.user_ref ?? '—'} />
              <Line label="Condensat de la question" value={<code>{shortId(d.question_hash, 16)}</code>} />
              <Line label="Durée totale" value={fmtMs(d.total_duration_ms)} />
              <Line label="Coût total" value={usd(d.total_cost_usd)} />
            </Ledger>
            <ol className="adm-steps" aria-label="Étapes">
              {d.steps.map((s) => (
                <Step key={s.id} s={s} />
              ))}
            </ol>
          </>
        )}
      </Loaded>
    </>
  );
}

export function AdminAuditPage() {
  const { traceId } = useParams();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<Filters>(NO_FILTER);
  const [applied, setApplied] = useState<Filters>(NO_FILTER);
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const q = useAdmin<AuditPageData>(
    ['audit', applied, page],
    `audit/queries?${qs(applied, { page, page_size: PAGE_SIZE })}`,
    { keep: true },
  );

  function submit(e: FormEvent) {
    e.preventDefault();
    setApplied(draft);
    setPage(1);
  }
  function reset() {
    setDraft(NO_FILTER);
    setApplied(NO_FILTER);
    setPage(1);
  }
  async function exportCsv() {
    setExporting(true);
    setExportError(null);
    try {
      await downloadAuthenticated(`/admin/audit/queries/export.csv?${qs(applied)}`, 'journal-audit.csv');
      announce('Export téléchargé. Cet export est enregistré dans le journal d’accès.');
    } catch (e) {
      setExportError(e instanceof Error ? e.message : 'L’export a échoué.');
    } finally {
      setExporting(false);
    }
  }

  const filtered = JSON.stringify(applied) !== JSON.stringify(NO_FILTER);

  if (q.isError && isForbidden(q.error)) return <AccessDenied />;

  return (
    <div className="adm-page">
      <PageHead
        title="Journal d’audit"
        description="Chaque appel de l’agent, sans le texte des questions : seul un condensat permet de les rapprocher."
        actions={
          <Button variant="secondary" icon="download" onClick={() => void exportCsv()} disabled={exporting}>
            {exporting ? 'Export en cours…' : 'Exporter en CSV'}
          </Button>
        }
      />
      <p className="adm-warn">
        <Icon name="alert" size={16} />
        <span>Ouvrir un détail ou exporter le journal est enregistré dans le journal d’accès (qui, quand, quoi).</span>
      </p>
      {exportError ? (
        <p className="ui-error" role="alert">
          {exportError} Relancez l’export.
        </p>
      ) : null}

      <form className="adm-filters" onSubmit={submit} aria-label="Filtres du journal">
        <Field label="Outil">
          {(p) => (
            <select className="ui-select" {...p} value={draft.tool} onChange={(e) => setDraft({ ...draft, tool: e.target.value })}>
              {TOOLS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Statut">
          {(p) => (
            <select className="ui-select" {...p} value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
              <option value="">Tous les statuts</option>
              <option value="ok">Réussi</option>
              <option value="error">Erreur</option>
              <option value="blocked">Bloqué</option>
            </select>
          )}
        </Field>
        <Field label="Du">
          {(p) => <input className="ui-input" type="date" {...p} value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />}
        </Field>
        <Field label="Au">
          {(p) => <input className="ui-input" type="date" {...p} value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />}
        </Field>
        <Field label="Trace">
          {(p) => (
            <input
              className="ui-input"
              type="text"
              {...p}
              maxLength={64}
              value={draft.trace}
              onChange={(e) => setDraft({ ...draft, trace: e.target.value })}
            />
          )}
        </Field>
        <div className="adm-filter-actions">
          <Button type="submit">Filtrer</Button>
          {filtered || JSON.stringify(draft) !== JSON.stringify(NO_FILTER) ? (
            <Button variant="ghost" onClick={reset}>
              Effacer les filtres
            </Button>
          ) : null}
        </div>
      </form>

      <Loaded query={q} rows={8}>
        {(d) =>
          d.items.length === 0 ? (
            <EmptyState title={filtered ? 'Aucun appel ne correspond' : 'Aucun appel enregistré'}>
              {filtered
                ? 'Élargissez la période ou effacez un filtre.'
                : 'Le journal se remplit dès que l’agent répond à une question.'}
            </EmptyState>
          ) : (
            <>
              <div className="ui-table-wrap">
                <table className="ui-table">
                  <caption className="sr-only">Appels de l’agent, du plus récent au plus ancien</caption>
                  <thead>
                    <tr>
                      <th scope="col">Date</th>
                      <th scope="col">Trace</th>
                      <th scope="col">Condensat de la question</th>
                      <th scope="col">Outils</th>
                      <th scope="col" className="is-num">Durée</th>
                      <th scope="col" className="is-num">Coût</th>
                      <th scope="col">Statut</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.items.map((t) => (
                      <tr key={t.trace_id}>
                        <td>{fmtDateTime(t.ts)}</td>
                        <td>
                          <button
                            type="button"
                            className="adm-link"
                            onClick={() => navigate(`/admin/audit/${encodeURIComponent(t.trace_id)}`)}
                            aria-label={`Ouvrir le détail de la trace ${t.trace_id}`}
                          >
                            <code>{shortId(t.trace_id)}</code>
                          </button>
                        </td>
                        <td>
                          <code title="Condensat : le texte de la question n’est jamais affiché">{shortId(t.question_hash, 10)}</code>
                        </td>
                        <td>{t.tools.join(', ') || '—'}</td>
                        <td className="is-num">{fmtMs(t.duration_ms)}</td>
                        <td className="is-num">{usd(t.cost_usd)}</td>
                        <td>{traceStatus(t)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} noun={d.total > 1 ? 'appels' : 'appel'} />
            </>
          )
        }
      </Loaded>

      <Drawer
        open={Boolean(traceId)}
        onOpenChange={(o) => {
          if (!o) navigate('/admin/audit');
        }}
        title="Détail d’un appel"
        description="Étapes, durées, jetons et coût."
      >
        {traceId ? <DetailBody traceId={traceId} /> : null}
      </Drawer>
    </div>
  );
}
