/** Le relevé : une ligne par indicateur (valeur, période précédente, écart signé, barres de comparaison). */
import { forwardRef } from 'react';

import { fmtDeltaPct } from '@/shared/format';
import { Icon } from '@/shared/ui';

import { LocalIcon } from './icons';
import type { DashboardData, Tile } from './types';

type Trend = 'up' | 'down' | 'flat' | 'none';

/** Un taux d'échec qui baisse est une bonne nouvelle ; pour les autres indicateurs, c'est la hausse. */
const LOWER_IS_BETTER = new Set(['taux_echec']);

function deltaOf(t: Tile): { text: string; sub: string | null; trend: Trend; good: boolean | null } {
  const isPoints = t.delta_pp !== null && t.delta_pp !== undefined;
  const raw = isPoints ? t.delta_pp : t.delta_pct;
  if (raw === null || raw === undefined) return { text: '—', sub: null, trend: 'none', good: null };
  const text = isPoints
    ? (t.rendered_delta_pp ?? `${raw}`)
    : (t.rendered_delta_pct ?? fmtDeltaPct(raw));
  const sub = isPoints ? 'écart en points' : (t.rendered_delta_abs ?? null);
  const trend: Trend = Math.abs(raw) < 0.05 ? 'flat' : raw > 0 ? 'up' : 'down';
  const good = trend === 'flat' ? null : LOWER_IS_BETTER.has(t.metric) ? trend === 'down' : trend === 'up';
  return { text: text, sub, trend, good };
}

function TrendIcon({ trend }: { trend: Trend }) {
  if (trend === 'up') return <Icon name="arrowUp" size={16} />;
  if (trend === 'down') return <Icon name="arrowDown" size={16} />;
  return <LocalIcon name="minus" size={16} />;
}

function trendWord(trend: Trend): string {
  return trend === 'up' ? 'en hausse' : trend === 'down' ? 'en baisse' : trend === 'flat' ? 'stable' : '';
}

function pct(v: number | null | undefined, max: number): number {
  if (v === null || v === undefined || max <= 0) return 0;
  return Math.max(2, Math.round((Math.abs(v) / max) * 100));
}

interface RowProps {
  tile: Tile;
  reason: string | null;
  highlighted: boolean;
}

const Row = forwardRef<HTMLTableRowElement, RowProps>(function Row({ tile, reason, highlighted }, ref) {
  const id = `indicateur-${tile.metric}`;
  if (!tile.available) {
    return (
      <tr ref={ref} id={id} tabIndex={-1} className="rel-row rel-row-off" data-highlight={highlighted || undefined}>
        <th scope="row" className="rel-name">
          {tile.label}
        </th>
        <td colSpan={3} className="rel-off">
          <strong>Indisponible</strong>
          {reason ? <span>{reason}</span> : null}
        </td>
      </tr>
    );
  }
  const d = deltaOf(tile);
  const max = Math.max(Math.abs(tile.value ?? 0), Math.abs(tile.previous ?? 0));
  return (
    <tr ref={ref} id={id} tabIndex={-1} className="rel-row" data-highlight={highlighted || undefined}>
      <th scope="row" className="rel-name">
        {tile.label}
      </th>
      <td className="rel-cur">
        <span className="rel-lbl">Période</span>
        <span className="rel-val num">{tile.rendered ?? '—'}</span>
        <span className="rel-bar" aria-hidden="true">
          <i style={{ width: `${pct(tile.value, max)}%` }} />
        </span>
      </td>
      <td className="rel-prev">
        <span className="rel-lbl">Précédente</span>
        <span className="rel-val num">{tile.rendered_previous ?? '—'}</span>
        <span className="rel-bar" aria-hidden="true">
          <i style={{ width: `${pct(tile.previous, max)}%` }} />
        </span>
      </td>
      <td className="rel-delta">
        <span className="rel-lbl">Écart</span>
        <span
          className="rel-chg num"
          data-good={d.good === null ? undefined : String(d.good)}
          data-trend={d.trend}
        >
          <TrendIcon trend={d.trend} />
          <span>{d.text}</span>
          {d.trend !== 'none' ? <span className="sr-only">, {trendWord(d.trend)}</span> : null}
        </span>
        {d.sub ? <span className="rel-sub num">{d.sub}</span> : null}
      </td>
    </tr>
  );
});

export function Statement({
  data,
  highlight,
  setRowRef,
}: {
  data: DashboardData;
  highlight: string | null;
  setRowRef: (metric: string) => (el: HTMLTableRowElement | null) => void;
}) {
  const unavailable = data.tiles.filter((t) => !t.available).length;
  const reason = data.errors[0] ?? null;
  const all = unavailable === data.tiles.length;
  const scope = data.region ?? 'Toutes les régions';
  const cur = data.period.label ?? data.period.start;
  const prev = data.compare_period.label ?? data.compare_period.start;
  return (
    <div className="rel">
      {all && reason ? (
        <p className="rel-note" role="status">
          {reason}
        </p>
      ) : null}
      <table className="rel-table">
        <caption className="sr-only">
          Indicateurs de {cur} ({scope}), comparés à {prev}
        </caption>
        <thead>
          <tr>
            <th scope="col">Indicateur</th>
            <th scope="col">{cur}</th>
            <th scope="col">{prev}</th>
            <th scope="col">Écart</th>
          </tr>
        </thead>
        <tbody>
          {data.tiles.map((t) => (
            <Row
              key={t.metric}
              ref={setRowRef(t.metric)}
              tile={t}
              reason={all ? null : reason}
              highlighted={highlight === t.metric}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StatementSkeleton() {
  return (
    <div className="rel" aria-busy="true">
      <span className="sr-only" role="status">
        Chargement des indicateurs…
      </span>
      <div className="rel-skel" aria-hidden="true">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="ui-skeleton" />
        ))}
      </div>
    </div>
  );
}
