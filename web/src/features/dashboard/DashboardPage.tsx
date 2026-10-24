/** Indicateurs : le relevé du mois (RF4) et l'analyse de l'agent de données (RF17). Période et région dans l'URL. */
import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';

import { ApiError, api } from '@/api/client';
import { useAuth } from '@/auth/useAuth';
import { Button, EmptyState, ErrorState, Field, PageHead } from '@/shared/ui';

import { Analysis } from './Analysis';
import { MONTH_RE, REGIONS, monthsEnding } from './regions';
import { Statement, StatementSkeleton } from './Statement';
import type { DashboardData } from './types';

import './dashboard.css';

function dashboardPath(periode: string, region: string): string {
  const q = new URLSearchParams();
  if (periode) q.set('period', periode);
  if (region) q.set('region', region);
  const s = q.toString();
  return `/dashboard${s ? `?${s}` : ''}`;
}

function useDashboard(periode: string, region: string, enabled = true) {
  return useQuery({
    queryKey: ['dashboard', periode, region],
    queryFn: () => api<DashboardData>(dashboardPath(periode, region)),
    enabled,
  });
}

export function DashboardPage() {
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const rawPeriode = params.get('periode') ?? '';
  const rawRegion = params.get('region') ?? '';
  const periode = MONTH_RE.test(rawPeriode) ? rawPeriode : '';
  const region = (REGIONS as readonly string[]).includes(rawRegion) ? rawRegion : '';

  const dash = useDashboard(periode, region);
  // Sans période dans l'URL, la réponse porte déjà sur le mois de référence ; sinon on le demande à part.
  const ref = useDashboard('', '', periode !== '');
  const refMonth = (periode === '' ? dash.data : ref.data)?.period.start.slice(0, 7) ?? null;
  const shownMonth = periode || refMonth;

  const months = useMemo(() => {
    const list = refMonth ? monthsEnding(refMonth) : [];
    if (periode && !list.some((m) => m.value === periode)) list.push({ value: periode, label: periode });
    return list;
  }, [refMonth, periode]);

  const update = useCallback(
    (key: 'periode' | 'region', value: string) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value && !(key === 'periode' && value === refMonth)) next.set(key, value);
          else next.delete(key);
          return next;
        },
        { replace: false },
      );
    },
    [setParams, refMonth],
  );

  // Mise en évidence d'une ligne depuis une source de l'analyse.
  const rows = useRef(new Map<string, HTMLTableRowElement>());
  const [highlight, setHighlight] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const setRowRef = useCallback(
    (metric: string) => (el: HTMLTableRowElement | null) => {
      if (el) rows.current.set(metric, el);
      else rows.current.delete(metric);
    },
    [],
  );
  const showRow = useCallback((metric: string) => {
    const el = rows.current.get(metric);
    setHighlight(metric);
    el?.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
    el?.focus({ preventScroll: true });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setHighlight(null), 6000);
  }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const canRegenerate = me?.role === 'analyste' || me?.role === 'admin';
  const err = dash.error;
  const unavailable = err instanceof ApiError && err.status === 503;
  const cur = dash.data?.period.label;
  const prev = dash.data?.compare_period.label;

  return (
    <div className="dash">
      <PageHead
        title="Indicateurs"
        description="Le relevé du mois, comparé au mois précédent, puis l’analyse que l’agent en tire."
      />

      <div className="dash-filters" role="group" aria-label="Choix du relevé">
        <Field label="Période">
          {(p) => (
            <select
              {...p}
              className="ui-select"
              value={shownMonth ?? ''}
              disabled={months.length === 0}
              onChange={(e) => update('periode', e.target.value)}
            >
              {months.length === 0 ? <option value="">Chargement…</option> : null}
              {months.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Région">
          {(p) => (
            <select {...p} className="ui-select" value={region} onChange={(e) => update('region', e.target.value)}>
              <option value="">Toutes les régions</option>
              {REGIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>

      <div className="dash-grid">
        <section className="dash-releve" aria-labelledby="releve-titre">
          <header className="dash-sec-head">
            <h2 id="releve-titre">{cur ? `Relevé de ${cur}` : 'Relevé'}</h2>
            {dash.data ? (
              <p>
                {dash.data.region ?? 'Toutes les régions'}, comparé à {prev}.
              </p>
            ) : null}
          </header>
          {dash.isPending ? <StatementSkeleton /> : null}
          {dash.isError && unavailable ? (
            <EmptyState
              title="Tableau de bord momentanément indisponible"
              action={
                <Button variant="secondary" icon="refresh" onClick={() => void dash.refetch()}>
                  Réessayer
                </Button>
              }
            >
              Les indicateurs ne peuvent pas être calculés pour le moment. Réessayez dans un instant.
            </EmptyState>
          ) : null}
          {dash.isError && !unavailable ? <ErrorState error={err} onRetry={() => void dash.refetch()} /> : null}
          {dash.data ? <Statement data={dash.data} highlight={highlight} setRowRef={setRowRef} /> : null}
        </section>

        <section className="dash-analyse" aria-labelledby="analyse-titre">
          <header className="dash-sec-head">
            <h2 id="analyse-titre">Analyse de l’agent de données</h2>
          </header>
          <Analysis
            key={`${shownMonth ?? ''}|${region}`}
            month={dash.data ? dash.data.period.start.slice(0, 7) : null}
            region={region || null}
            data={dash.data}
            canRegenerate={canRegenerate}
            onSource={showRow}
          />
        </section>
      </div>
    </div>
  );
}
