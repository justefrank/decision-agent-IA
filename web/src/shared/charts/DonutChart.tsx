import { useId } from 'react';

import { fmtRatio } from '@/shared/format';

import { ChartFrame, SERIES_COLORS } from './ChartFrame';

import './charts.css';

export interface DonutPart {
  label: string;
  value: number;
}

export interface DonutChartProps {
  title: string;
  summary: string;
  parts: DonutPart[];
  format: (v: number) => string;
  formatShare?: (ratio: number) => string;
}

const R = 62;
const C = 2 * Math.PI * R;
const GAP = 3;

/** Répartition en parts (6 valeurs au plus) : légende directe avec part et valeur ; teintes + hachures. */
export function DonutChart({ title, summary, parts, format, formatShare = fmtRatio }: DonutChartProps) {
  const pid = useId().replace(/:/g, '');
  const list = parts.filter((p) => p.value > 0).sort((a, b) => b.value - a.value).slice(0, 6);
  const total = list.reduce((s, p) => s + p.value, 0) || 1;
  // Les 4 premières parts en teinte pleine, les suivantes en teinte hachurée.
  const fillOf = (i: number) => (i < 4 ? SERIES_COLORS[i]! : `url(#${pid}-h${i - 4})`);
  const starts = list.map((_, i) => list.slice(0, i).reduce((a, p) => a + (p.value / total) * C, 0));

  return (
    <ChartFrame
      title={title}
      summary={summary}
      valuesTable={
        <div className="ui-table-wrap ch-values-scroll">
          <table className="ui-table">
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr>
                <th scope="col">Part</th>
                <th scope="col" className="is-num">
                  Valeur
                </th>
                <th scope="col" className="is-num">
                  Part du total
                </th>
              </tr>
            </thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.label}>
                  <th scope="row">{p.label}</th>
                  <td className="is-num">{format(p.value)}</td>
                  <td className="is-num">{formatShare(p.value / total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      }
    >
      {({ describedBy, titleId }) => (
        <div className="ch-donut">
          <svg role="img" aria-labelledby={titleId} aria-describedby={describedBy} width="168" height="168" viewBox="0 0 168 168">
            <defs>
              {[0, 1].map((k) => (
                <pattern key={k} id={`${pid}-h${k}`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                  <rect width="6" height="6" fill="var(--card)" />
                  <line x1="0" y1="0" x2="0" y2="6" stroke={SERIES_COLORS[k]} strokeWidth="3" />
                </pattern>
              ))}
            </defs>
            <g transform="rotate(-90 84 84)">
              {list.map((p, i) => {
                const len = (p.value / total) * C;
                return (
                  <circle
                    key={p.label}
                    cx="84"
                    cy="84"
                    r={R}
                    fill="none"
                    stroke={fillOf(i)}
                    strokeWidth="26"
                    strokeDasharray={`${Math.max(0, len - (list.length > 1 ? GAP : 0))} ${C}`}
                    strokeDashoffset={-starts[i]!}
                  />
                );
              })}
            </g>
          </svg>
          <ul className="ch-donut-legend">
            {list.map((p, i) => (
              <li key={p.label}>
                <svg width="16" height="16" aria-hidden="true">
                  <rect width="16" height="16" rx="3" fill={i < 4 ? SERIES_COLORS[i] : `url(#${pid}-h${i - 4})`} />
                </svg>
                <span className="ch-donut-name">{p.label}</span>
                <b className="num">{formatShare(p.value / total)}</b>
                <span className="num ch-donut-val">{format(p.value)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </ChartFrame>
  );
}

