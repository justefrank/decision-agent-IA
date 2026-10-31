/** Rend le graphique choisi par le code (`chart.type`) à partir du tableau de résultat. Jamais de choix ici. */
import type { ColumnInfo } from '@/api/types';
import { BarChart, DataTable, DonutChart, LineChart, type Cell, type LineSeries } from '@/shared/charts';
import type { Message } from './copy';
import { fmtByUnit, fmtDate, fmtMonth } from '@/shared/format';

type Row = unknown[];

const colLabel = (c: ColumnInfo) => c.label ?? c.name;

function shortDate(x: string): string {
  if (/^\d{4}-\d{2}-\d{2}/.test(x)) {
    return new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' }).format(new Date(x.slice(0, 10)));
  }
  if (/^\d{4}-\d{2}$/.test(x)) return fmtMonth(x);
  return x;
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export function ReceiptChart({ message }: { message: Message }) {
  const { chart, table } = message;
  if (!table || table.rows.length === 0) return null;
  const cols = table.columns;
  const rows = table.rows as Row[];
  const idx = (name: string | null | undefined) => (name ? cols.findIndex((c) => c.name === name) : -1);
  const yCols = (chart?.y ?? []).map(idx).filter((i) => i >= 0);
  const xi = idx(chart?.x);
  const si = idx(chart?.series);
  const unitOf = (i: number) => cols[i]?.unit ?? null;
  const fmtY = (i: number) => (v: number) => fmtByUnit(v, unitOf(i));

  if (chart?.type === 'kpi') return null;

  if (chart?.type === 'line' && xi >= 0 && yCols.length > 0) {
    const y0 = yCols[0]!;
    let series: LineSeries[];
    if (si >= 0) {
      const names = [...new Set(rows.map((r) => String(r[si])))];
      const xs = [...new Set(rows.map((r) => String(r[xi])))];
      series = names.slice(0, 4).map((n) => ({
        name: n,
        points: xs.map((x) => ({ x, y: num(rows.find((r) => String(r[si]) === n && String(r[xi]) === x)?.[y0]) })),
      }));
    } else {
      series = yCols.slice(0, 2).map((yi, k) => ({
        name: colLabel(cols[yi]!),
        tone: k === 1 ? ('previous' as const) : undefined,
        points: rows.map((r) => ({ x: String(r[xi]), y: num(r[yi]) })),
      }));
    }
    const first = series[0]!.points;
    const vals = first.map((p) => p.y).filter((v): v is number => v !== null);
    const f = fmtY(y0);
    const summary = `Courbe de ${colLabel(cols[y0]!)}, de ${shortDate(first[0]?.x ?? '')} à ${shortDate(first[first.length - 1]?.x ?? '')}. ${
      vals.length ? `Valeurs de ${f(Math.min(...vals))} à ${f(Math.max(...vals))}.` : ''
    }`;
    return <LineChart title={colLabel(cols[y0]!)} summary={summary} series={series} formatY={f} formatX={shortDate} />;
  }

  if (chart?.type === 'bar' && xi >= 0 && yCols.length > 0) {
    const y0 = yCols[0]!;
    let items: { label: string; value: number; compare?: number | null }[];
    let valueLabel = colLabel(cols[y0]!);
    let compareLabel: string | undefined;
    if (si >= 0) {
      const names = [...new Set(rows.map((r) => String(r[si])))];
      const labels = [...new Set(rows.map((r) => String(r[xi])))];
      valueLabel = names[0] ?? valueLabel;
      compareLabel = names[1];
      items = labels.map((l) => ({
        label: l,
        value: num(rows.find((r) => String(r[xi]) === l && String(r[si]) === names[0])?.[y0]) ?? 0,
        compare: names[1] ? num(rows.find((r) => String(r[xi]) === l && String(r[si]) === names[1])?.[y0]) : undefined,
      }));
    } else {
      const y1 = yCols[1];
      compareLabel = y1 !== undefined ? colLabel(cols[y1]!) : undefined;
      items = rows.map((r) => ({
        label: String(r[xi]),
        value: num(r[y0]) ?? 0,
        compare: y1 !== undefined ? num(r[y1]) : undefined,
      }));
    }
    const f = fmtY(y0);
    const top = [...items].sort((a, b) => b.value - a.value)[0];
    const summary = `${items.length} valeurs triées de la plus grande à la plus petite. ${top ? `${top.label} est en tête avec ${f(top.value)}.` : ''}`;
    return (
      <BarChart title={colLabel(cols[y0]!)} summary={summary} items={items} format={f} valueLabel={valueLabel} compareLabel={compareLabel} />
    );
  }

  if (chart?.type === 'donut' && xi >= 0 && yCols.length > 0) {
    const y0 = yCols[0]!;
    const parts = rows.map((r) => ({ label: String(r[xi]), value: num(r[y0]) ?? 0 }));
    const f = fmtY(y0);
    const total = parts.reduce((s, p) => s + p.value, 0) || 1;
    const top = [...parts].sort((a, b) => b.value - a.value)[0];
    const summary = `Répartition en ${parts.length} parts. ${top ? `${top.label} représente ${Math.round((top.value / total) * 100)} % du total.` : ''}`;
    return <DonutChart title={colLabel(cols[y0]!)} summary={summary} parts={parts} format={f} />;
  }

  // Tableau (type `table`, ou repli si le graphique ne correspond pas aux colonnes).
  const time = cols.findIndex((c) => c.role === 'time');
  const measure = cols.findIndex((c) => c.role === 'measure');
  const defaultSort =
    time >= 0 ? { column: time, dir: 'asc' as const } : measure >= 0 ? { column: measure, dir: 'desc' as const } : undefined;
  const columns = cols.map((c) => ({ key: c.name, label: colLabel(c), numeric: c.role === 'measure' }));
  const format = (i: number, v: Cell) => {
    if (v === null || v === undefined) return '—';
    const c = cols[i]!;
    if (c.unit === 'date' && typeof v === 'string') return fmtDate(v);
    return fmtByUnit(v, c.unit);
  };
  const title = message.period?.label ? `Résultat, ${message.period.label}` : 'Résultat détaillé';
  return (
    <DataTable
      title={title}
      summary={`Tableau de ${rows.length} ligne${rows.length > 1 ? 's' : ''} et ${cols.length} colonnes.`}
      columns={columns}
      rows={rows as Cell[][]}
      format={format}
      truncated={message.truncated}
      defaultSort={defaultSort}
    />
  );
}
