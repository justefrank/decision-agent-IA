import { useState } from 'react';
import { Link, useParams } from 'react-router';

import { fmtDateTime, fmtInt, fmtMs } from '@/shared/format';
import { EmptyState, PageHead, Segmented } from '@/shared/ui';

import { useAdmin, type CategoryCount, type EvalDetail, type EvalReport, type EvalRunRow } from './adminApi';
import { Ledger, Line, Loaded, Mark, Section, pct, shortId, usd } from './common';

export const TARGET = 0.8;
export const MIN_CATEGORY = 8;

export const ABLATIONS: Record<string, string> = {
  none: 'Bras de base',
  a: 'a : modèle seul, schéma brut',
  b: 'b : sans exemples',
  c: 'c : sans indicateurs certifiés (SQL seul)',
  d: 'd : sans validateur',
  e: 'e : sans citation par référence',
};

export function wilson(k: number, n: number, z = 1.96): [number, number] {
  if (n === 0) return [0, 0];
  const p = k / n;
  const d = 1 + (z * z) / n;
  const c = p + (z * z) / (2 * n);
  const m = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n));
  return [Math.max(0, (c - m) / d), Math.min(1, (c + m) / d)];
}

/** Phrase honnête : la cible n'est démontrée que si la borne basse de l'intervalle l'atteint. */
export function honestSentence(k: number, n: number, low?: number): { kind: 'ok' | 'warn' | 'bad'; text: string } {
  if (n === 0) return { kind: 'warn', text: 'Aucune question évaluée : aucune conclusion n’est possible.' };
  const lo = low ?? wilson(k, n)[0];
  const p = k / n;
  if (lo >= TARGET) return { kind: 'ok', text: `La cible de 80 % est démontrée : même la borne basse de l’intervalle (${pct(lo)}) l’atteint.` };
  if (p >= TARGET)
    return {
      kind: 'warn',
      text: `La mesure atteint 80 %, mais la cible n’est pas démontrée : l’intervalle descend à ${pct(lo)}. Il faut plus de questions ou un meilleur score.`,
    };
  return { kind: 'bad', text: `La cible de 80 % n’est pas atteinte (mesure : ${pct(p)}, borne basse : ${pct(lo)}).` };
}

function IntervalBar({ lo, hi, value, label }: { lo: number; hi: number; value: number; label: string }) {
  return (
    <div className="adm-interval" role="img" aria-label={`${label} : ${pct(value)}, intervalle de ${pct(lo)} à ${pct(hi)}, cible ${pct(TARGET, 0)}`}>
      <span className="adm-interval-range" style={{ left: `${lo * 100}%`, width: `${Math.max(0.5, (hi - lo) * 100)}%` }} />
      <span className="adm-interval-dot" style={{ left: `${value * 100}%` }} />
      <span className="adm-interval-target" style={{ left: `${TARGET * 100}%` }} />
      <span className="adm-interval-tl" style={{ left: `${TARGET * 100}%` }}>
        cible 80 %
      </span>
    </div>
  );
}

function RunsList() {
  const [split, setSplit] = useState<'' | 'dev' | 'test'>('');
  const q = useAdmin<{ items: EvalRunRow[] }>(['eval-runs', split], `eval/runs${split ? `?split=${split}` : ''}`);
  return (
    <div className="adm-page">
      <PageHead
        title="Évaluation"
        description="Le score de l’agent sur des questions écrites à la main, avec l’incertitude qui l’accompagne."
        actions={
          <Segmented
            label="Jeu de questions"
            value={split}
            options={[
              { value: '', label: 'Tous' },
              { value: 'dev', label: 'Développement' },
              { value: 'test', label: 'Test' },
            ]}
            onChange={setSplit}
          />
        }
      />
      <Loaded query={q} rows={5}>
        {({ items }) =>
          items.length === 0 ? (
            <EmptyState title="Aucune évaluation enregistrée">
              <>
                Lancez <code>make eval SPLIT=dev</code> (ou <code>SPLIT=test</code> pour le chiffre d’acceptation) avec l’option
                d’enregistrement en base <code>--write-db-env</code> : l’exécution apparaîtra ici.
              </>
            </EmptyState>
          ) : (
            <>
              <div className="ui-table-wrap">
                <table className="ui-table">
                  <caption className="sr-only">Exécutions d’évaluation, de la plus récente à la plus ancienne</caption>
                  <thead>
                    <tr>
                      <th scope="col">Date</th>
                      <th scope="col">Jeu</th>
                      <th scope="col">Variante</th>
                      <th scope="col" className="is-num">Questions</th>
                      <th scope="col" className="is-num">3 réussites sur 3</th>
                      <th scope="col">Intervalle à 95 %</th>
                      <th scope="col">Cible de 80 %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((r) => {
                      const s = honestSentence(r.n_correct, r.n);
                      return (
                        <tr key={r.id}>
                          <td>
                            <Link to={`/admin/evaluation/${r.id}`}>{fmtDateTime(r.ts)}</Link>
                          </td>
                          <td>{r.split === 'test' ? 'Test' : 'Développement'}</td>
                          <td>{ABLATIONS[r.ablation ?? 'none'] ?? r.ablation}</td>
                          <td className="is-num">{fmtInt(r.n)}</td>
                          <td className="is-num">
                            {r.n_correct} sur {r.n} ({pct(r.n ? r.n_correct / r.n : 0)})
                          </td>
                          <td className="num">
                            {pct(r.ci_low ?? wilson(r.n_correct, r.n)[0])} à {pct(r.ci_high ?? wilson(r.n_correct, r.n)[1])}
                          </td>
                          <td>{s.kind === 'ok' ? <Mark kind="ok">Démontrée</Mark> : <Mark kind={s.kind}>Non démontrée</Mark>}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <Ablations items={items} />
            </>
          )
        }
      </Loaded>
    </div>
  );
}

function Ablations({ items }: { items: EvalRunRow[] }) {
  const latest = new Map<string, EvalRunRow>();
  for (const r of items) {
    const key = `${r.split}|${r.ablation ?? 'none'}`;
    if (!latest.has(key)) latest.set(key, r);
  }
  const arms = [...latest.values()].filter((r) => (r.ablation ?? 'none') !== 'none');
  if (arms.length === 0) return null;
  return (
    <Section
      id="ablations"
      title="Ablations"
      note="On retire un composant à la fois pour mesurer ce qu’il apporte. Dernière exécution de chaque variante ; sous 70 questions, la comparaison reste descriptive."
    >
      <div className="ui-table-wrap">
        <table className="ui-table">
          <caption className="sr-only">Dernier score de chaque variante</caption>
          <thead>
            <tr>
              <th scope="col">Variante</th>
              <th scope="col">Jeu</th>
              <th scope="col" className="is-num">3 réussites sur 3</th>
              <th scope="col" className="is-num">Écart avec le bras de base</th>
            </tr>
          </thead>
          <tbody>
            {arms.map((r) => {
              const base = latest.get(`${r.split}|none`);
              const delta = base && base.n && r.n ? r.n_correct / r.n - base.n_correct / base.n : null;
              return (
                <tr key={r.id}>
                  <td>{ABLATIONS[r.ablation ?? ''] ?? r.ablation}</td>
                  <td>{r.split === 'test' ? 'Test' : 'Développement'}</td>
                  <td className="is-num">
                    {r.n_correct} sur {r.n}
                  </td>
                  <td className="is-num">
                    {delta === null ? 'Pas de bras de base' : `${delta > 0 ? '+' : delta < 0 ? '−' : ''}${pct(Math.abs(delta))}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function Categories({ cats, isTest }: { cats: Record<string, CategoryCount>; isTest: boolean }) {
  const rows = Object.entries(cats);
  if (rows.length === 0) return null;
  return (
    <Section
      id="categories"
      title="Par catégorie"
      note={`Comptes bruts. Sous ${MIN_CATEGORY} questions, une catégorie ne permet aucune conclusion.${isTest ? ' Pour le jeu de test, les échecs ne sont analysés que par catégorie.' : ''}`}
    >
      <div className="ui-table-wrap">
        <table className="ui-table">
          <caption className="sr-only">Résultats par catégorie de questions</caption>
          <thead>
            <tr>
              <th scope="col">Catégorie</th>
              <th scope="col" className="is-num">3 réussites sur 3</th>
              <th scope="col" className="is-num">Réussite à la 1re passe</th>
              <th scope="col">Lecture</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, c]) => (
              <tr key={name}>
                <th scope="row">{name}</th>
                <td className="is-num">
                  {c.pass3} sur {c.n}
                </td>
                <td className="is-num">{c.pass1 === undefined ? '—' : pct(c.pass1, 0)}</td>
                <td>{c.n < MIN_CATEGORY ? `Pas de conclusion sous ${MIN_CATEGORY} questions` : 'Échantillon suffisant pour lire le taux'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function Body({ d }: { d: EvalDetail }) {
  const run = d.run;
  const rep: EvalReport = run.report ?? {};
  const isTest = run.split === 'test';
  const k = rep.score?.pass3.k ?? run.n_correct;
  const n = rep.score?.pass3.n ?? run.n;
  const [lo, hi] = rep.score?.pass3.wilson95 ?? [run.ci_low ?? wilson(k, n)[0], run.ci_high ?? wilson(k, n)[1]];
  const rate = n ? k / n : 0;
  const sentence = honestSentence(k, n, lo);
  const p1 = rep.score?.pass1;
  const cons = rep.score?.consistency;
  const cats: Record<string, CategoryCount> =
    rep.categories ?? Object.fromEntries(Object.entries(d.by_category).map(([c, v]) => [c, { n: v.n, pass3: v.pass3 }]));
  const failing = d.results.filter((r) => r.passes < (rep.passes ?? 3));
  const failCats = rep.failures_by_category ?? {};
  const cmp = rep.ablation_comparison?.pass3;

  return (
    <>
      <section className="adm-receipt" aria-labelledby="score">
        <h2 id="score">3 réussites sur 3</h2>
        <p className="adm-figure num">
          <span className="adm-key">{pct(rate)}</span>
          <span>
            {' '}
            {k} questions sur {n}
          </span>
        </p>
        <IntervalBar lo={lo} hi={hi} value={rate} label="Taux de questions réussies 3 fois sur 3" />
        <p className="num adm-interval-txt">
          Intervalle de Wilson à 95 % : de {pct(lo)} à {pct(hi)}
        </p>
        <p className="adm-verdict" data-kind={sentence.kind}>
          <Mark kind={sentence.kind}>{sentence.kind === 'ok' ? 'Cible démontrée' : 'Cible non démontrée'}</Mark>
          <span>{sentence.text}</span>
        </p>
        <p className="adm-note">
          Une question compte comme réussie quand l’agent donne trois fois de suite la bonne réponse : exécution, chiffres cités,
          période et périmètre.
        </p>
      </section>

      <div className="adm-cols">
        <Section id="pass1" title="Réussite à la 1re passe">
          <Ledger label="Réussite à la première passe">
            <Line label="Moyenne" value={p1 ? pct(p1.mean) : run.pass1 === null ? '—' : pct(run.pass1)} />
            {p1 ? <Line label="Intervalle à 95 %" value={`${pct(p1.bootstrap95[0])} à ${pct(p1.bootstrap95[1])}`} hint="Rééchantillonnage par question" /> : null}
          </Ledger>
        </Section>
        {cons ? (
          <Section id="coherence" title="Cohérence entre passes" note="Combien de questions réussies à chaque passe, 3 fois, 2 fois, 1 fois ou jamais.">
            <Ledger label="Cohérence">
              {Object.entries(cons).map(([key, v]) => (
                <Line key={key} label={`${key.replace('/', ' sur ')} passes réussies`} value={`${fmtInt(v)} ${v > 1 ? 'questions' : 'question'}`} />
              ))}
            </Ledger>
          </Section>
        ) : null}
      </div>

      <Categories cats={cats} isTest={isTest} />

      <Section id="variante" title="Variante testée" note={cmp?.descriptive ? 'Sous 70 questions, la comparaison reste descriptive.' : undefined}>
        <Ledger label="Variante">
          <Line label="Bras" value={ABLATIONS[run.ablation ?? 'none'] ?? run.ablation} />
          {cmp ? (
            <>
              <Line label="Écart avec le bras de base" value={`${cmp.delta > 0 ? '+' : cmp.delta < 0 ? '−' : ''}${pct(Math.abs(cmp.delta))} sur ${cmp.n} questions`} />
              {cmp.p_value !== undefined ? <Line label="Probabilité sous l’hypothèse d’égalité (McNemar)" value={String(cmp.p_value.toFixed(3)).replace('.', ',')} /> : null}
            </>
          ) : (
            <Line label="Comparaison" value="Aucune comparaison enregistrée pour cette exécution" />
          )}
        </Ledger>
      </Section>

      <div className="adm-cols">
        <Section id="latence" title="Latence" note={rep.latency_ms?.note}>
          <Ledger label="Latence">
            <Line label="Médiane" value={fmtMs(rep.latency_ms?.p50)} />
            <Line label="9 sur 10" value={fmtMs(rep.latency_ms?.p90)} />
            <Line label="Maximum" value={fmtMs(rep.latency_ms?.max)} />
          </Ledger>
        </Section>
        <Section id="cout" title="Coût">
          <Ledger label="Coût">
            <Line label="Total" value={usd(rep.cost?.usd_total)} />
            <Line label="Par réponse" value={usd(rep.cost?.usd_per_question_pass)} />
            <Line label="Par réussite" value={usd(rep.cost?.usd_per_success)} />
          </Ledger>
        </Section>
      </div>

      <Section
        id="echecs"
        title="Échecs"
        note={isTest ? 'Jeu de test : seule l’analyse par catégorie est montrée, pour ne pas ajuster l’agent aux questions du test.' : undefined}
      >
        {isTest ? (
          Object.keys(failCats).length === 0 ? (
            <p>Aucun échec enregistré.</p>
          ) : (
            <ul className="adm-plain">
              {Object.entries(failCats).map(([cat, reasons]) => (
                <li key={cat}>
                  <strong>{cat}</strong> : {Object.entries(reasons).map(([r, c]) => `${r} (${c})`).join(', ')}
                </li>
              ))}
            </ul>
          )
        ) : failing.length === 0 ? (
          <p>Aucune question n’a échoué.</p>
        ) : (
          <div className="ui-table-wrap">
            <table className="ui-table">
              <caption className="sr-only">Questions non réussies 3 fois sur 3</caption>
              <thead>
                <tr>
                  <th scope="col">Question</th>
                  <th scope="col">Catégorie</th>
                  <th scope="col" className="is-num">Passes réussies</th>
                  <th scope="col">Raisons</th>
                </tr>
              </thead>
              <tbody>
                {failing.map((r) => (
                  <tr key={r.question_id}>
                    <td>
                      <code>{r.question_id}</code>
                    </td>
                    <td>{r.category ?? '—'}</td>
                    <td className="is-num">{r.passes} sur {rep.passes ?? 3}</td>
                    <td>{r.got?.reasons?.length ? r.got.reasons.join(' ; ') : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {rep.degenerate_references?.length ? (
        <p className="adm-warn">
          <span>
            Références dégénérées ({rep.degenerate_references.join(', ')}) : à cette échelle de données, le score ne mesure pas tout.
          </span>
        </p>
      ) : null}

      <Section id="trace" title="Traçabilité">
        <Ledger label="Traçabilité">
          <Line label="Modèle" value={run.model_id ?? '—'} />
          <Line label="Version du prompt" value={run.prompt_version ?? '—'} />
          <Line label="Version sémantique" value={run.semantic_version ?? '—'} />
          <Line label="Commit" value={<code>{shortId(run.git_sha, 10)}</code>} />
        </Ledger>
      </Section>
    </>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const q = useAdmin<EvalDetail>(['eval-run', runId], `eval/runs/${encodeURIComponent(runId)}`);
  return (
    <div className="adm-page">
      <PageHead
        title={q.data ? `Évaluation du ${fmtDateTime(q.data.run.ts)}` : 'Évaluation'}
        description={
          q.data ? `Jeu ${q.data.run.split === 'test' ? 'de test' : 'de développement'}, ${q.data.run.n} questions.` : undefined
        }
        actions={<Link to="/admin/evaluation">Toutes les exécutions</Link>}
      />
      <Loaded query={q} rows={6}>
        {(d) => <Body d={d} />}
      </Loaded>
    </div>
  );
}

export function AdminEvalPage() {
  const { runId } = useParams();
  return runId ? <RunDetail runId={runId} /> : <RunsList />;
}
