import { useState } from 'react';

import { fmtInt } from '@/shared/format';
import { EmptyState, Field, PageHead, scrollable, Segmented } from '@/shared/ui';

import {
  useAdmin,
  type Dimension,
  type ExamplesContent,
  type GlossaryContent,
  type KpiCatalog,
  type Metric,
  type SemanticFile,
  type Settings,
  type TablesContent,
} from './adminApi';
import { Ledger, Line, Loaded, Section } from './common';

const UNITS: Record<string, string> = {
  count: 'Nombre',
  xof: 'FCFA',
  ratio: 'Part (en %)',
  pct: 'Pourcentage',
  pp: 'Points de pourcentage',
};

/** Procédure de modification : lecture seule ici, le changement passe par une PR Git relue par une autre personne. */
export function ChangeProcedure({ version }: { version: string }) {
  // La route des paramètres est réservée aux administrateurs : pour un analyste, on retombe sur un texte sans chemin.
  const s = useAdmin<Settings>(['settings'], 'settings');
  const where = s.data?.change_procedure.url;
  return (
    <aside className="adm-procedure" aria-label="Procédure de modification">
      <p>
        <strong>Pour modifier :</strong> ouvrez une demande de modification (PR Git) ; la revue est faite par une autre personne.
        Cette page est en lecture seule.
      </p>
      <p className="adm-note">
        Version de la couche sémantique : <code>{version}</code>.{' '}
        {where ? (
          <>
            Procédure et dépôt : <code>{where}</code>
          </>
        ) : (
          'Demandez à un administrateur l’emplacement du dépôt.'
        )}
      </p>
    </aside>
  );
}

function SearchBox({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div className="adm-search">
      <Field label={label}>
        {(p) => <input className="ui-input" type="search" {...p} value={value} onChange={(e) => onChange(e.target.value)} />}
      </Field>
    </div>
  );
}

const match = (q: string, ...fields: (string | undefined | null)[]) => {
  const n = q.trim().toLowerCase();
  return !n || fields.some((f) => f?.toLowerCase().includes(n));
};

function MetricCard({ id, m }: { id: string; m: Metric }) {
  return (
    <article className="adm-def" aria-labelledby={`m-${id}`}>
      <h3 id={`m-${id}`}>{m.label}</h3>
      <p className="adm-id">
        <code>{id}</code> · {UNITS[m.unit ?? ''] ?? m.unit ?? 'Sans unité'}
      </p>
      <p>{m.description.trim()}</p>
      <Ledger label={`Propriétés de ${m.label}`}>
        <Line label="Additif entre périodes" value={m.additive ? 'Oui' : 'Non'} />
        {m.default_region_kind ? <Line label="Région par défaut" value={m.default_region_kind} /> : null}
        {m.default_period ? <Line label="Période par défaut" value={m.default_period} /> : null}
      </Ledger>
      <pre className="ui-code" {...scrollable(`Définition SQL de ${m.label}`)}>
        {m.sql}
      </pre>
    </article>
  );
}

function KpiBody({ d }: { d: KpiCatalog }) {
  const [q, setQ] = useState('');
  const metrics = Object.entries(d.metrics).filter(([id, m]) => match(q, id, m.label, m.description));
  const dims = Object.entries(d.dimensions).filter(([id, x]) => match(q, id, x.label));
  return (
    <>
      <ChangeProcedure version={d.semantic_version} />
      <SearchBox label="Chercher un indicateur ou un axe" value={q} onChange={setQ} />
      <p className="sr-only" role="status">
        {metrics.length} indicateurs et {dims.length} axes affichés
      </p>
      {metrics.length === 0 && dims.length === 0 ? (
        <EmptyState title="Aucun résultat">Essayez un autre mot, par exemple « agents » ou « frais ».</EmptyState>
      ) : null}
      {metrics.length ? (
        <Section id="indicateurs" title={`Indicateurs certifiés (${metrics.length})`} note="Chaque indicateur a une seule définition, utilisée par l’agent et par le tableau de bord.">
          <div className="adm-defs">
            {metrics.map(([id, m]) => (
              <MetricCard key={id} id={id} m={m} />
            ))}
          </div>
        </Section>
      ) : null}
      {dims.length ? (
        <Section id="axes" title={`Axes d’analyse (${dims.length})`}>
          <div className="ui-table-wrap" {...scrollable('Axes d’analyse disponibles')}>
            <table className="ui-table">
              <caption className="sr-only">Axes d’analyse disponibles</caption>
              <thead>
                <tr>
                  <th scope="col">Axe</th>
                  <th scope="col">Identifiant</th>
                  <th scope="col">Valeurs</th>
                </tr>
              </thead>
              <tbody>
                {dims.map(([id, x]: [string, Dimension]) => (
                  <tr key={id}>
                    <th scope="row">{x.label}</th>
                    <td>
                      <code>{id}</code>
                    </td>
                    <td>{x.values?.join(', ') ?? 'Selon les données'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      ) : null}
      <Section id="limites" title="Limites d’une question">
        <Ledger label="Limites">
          <Line label="Indicateurs par question" value={fmtInt(d.limits.max_metrics)} />
          <Line label="Axes de découpage" value={fmtInt(d.limits.max_group_by)} />
          <Line label="Taille maximale d’un classement" value={fmtInt(d.limits.max_rank_limit)} />
          <Line label="Régions connues" value={fmtInt(d.regions.length)} />
        </Ledger>
      </Section>
    </>
  );
}

export function AdminKpiPage() {
  const q = useAdmin<KpiCatalog>(['kpis'], 'kpis');
  return (
    <div className="adm-page">
      <PageHead title="Catalogue de KPI" description="Les définitions certifiées que l’agent utilise, en lecture seule." />
      <Loaded query={q} rows={6}>
        {(d) => <KpiBody d={d} />}
      </Loaded>
    </div>
  );
}

type Tab = 'tables' | 'glossary' | 'examples';

function TablesView({ c, q }: { c: TablesContent; q: string }) {
  const tables = Object.entries(c.tables).filter(([n, t]) =>
    match(q, n, t.description, t.grain, ...Object.entries(t.columns).flatMap(([k, col]) => [k, col.description])),
  );
  if (!tables.length) return <EmptyState title="Aucun résultat">Aucune table ni colonne ne contient ce mot.</EmptyState>;
  return (
    <div className="adm-defs">
      {tables.map(([name, t]) => (
        <article key={name} className="adm-def" aria-labelledby={`t-${name}`}>
          <h3 id={`t-${name}`}>
            <code>
              {c.schema}.{name}
            </code>
          </h3>
          <p>{t.description}</p>
          {t.grain ? <p className="adm-note">Une ligne par : {t.grain}</p> : null}
          <div className="ui-table-wrap" {...scrollable(`Colonnes de ${name}`)}>
            <table className="ui-table">
              <caption className="sr-only">Colonnes de {name}</caption>
              <thead>
                <tr>
                  <th scope="col">Colonne</th>
                  <th scope="col">Type</th>
                  <th scope="col">Sens</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(t.columns)
                  .filter(([k, col]) => match(q, name, t.description, k, col.description) || !q.trim())
                  .map(([k, col]) => (
                    <tr key={k}>
                      <th scope="row">
                        <code>{k}</code>
                      </th>
                      <td>{col.type}</td>
                      <td>
                        {col.description}
                        {col.values ? ` Valeurs : ${col.values.join(', ')}.` : ''}
                        {col.references ? ` Renvoie à ${col.references}.` : ''}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </article>
      ))}
    </div>
  );
}

function GlossaryView({ c, q }: { c: GlossaryContent; q: string }) {
  const terms = c.terms.filter((t) => match(q, t.term, t.rule));
  if (!terms.length) return <EmptyState title="Aucun résultat">Aucun terme du glossaire ne contient ce mot.</EmptyState>;
  return (
    <dl className="adm-glossary">
      {terms.map((t) => (
        <div key={t.term}>
          <dt>{t.term}</dt>
          <dd>{t.rule.trim()}</dd>
        </div>
      ))}
    </dl>
  );
}

function ExamplesView({ c, q }: { c: ExamplesContent; q: string }) {
  const ex = c.examples.filter((e) => match(q, e.id, e.question, e.piege));
  if (!ex.length) return <EmptyState title="Aucun résultat">Aucun exemple ne contient ce mot.</EmptyState>;
  return (
    <div className="adm-defs">
      {ex.map((e) => (
        <article key={e.id} className="adm-def" aria-labelledby={`e-${e.id}`}>
          <h3 id={`e-${e.id}`}>{e.question}</h3>
          <p className="adm-id">
            <code>{e.id}</code>
          </p>
          {e.piege ? <p>Piège : {e.piege.trim()}</p> : null}
          {e.appel ? (
            <pre className="ui-code" {...scrollable(`Appel attendu pour ${e.id}`)}>
              {e.appel.sql ?? JSON.stringify(e.appel, null, 2)}
            </pre>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function SemanticBody() {
  const [tab, setTab] = useState<Tab>('tables');
  const [q, setQ] = useState('');
  const tables = useAdmin<SemanticFile<TablesContent>>(['sem', 'tables'], 'semantic/tables', { enabled: tab === 'tables' });
  const glossary = useAdmin<SemanticFile<GlossaryContent>>(['sem', 'glossary'], 'semantic/glossary', { enabled: tab === 'glossary' });
  const examples = useAdmin<SemanticFile<ExamplesContent>>(['sem', 'examples'], 'semantic/examples', { enabled: tab === 'examples' });
  const active = tab === 'tables' ? tables : tab === 'glossary' ? glossary : examples;
  return (
    <>
      <ChangeProcedure version={active.data?.semantic_version ?? '…'} />
      <div className="adm-toolbar">
        <Segmented
          label="Fichier"
          value={tab}
          options={[
            { value: 'tables', label: 'Tables' },
            { value: 'glossary', label: 'Glossaire' },
            { value: 'examples', label: 'Exemples' },
          ]}
          onChange={setTab}
        />
        <SearchBox label="Chercher dans ce fichier" value={q} onChange={setQ} />
      </div>
      {active.data ? <p className="adm-note">Source : <code>{active.data.source}</code></p> : null}
      {tab === 'tables' ? <Loaded query={tables}>{(d) => <TablesView c={d.content} q={q} />}</Loaded> : null}
      {tab === 'glossary' ? <Loaded query={glossary}>{(d) => <GlossaryView c={d.content} q={q} />}</Loaded> : null}
      {tab === 'examples' ? <Loaded query={examples}>{(d) => <ExamplesView c={d.content} q={q} />}</Loaded> : null}
    </>
  );
}

export function AdminSemanticPage() {
  return (
    <div className="adm-page">
      <PageHead title="Couche sémantique" description="Les tables, le glossaire et les exemples sur lesquels l’agent s’appuie, en lecture seule." />
      <SemanticBody />
    </div>
  );
}
