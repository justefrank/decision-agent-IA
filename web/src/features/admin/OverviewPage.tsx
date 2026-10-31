import { useState } from 'react';

import { fmtInt, fmtMs, fmtRatio } from '@/shared/format';
import { EmptyState, PageHead, Segmented } from '@/shared/ui';

import { useAdmin, type Health, type Overview, type Range } from './adminApi';
import { Ledger, Line, Loaded, Mark, Section, usd } from './common';

const RANGES = [
  { value: '24h', label: '24 heures' },
  { value: '7d', label: '7 jours' },
  { value: '30d', label: '30 jours' },
  { value: '90d', label: '90 jours' },
] as const;

/** Cibles O2 (SRS) : médiane sous 15 s, p90 sous 30 s. */
export const TARGET_P50_MS = 15_000;
export const TARGET_P90_MS = 30_000;

function LatencyBar({ label, value, target }: { label: string; value: number | null; target: number }) {
  const scale = target * 1.5;
  const within = value !== null && value < target;
  const w = value === null ? 0 : Math.min(100, (value / scale) * 100);
  return (
    <li className="adm-lat">
      <div className="adm-lat-head">
        <span>{label}</span>
        <strong className="num">{value === null ? 'Pas de mesure' : fmtMs(value)}</strong>
        {value === null ? (
          <Mark kind="warn">Non mesurée</Mark>
        ) : within ? (
          <Mark kind="ok">Sous la cible de {fmtMs(target)}</Mark>
        ) : (
          <Mark kind="bad">Au-dessus de la cible de {fmtMs(target)}</Mark>
        )}
      </div>
      <div className="adm-bar" role="img" aria-label={`${label} : ${value === null ? 'pas de mesure' : fmtMs(value)}, cible ${fmtMs(target)}`}>
        <span className="adm-bar-fill" data-over={value !== null && !within} style={{ width: `${w}%` }} />
        <span className="adm-bar-target" style={{ left: `${(target / scale) * 100}%` }} />
      </div>
    </li>
  );
}

const COMPONENTS: { key: keyof Health; label: string }[] = [
  { key: 'db', label: 'Base de données' },
  { key: 'mcp', label: 'Outils de données' },
  { key: 'agent', label: 'Agent (modèle)' },
];

function HealthLines({ health }: { health: Health }) {
  return (
    <Ledger label="Santé des composants">
      {COMPONENTS.map((c) => {
        const v = health[c.key];
        return (
          <Line
            key={c.key}
            label={c.label}
            value={v === 'ok' ? <Mark kind="ok">En service</Mark> : <Mark kind="bad">{v ? 'Hors service' : 'Inconnu'}</Mark>}
          />
        );
      })}
    </Ledger>
  );
}

function Body({ d }: { d: Overview }) {
  const empty = d.questions === 0 && d.traces === 0;
  return (
    <>
      {empty ? (
        <EmptyState title="Aucune activité sur cette période">
          Aucune question n’a été posée depuis le {new Date(d.since).toLocaleDateString('fr-FR')}. Les délais, le coût et les
          blocages apparaîtront dès la première question.
        </EmptyState>
      ) : (
        <>
          <Section
            id="delais"
            title="Délais de réponse"
            note={`Sur ${fmtInt(d.answers)} réponses. Cibles O2 : la moitié des réponses en moins de 15 s, 9 sur 10 en moins de 30 s.`}
          >
            <ul className="adm-lats">
              <LatencyBar label="Médiane (p50)" value={d.latency_ms.p50} target={TARGET_P50_MS} />
              <LatencyBar label="9 réponses sur 10 (p90)" value={d.latency_ms.p90} target={TARGET_P90_MS} />
            </ul>
          </Section>
          <div className="adm-cols">
            <Section id="activite" title="Activité">
              <Ledger label="Activité">
                <Line label="Questions posées" value={fmtInt(d.questions)} />
                <Line label="Réponses données" value={fmtInt(d.answers)} />
                <Line label="Appels d’outils de données" value={fmtInt(d.tool_calls)} />
                <Line label="Appels au modèle" value={fmtInt(d.llm_calls)} />
                <Line
                  label="Erreurs"
                  value={
                    d.errors === 0 ? (
                      <Mark kind="ok">Aucune</Mark>
                    ) : (
                      <Mark kind="warn">{fmtInt(d.errors)}</Mark>
                    )
                  }
                />
              </Ledger>
            </Section>
            <Section id="cout" title="Coût et jetons">
              <Ledger label="Coût et jetons">
                <Line label="Coût total" value={usd(d.cost_usd.total)} />
                <Line label="Coût par question" value={usd(d.cost_usd.per_trace)} />
                <Line label="Jetons en entrée" value={fmtInt(d.tokens.in)} />
                <Line label="Jetons en sortie" value={fmtInt(d.tokens.out)} />
                <Line
                  label="Part lue dans le cache"
                  hint="Plus elle est haute, moins la réponse coûte."
                  value={d.tokens.cache_read_rate === null ? '—' : fmtRatio(d.tokens.cache_read_rate)}
                />
              </Ledger>
            </Section>
          </div>
          <Section
            id="garde"
            title="Garde SQL"
            note="Le garde refuse toute requête qui n’est pas une lecture simple des tables autorisées."
          >
            <Ledger label="Garde SQL">
              <Line label="Requêtes bloquées" value={fmtInt(d.guard.blocked)} />
              <Line label="Part des appels bloqués" value={d.guard.block_rate === null ? '—' : fmtRatio(d.guard.block_rate)} />
            </Ledger>
          </Section>
        </>
      )}
      <Section id="sante" title="Santé des composants">
        <HealthLines health={d.health} />
      </Section>
    </>
  );
}

export function AdminOverviewPage() {
  const [range, setRange] = useState<Range>('7d');
  const q = useAdmin<Overview>(['overview', range], `overview?range=${range}`);
  return (
    <div className="adm-page">
      <PageHead
        title="Exploitation"
        description="Ce que l’agent a fait, à quelle vitesse et pour quel coût."
        actions={<Segmented label="Période" value={range} options={RANGES} onChange={setRange} />}
      />
      <Loaded query={q} rows={6}>
        {(d) => <Body d={d} />}
      </Loaded>
    </div>
  );
}
