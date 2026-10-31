import { ChartFrame, SERIES_COLORS } from './ChartFrame';
import { useWidth } from './useWidth';

import './charts.css';

export interface LineSeries {
  name: string;
  points: { x: string; y: number | null }[];
  /** Période précédente : même teinte que la série courante, en pointillés plus clairs. */
  tone?: 'previous';
}

export interface LineChartProps {
  title: string;
  summary: string;
  series: LineSeries[];
  formatY: (v: number) => string;
  formatX?: (x: string) => string;
}

const DASH = [undefined, '7 5', '2 4', '10 4 2 4'] as const;
const H = 220;
const PAD = { top: 14, right: 14, bottom: 26, left: 4 };

/** Courbe : période courante pleine, précédente en pointillés ; légende directe avec dernière valeur. */
export function LineChart({ title, summary, series, formatY, formatX = (x) => x }: LineChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const list = series.slice(0, 4);
  const xs = list[0]?.points.map((p) => p.x) ?? [];
  const values = list.flatMap((s) => s.points.map((p) => p.y).filter((v): v is number => v !== null));
  const max = Math.max(0, ...values);
  const min = Math.min(0, ...values);
  const dmin = values.length ? Math.min(...values) : 0;
  const tight = dmin > 0 && dmin > 0.4 * max; // courbe quasi plate : on resserre l'axe pour voir l'évolution
  const span = max - dmin || max * 0.1 || 1;
  const top = tight ? max + span * 0.25 : niceMax(max);
  const bottom = tight ? Math.max(0, dmin - span * 0.25) : min < 0 ? -niceMax(-min) : 0;
  const iw = Math.max(40, width - PAD.left - PAD.right);
  const ih = H - PAD.top - PAD.bottom;
  const sx = (i: number) => PAD.left + (xs.length <= 1 ? iw / 2 : (i / (xs.length - 1)) * iw);
  const sy = (v: number) => PAD.top + ih - ((v - bottom) / (top - bottom || 1)) * ih;
  const ticks = [bottom, bottom + (top - bottom) / 2, top];
  const labelIdx = xs.length <= 1 ? [0] : width < 420 ? [0, xs.length - 1] : [0, Math.floor((xs.length - 1) / 2), xs.length - 1];
  const showDots = xs.length <= 14;

  const colorOf = (s: LineSeries, i: number) => (s.tone === 'previous' ? SERIES_COLORS[0] : SERIES_COLORS[i]!);

  return (
    <ChartFrame
      title={title}
      summary={summary}
      legend={
        <ul className="ch-legend">
          {list.map((s, i) => {
            const last = [...s.points].reverse().find((p) => p.y !== null);
            return (
              <li key={s.name}>
                <svg width="28" height="10" aria-hidden="true">
                  <line
                    x1="1"
                    y1="5"
                    x2="27"
                    y2="5"
                    stroke={colorOf(s, i)}
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeDasharray={s.tone === 'previous' ? DASH[1] : DASH[i]}
                    opacity={s.tone === 'previous' ? 0.8 : 1}
                  />
                </svg>
                <span>{s.name}</span>
                {last && last.y !== null ? <b className="num">{formatY(last.y)}</b> : null}
              </li>
            );
          })}
        </ul>
      }
      valuesTable={
        <div className="ui-table-wrap ch-values-scroll">
          <table className="ui-table">
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr>
                <th scope="col">Date</th>
                {list.map((s) => (
                  <th key={s.name} scope="col" className="is-num">
                    {s.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {xs.map((x, i) => (
                <tr key={x}>
                  <th scope="row">{formatX(x)}</th>
                  {list.map((s) => {
                    const v = s.points[i]?.y;
                    return (
                      <td key={s.name} className="is-num">
                        {v === null || v === undefined ? '—' : formatY(v)}
                      </td>
                    );
                  })}
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
            height={H}
            viewBox={`0 0 ${width} ${H}`}
          >
            {ticks.map((t) => (
              <g key={t}>
                <line className="ch-grid" x1={PAD.left} x2={width - PAD.right} y1={sy(t)} y2={sy(t)} />
                <text className="ch-tick" x={PAD.left} y={sy(t) - 4}>
                  {formatY(t)}
                </text>
              </g>
            ))}
            {labelIdx.map((i, k) => (
              <text
                key={i}
                className="ch-tick"
                x={sx(i)}
                y={H - 6}
                textAnchor={k === 0 && labelIdx.length > 1 ? 'start' : i === xs.length - 1 && labelIdx.length > 1 ? 'end' : 'middle'}
              >
                {formatX(xs[i]!)}
              </text>
            ))}
            {list.map((s, i) => {
              let d = '';
              let pen = false;
              s.points.forEach((p, j) => {
                if (p.y === null) {
                  pen = false;
                  return;
                }
                d += `${pen ? 'L' : 'M'}${sx(j).toFixed(1)} ${sy(p.y).toFixed(1)}`;
                pen = true;
              });
              const prev = s.tone === 'previous';
              return (
                <g key={s.name}>
                  <path
                    d={d}
                    fill="none"
                    stroke={colorOf(s, i)}
                    strokeWidth={prev ? 2 : 3}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    strokeDasharray={prev ? DASH[1] : DASH[i]}
                    opacity={prev ? 0.8 : 1}
                  />
                  {showDots
                    ? s.points.map((p, j) =>
                        p.y === null ? null : (
                          <circle key={j} className="ch-dot" cx={sx(j)} cy={sy(p.y)} r={prev ? 3 : 3.5} stroke={colorOf(s, i)} />
                        ),
                      )
                    : null}
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </ChartFrame>
  );
}

/** Plus petit « beau » nombre ≥ v (1, 2, 2,5, 5 × 10^n). */
function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const f = v / p;
  const n = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return n * p;
}
