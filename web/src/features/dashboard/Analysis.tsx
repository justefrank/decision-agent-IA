/** Analyse de l'agent de données : constats sourcés, confiance en toutes lettres, hypothèses étiquetées. */
import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';

import { ApiError, api } from '@/api/client';
import type { DashboardAnalysis } from '@/api/types';
import { fmtDateTime } from '@/shared/format';
import { Button, Icon, announce, type IconName } from '@/shared/ui';

import { LocalIcon, type LocalIconName } from './icons';
import type { AnalysisResponse, DashboardData } from './types';

type Finding = DashboardAnalysis['findings'][number];

export const STEPS = [
  'Lecture des indicateurs',
  'Comparaison avec la période précédente',
  'Recherche d’écarts par région',
] as const;
const STEP_MS = 2200;
export const COOLDOWN_S = 60;

const TAGS: Record<Finding['tag'], { icon: IconName | LocalIconName; tone: 'pos' | 'neg' | 'neutral' }> = {
  Hausse: { icon: 'arrowUp', tone: 'pos' },
  Baisse: { icon: 'arrowDown', tone: 'neg' },
  'À surveiller': { icon: 'alert', tone: 'neg' },
  Écart: { icon: 'swap', tone: 'neutral' },
  'Écart favorable': { icon: 'check', tone: 'pos' },
};

function TagIcon({ name }: { name: IconName | LocalIconName }) {
  return name === 'swap' ? <LocalIcon name="swap" size={16} /> : <Icon name={name as IconName} size={16} />;
}

const CONFIDENCE: Record<Finding['confidence'], { text: string; pips: number }> = {
  elevee: { text: 'Confiance élevée', pips: 3 },
  moyenne: { text: 'Confiance moyenne', pips: 2 },
  hypothese: { text: 'Hypothèse', pips: 0 },
};

export function analysisErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429)
      return 'Trop de demandes pour le moment, ou limite du jour atteinte. Patientez une minute, puis réessayez.';
    if (err.status === 403) return 'La régénération est réservée aux analystes et aux administrateurs.';
    if (err.status === 503)
      return 'L’analyse est momentanément indisponible. Le relevé reste valable ; réessayez dans un instant.';
    return err.message;
  }
  return 'L’analyse n’a pas pu être produite. Réessayez dans un instant.';
}

function Steps() {
  const [current, setCurrent] = useState(0);
  useEffect(() => {
    announce(`Génération de l’analyse. ${STEPS[0]}.`);
    let i = 0;
    const t = window.setInterval(() => {
      if (i < STEPS.length - 1) {
        i += 1;
        setCurrent(i);
        announce(`${STEPS[i]}.`);
      }
    }, STEP_MS);
    return () => window.clearInterval(t);
  }, []);
  return (
    <div className="an-steps">
      <p className="an-steps-title">Analyse en cours</p>
      <ol>
        {STEPS.map((s, i) => {
          const state = i < current ? 'done' : i === current ? 'now' : 'next';
          return (
            <li key={s} data-state={state} aria-current={state === 'now' ? 'step' : undefined}>
              <span className="an-mark" aria-hidden="true">
                {state === 'done' ? <Icon name="check" size={14} /> : null}
              </span>
              <span>{s}</span>
              <span className="sr-only">
                {state === 'done' ? ', terminé' : state === 'now' ? ', en cours' : ', à venir'}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Pips({ n }: { n: number }) {
  return (
    <span className="an-pips" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <i key={i} data-on={i < n || undefined} />
      ))}
    </span>
  );
}

function FindingItem({
  f,
  sources,
  onSource,
}: {
  f: Finding;
  sources: { key: string; label: string; metric: string | null }[];
  onSource: (metric: string) => void;
}) {
  const tag = TAGS[f.tag];
  const conf = CONFIDENCE[f.confidence];
  const isHyp = f.confidence === 'hypothese';
  return (
    <li className="an-finding" data-hypothesis={isHyp || undefined}>
      <div className="an-meta">
        <span className="an-tag" data-tone={tag.tone}>
          <TagIcon name={tag.icon} />
          {f.tag}
        </span>
        {isHyp ? (
          <span className="an-hyp-label">
            <LocalIcon name="help" size={16} />
            Hypothèse
          </span>
        ) : (
          <span className="an-conf">
            <Pips n={conf.pips} />
            {conf.text}
          </span>
        )}
      </div>
      <p className="an-text">{f.text}</p>
      {f.hypothesis ? (
        <p className="an-hyp">
          <strong>
            <LocalIcon name="help" size={16} />
            Hypothèse
          </strong>
          <span>{f.hypothesis}</span>
          <em>Non vérifiée dans les données.</em>
        </p>
      ) : null}
      {sources.length > 0 ? (
        <div className="an-sources">
          <span id={`src-${f.sources.join('-')}`} className="an-src-title">
            Sources
          </span>
          <ul aria-labelledby={`src-${f.sources.join('-')}`}>
            {sources.map((s) => (
              <li key={s.key}>
                {s.metric ? (
                  <button
                    type="button"
                    className="an-src"
                    aria-label={`Voir la ligne ${s.label} dans le relevé`}
                    onClick={() => onSource(s.metric!)}
                  >
                    {s.label}
                  </button>
                ) : (
                  <span className="an-src an-src-plain">{s.label}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </li>
  );
}

/** Ramène les identifiants de faits cités à des lignes du relevé (une puce par indicateur). */
function resolveSources(
  f: Finding,
  data: DashboardData | undefined,
  facts: DashboardAnalysis['facts'],
): { key: string; label: string; metric: string | null }[] {
  const out = new Map<string, { key: string; label: string; metric: string | null }>();
  for (const id of f.sources) {
    const tile = data?.tiles.find((t) => t.available && Object.values(t.fact_ids ?? {}).includes(id));
    if (tile) {
      out.set(tile.metric, { key: tile.metric, label: tile.label, metric: tile.metric });
      continue;
    }
    const fact = facts?.find((x) => x.id === id);
    if (fact) out.set(`fact-${id}`, { key: `fact-${id}`, label: fact.label, metric: null });
  }
  return [...out.values()];
}

function Regenerate({ generatedAt, onClick }: { generatedAt: string | null; onClick: () => void }) {
  const left = () =>
    generatedAt ? Math.max(0, Math.ceil(COOLDOWN_S - (Date.now() - new Date(generatedAt).getTime()) / 1000)) : 0;
  const [cooldown, setCooldown] = useState(left);
  useEffect(() => {
    if (cooldown === 0) return;
    const t = window.setInterval(() => setCooldown(left()), 1000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `left` ne dépend que de generatedAt, fixe pour ce composant
  }, [cooldown === 0]);
  return (
    <div>
      <Button variant="secondary" size="sm" icon="refresh" disabled={cooldown > 0} onClick={onClick}>
        Régénérer l’analyse
      </Button>
      {cooldown > 0 ? <p className="ui-help">Nouvelle génération possible dans {cooldown} s.</p> : null}
    </div>
  );
}

export function Analysis({
  month,
  region,
  data,
  canRegenerate,
  onSource,
}: {
  month: string | null;
  region: string | null;
  data: DashboardData | undefined;
  canRegenerate: boolean;
  onSource: (metric: string) => void;
}) {
  const navigate = useNavigate();
  const [notice, setNotice] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const gen = useMutation({
    mutationFn: (regenerate: boolean) =>
      api<AnalysisResponse>('/dashboard/analysis', { method: 'POST', json: { period: month, region, regenerate } }),
    onSuccess: (res, regenerate) => {
      setNotice(
        regenerate && res.reused
          ? 'Une analyse de moins d’une minute existe déjà : la voici. Une nouvelle génération sera possible dans un instant.'
          : null,
      );
      announce('Analyse prête.');
    },
    onError: (e) => announce(analysisErrorMessage(e)),
  });
  const res = gen.data;
  const a = res?.analysis;
  const ready = month !== null && data !== undefined;

  useEffect(() => {
    if (res && resultRef.current) resultRef.current.focus({ preventScroll: true });
  }, [res]);

  return (
    <div className="an">
      {!res && !gen.isPending ? (
        <div className="an-intro">
          <p>
            L’agent lit les indicateurs, les compare à la période précédente et signale les écarts. Chaque constat
            cite ses sources dans le relevé.
          </p>
          <Button icon="chart" disabled={!ready} onClick={() => gen.mutate(false)}>
            Générer l’analyse
          </Button>
          {!ready ? <p className="ui-help">Disponible dès que le relevé est affiché.</p> : null}
        </div>
      ) : null}

      {gen.isPending ? <Steps /> : null}

      {gen.isError && !gen.isPending ? (
        <div className="an-error" role="alert">
          <p>{analysisErrorMessage(gen.error)}</p>
          <Button
            variant="secondary"
            icon="refresh"
            onClick={() => gen.mutate(gen.variables ?? false)}
            disabled={!ready}
          >
            Réessayer
          </Button>
        </div>
      ) : null}

      {a && !gen.isPending ? (
        <div className="an-result" ref={resultRef} tabIndex={-1}>
          {notice ? (
            <p className="an-notice" role="status">
              {notice}
            </p>
          ) : null}
          {!a.available ? (
            <div className="an-unavailable">
              <h3>Analyse indisponible</h3>
              <p>{a.lead}</p>
              <p className="ui-help">Le relevé reste affiché et à jour.</p>
            </div>
          ) : (
            <>
              <p className="an-lead">{a.lead}</p>
              {a.findings.length > 0 ? (
                <ul className="an-findings">
                  {a.findings.map((f, i) => (
                    <FindingItem
                      key={`${f.tag}-${i}`}
                      f={f}
                      sources={resolveSources(f, data, a.facts)}
                      onSource={onSource}
                    />
                  ))}
                </ul>
              ) : (
                <p className="an-none">Aucun constat à signaler sur cette période.</p>
              )}
              {a.follow_up && a.follow_up.length > 0 ? (
                <div className="an-follow">
                  <h3>Pour aller plus loin</h3>
                  <ul>
                    {a.follow_up.map((q) => (
                      <li key={q}>
                        <button
                          type="button"
                          className="an-q"
                          onClick={() => navigate('/questions', { state: { prefill: q } })}
                        >
                          <Icon name="ask" size={18} />
                          <span>{q}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          )}
          <div className="an-foot">
            <p className="ui-help">
              {res?.reused ? 'Analyse déjà produite le ' : 'Analyse produite le '}
              {fmtDateTime(res?.generated_at)}. Les chiffres viennent du relevé ; seule la rédaction est de
              l’agent.
            </p>
            {canRegenerate ? (
              <Regenerate
                key={res?.generated_at}
                generatedAt={res?.generated_at ?? null}
                onClick={() => gen.mutate(true)}
              />
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
