import { ChartFrame } from './ChartFrame';
import { useWidth } from './useWidth';

import './charts.css';

export interface BarItem {
  label: string;
  value: number;
  /** Valeur de comparaison (période précédente), dessinée en barre fine hachurée. */
  compare?: number | null;
}

export interface BarChartProps {
  title: string;
  summary: string;
  items: BarItem[];
  format: (v: number) => string;
  valueLabel?: string;
  compareLabel?: string;
}

const CHAR_W = 7.4;

/** Barres horizontales triées, étiquette et valeur écrites directement sur chaque ligne. */
export function BarChart({ title, summary, items, format, valueLabel = 'Valeur', compareLabel }: BarChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const sorted = [...items].sort((a, b) => b.value - a.value);
  const hasCompare = sorted.some((i) => i.compare !== null && i.compare !== undefined);
  const max = Math.max(1e-9, ...sorted.flatMap((i) => [i.value, i.compare ?? 0]));
  const rowH = hasCompare ? 58 : 44;
  const height = sorted.length * rowH + 4;
  const barW = (v: number) => Math.max(v > 0 ? 3 : 0, (v / max) * (width - 2));

  return (
    <ChartFrame
      title={title}
      summary={summary}
      legend={
        hasCompare ? (
          <ul className="ch-legend">
            <li>
              <svg width="28" height="12" aria-hidden="true">
                <rect x="1" y="1" width="26" height="10" rx="2" fill="var(--c1)" />
              </svg>
              <span>{valueLabel}</span>
            </li>
            <li>
              <svg width="28" height="12" aria-hidden="true">
                <rect x="1.75" y="2.75" width="24.5" height="6.5" rx="2" fill="url(#ch-hatch-legend)" stroke="var(--c1)" strokeWidth="1.5" />
                <defs>
                  <pattern id="ch-hatch-legend" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                    <line x1="0" y1="0" x2="0" y2="5" stroke="var(--c1)" strokeWidth="2" />
                  </pattern>
                </defs>
              </svg>
              <span>{compareLabel ?? 'Période précédente'}</span>
            </li>
          </ul>
        ) : undefined
      }
      valuesTable={
        <div className="ui-table-wrap ch-values-scroll">
          <table className="ui-table">
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr>
                <th scope="col">Catégorie</th>
                <th scope="col" className="is-num">
                  {valueLabel}
                </th>
                {hasCompare ? (
                  <th scope="col" className="is-num">
                    {compareLabel ?? 'Période précédente'}
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {sorted.map((i) => (
                <tr key={i.label}>
                  <th scope="row">{i.label}</th>
                  <td className="is-num">{format(i.value)}</td>
                  {hasCompare ? (
                    <td className="is-num">{i.compare === null || i.compare === undefined ? '—' : format(i.compare)}</td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      }
    >
      {({ describedBy, titleId }) => (
        <div ref={ref} className="ch-canvas">
          <svg
            role="img"
            aria-labelledby={titleId}
            aria-describedby={describedBy}
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
          >
            <defs>
              <pattern id="ch-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="6" stroke="var(--c1)" strokeWidth="2.2" />
              </pattern>
            </defs>
            {sorted.map((it, k) => {
              const y0 = k * rowH;
              const valueText = format(it.value);
              const room = Math.max(6, Math.floor((width - valueText.length * CHAR_W - 16) / CHAR_W));
              const label = it.label.length > room ? `${it.label.slice(0, Math.max(1, room - 1))}…` : it.label;
              return (
                <g key={it.label}>
                  <text className="ch-label" x={0} y={y0 + 15}>
                    {label}
                    <title>{it.label}</title>
                  </text>
                  <text className="ch-value" x={width} y={y0 + 15} textAnchor="end">
                    {valueText}
                  </text>
                  <rect className="ch-track" x={0} y={y0 + 23} width={width} height={hasCompare ? 14 : 12} rx={3} />
                  <rect x={0} y={y0 + 23} width={barW(it.value)} height={hasCompare ? 14 : 12} rx={3} fill="var(--c1)" />
                  {hasCompare && it.compare !== null && it.compare !== undefined ? (
                    <rect
                      x={0.75}
                      y={y0 + 40}
                      width={Math.max(2, barW(it.compare) - 1.5)}
                      height={7}
                      rx={2}
                      fill="url(#ch-hatch)"
                      stroke="var(--c1)"
                      strokeWidth={1.5}
                    />
                  ) : null}
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </ChartFrame>
  );
}
