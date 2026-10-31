import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api } from '@/api/client';
import { fmtDateTime, fmtInt } from '@/shared/format';
import { announce, Button, PageHead, Segmented } from '@/shared/ui';

import { useAdmin, type Range, type RightsReport, type RightsTestResult, type Security, type Settings } from './adminApi';
import { Ledger, Line, Loaded, Mark, Section } from './common';

const RANGES = [
  { value: '24h', label: '24 heures' },
  { value: '7d', label: '7 jours' },
  { value: '30d', label: '30 jours' },
  { value: '90d', label: '90 jours' },
] as const;

const ERROR_CLASSES: Record<string, string> = {
  inconnu: 'Motif non précisé',
};
const ROLES: Record<string, string> = { decideur: 'Décideur', analyste: 'Analyste', admin: 'Administrateur' };
const ACTIONS: Record<string, string> = {
  audit_detail: 'Ouverture du détail d’un appel',
  audit_export_csv: 'Export du journal en CSV',
  rights_test_read: 'Lecture du test de droits',
};

function RightsReportView({ report }: { report: RightsReport }) {
  const checks = report.checks ?? [];
  const failed = checks.filter((c) => !c.ok);
  const phases = [...new Set(checks.map((c) => c.phase ?? 'général'))];
  const PHASE: Record<string, string> = { avant: 'Avant la transformation des données', apres_dbt_run: 'Après une transformation (dbt run)' };
  return (
    <>
      <p className="adm-verdict" data-kind={failed.length === 0 ? 'ok' : 'bad'}>
        {failed.length === 0 ? (
          <Mark kind="ok">Tous les contrôles réussis</Mark>
        ) : (
          <Mark kind="bad">
            {failed.length} {failed.length > 1 ? 'contrôles en échec' : 'contrôle en échec'}
          </Mark>
        )}
        <span>
          {checks.length} contrôles{report.generated_at ? `, relevés le ${fmtDateTime(report.generated_at)}` : ''}.
        </span>
      </p>
      {phases.map((ph) => {
        const inPhase = checks.filter((c) => (c.phase ?? 'général') === ph);
        const bad = inPhase.filter((c) => !c.ok);
        const good = inPhase.filter((c) => c.ok);
        return (
          <div key={ph} className="adm-block">
            <h3>{PHASE[ph] ?? ph}</h3>
            {bad.length ? (
              <ul className="adm-checks">
                {bad.map((c) => (
                  <li key={c.label}>
                    <Mark kind="bad">KO</Mark>
                    <span>{c.label}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            <details className="adm-details">
              <summary>
                {good.length} {good.length > 1 ? 'contrôles réussis' : 'contrôle réussi'} sur {inPhase.length}
              </summary>
              <ul className="adm-checks">
                {good.map((c) => (
                  <li key={c.label}>
                    <Mark kind="ok">OK</Mark>
                    <span>{c.label}</span>
                  </li>
                ))}
              </ul>
            </details>
          </div>
        );
      })}
    </>
  );
}

function SecurityBody({ d, range }: { d: Security; range: Range }) {
  const qc = useQueryClient();
  const [latest, setLatest] = useState<RightsTestResult | null>(null);
  const test = useMutation({
    mutationFn: () => api<RightsTestResult>('/admin/security/rights-test', { method: 'POST' }),
    onSuccess: async (r) => {
      setLatest(r);
      announce(r.available ? 'Rapport de droits relu.' : 'Aucun rapport de droits disponible.');
      await qc.invalidateQueries({ queryKey: ['admin', 'security'] });
    },
  });
  const rt = latest ?? d.rights_test;
  const report = latest ? (latest.report ?? null) : d.rights_test.report;
  const maxCalls = Math.max(1, ...d.guard_blocks_by_day.map((x) => x.tool_calls));
  const total = d.guard_blocks.reduce((s, b) => s + b.count, 0);
  return (
    <>
      <Section
        id="droits"
        title="Droits de l’agent sur la base"
        note="L’agent lit les données avec un compte restreint, agent_ro. Ce test vérifie qu’il peut lire les tables d’analyse et rien d’autre."
      >
        <div className="adm-actions">
          <Button variant="secondary" icon="refresh" onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? 'Lecture en cours…' : 'Relire le rapport'}
          </Button>
        </div>
        {test.isError ? (
          <p className="ui-error" role="alert">
            {test.error.message} Relancez la lecture.
          </p>
        ) : null}
        {report ? (
          <RightsReportView report={report} />
        ) : (
          <>
            <p className="adm-verdict" data-kind="warn">
              <Mark kind="warn">Aucun rapport</Mark>
              <span>Le test de droits n’a pas encore été lancé.</span>
            </p>
            <p>
              Lancez <code>make rights-test</code>, puis cliquez sur « Relire le rapport ».
            </p>
          </>
        )}
        <p className="adm-note">{rt.how}</p>
        <p className="adm-note">
          Un contrôle en échec veut dire que le compte de l’agent a trop de droits (écrire, supprimer, créer) : corrigez les droits avant
          toute mise en service. Chaque lecture du rapport est enregistrée dans le journal d’accès.
        </p>
      </Section>

      <Section id="blocages" title="Requêtes bloquées par le garde SQL" note={`Sur ${RANGES.find((r) => r.value === range)?.label ?? range}. Un blocage est normal : le garde fait son travail.`}>
        {d.guard_blocks.length === 0 ? (
          <p>
            <Mark kind="ok">Aucun blocage</Mark> Aucune requête n’a été refusée sur cette période.
          </p>
        ) : (
          <div className="ui-table-wrap">
            <table className="ui-table">
              <caption className="sr-only">Blocages par motif</caption>
              <thead>
                <tr>
                  <th scope="col">Motif</th>
                  <th scope="col" className="is-num">Blocages</th>
                  <th scope="col" className="is-num">Part</th>
                </tr>
              </thead>
              <tbody>
                {d.guard_blocks.map((b) => (
                  <tr key={b.error_class}>
                    <th scope="row">{ERROR_CLASSES[b.error_class] ?? b.error_class}</th>
                    <td className="is-num">{fmtInt(b.count)}</td>
                    <td className="is-num">{total ? `${fmtInt(Math.round((b.count / total) * 100))} %` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {d.guard_blocks_by_day.length > 0 ? (
          <div className="ui-table-wrap">
            <table className="ui-table">
              <caption className="sr-only">Appels d’outils de données et blocages par jour</caption>
              <thead>
                <tr>
                  <th scope="col">Jour</th>
                  <th scope="col" className="is-num">Appels</th>
                  <th scope="col" className="is-num">Bloqués</th>
                  <th scope="col">Répartition</th>
                </tr>
              </thead>
              <tbody>
                {d.guard_blocks_by_day.map((x) => (
                  <tr key={x.day}>
                    <th scope="row">{new Date(x.day).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })}</th>
                    <td className="is-num">{fmtInt(x.tool_calls)}</td>
                    <td className="is-num">{fmtInt(x.blocked)}</td>
                    <td>
                      <span className="adm-mini" aria-hidden="true">
                        <span style={{ width: `${(x.tool_calls / maxCalls) * 100}%` }}>
                          <i style={{ width: x.tool_calls ? `${(x.blocked / x.tool_calls) * 100}%` : 0 }} />
                        </span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Section>

      <Section id="roles" title="Qui voit quoi">
        <Ledger label="Droits par rôle">
          {Object.entries(d.role_matrix).map(([r, items]) => (
            <Line key={r} label={ROLES[r] ?? r} value={items.join(', ')} />
          ))}
        </Ledger>
        <p className="adm-note">{d.sessions}</p>
      </Section>

      <Section id="acces" title="Derniers accès au journal" note="Qui a ouvert un détail ou exporté le journal.">
        {d.recent_audit_access.length === 0 ? (
          <p>Aucun accès enregistré.</p>
        ) : (
          <div className="ui-table-wrap">
            <table className="ui-table">
              <caption className="sr-only">Accès récents au journal d’audit</caption>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Rôle</th>
                  <th scope="col">Action</th>
                  <th scope="col">Trace</th>
                </tr>
              </thead>
              <tbody>
                {d.recent_audit_access.map((a, i) => (
                  <tr key={`${a.ts}-${i}`}>
                    <td>{fmtDateTime(a.ts)}</td>
                    <td>{ROLES[a.actor_role] ?? a.actor_role}</td>
                    <td>{ACTIONS[a.action] ?? a.action}</td>
                    <td>{a.target_trace_id ? <code>{a.target_trace_id.slice(0, 8)}</code> : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </>
  );
}

export function AdminSecurityPage() {
  const [range, setRange] = useState<Range>('7d');
  const q = useAdmin<Security>(['security', range], `security?range=${range}`);
  return (
    <div className="adm-page">
      <PageHead
        title="Sécurité"
        description="Ce que le garde a refusé, et la preuve que l’agent ne peut que lire."
        actions={<Segmented label="Période" value={range} options={RANGES} onChange={setRange} />}
      />
      <Loaded query={q} rows={6}>
        {(d) => <SecurityBody d={d} range={range} />}
      </Loaded>
    </div>
  );
}

const LABELS: Record<string, string> = {
  environment: 'Environnement',
  reference_date: 'Date de référence des données',
  llm_model: 'Modèle',
  llm_effort: 'Effort de raisonnement',
  llm_fallbacks: 'Modèles de repli',
  keycloak_issuer: 'Fournisseur d’identité',
  keycloak_audience: 'Audience du jeton',
  keycloak_client_id: 'Client de l’application web',
  cors_origins: 'Origines autorisées',
};

function show(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'Oui' : 'Non';
  if (Array.isArray(v)) return v.length ? v.map(show).join(', ') : 'Aucune';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

const GROUPS: Record<string, string> = {
  llm: 'Modèle',
  agent: 'Limites de l’agent',
  sql: 'Garde SQL',
  quota: 'Quotas',
  retention: 'Conservation',
};

export function AdminSettingsPage() {
  const q = useAdmin<Settings>(['settings'], 'settings');
  return (
    <div className="adm-page">
      <PageHead title="Paramètres" description="Les réglages en vigueur, en lecture seule. Aucun secret n’est affiché." />
      <Loaded query={q} rows={6}>
        {(d) => (
          <>
            <aside className="adm-procedure" aria-label="Procédure de modification">
              <p>
                <strong>Pour modifier :</strong> ouvrez une demande de modification (PR Git) ; la revue est faite par une autre personne.
              </p>
              <p className="adm-note">
                {d.change_procedure.how}
                {d.change_procedure.url ? (
                  <>
                    {' '}
                    Procédure : <code>{d.change_procedure.url}</code>
                  </>
                ) : null}
              </p>
            </aside>
            <Section id="execution" title="Exécution">
              <Ledger label="Exécution">
                <Line label="Version sémantique" value={<code>{d.semantic_version}</code>} />
                {Object.entries(d.runtime).map(([k, v]) => (
                  <Line key={k} label={LABELS[k] ?? k} value={show(v)} />
                ))}
              </Ledger>
            </Section>
            {Object.entries(d.config)
              .filter(([, v]) => typeof v === 'object' && v !== null && !Array.isArray(v))
              .map(([group, values]) => (
                <Section key={group} id={`cfg-${group}`} title={GROUPS[group] ?? group}>
                  <Ledger label={GROUPS[group] ?? group}>
                    {Object.entries(values as Record<string, unknown>).map(([k, v]) => (
                      <Line key={k} label={k.replaceAll('_', ' ')} value={show(v)} />
                    ))}
                  </Ledger>
                </Section>
              ))}
          </>
        )}
      </Loaded>
    </div>
  );
}
