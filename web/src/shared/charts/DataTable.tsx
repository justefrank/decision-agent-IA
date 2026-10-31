import { useState } from 'react';

import { Icon } from '@/shared/ui';

import './charts.css';

export type Cell = string | number | boolean | null | undefined;

export interface TableColumn {
  key: string;
  label: string;
  numeric?: boolean;
}

export interface DataTableProps {
  title: string;
  summary: string;
  columns: TableColumn[];
  rows: Cell[][];
  format?: (columnIndex: number, value: Cell) => string;
  truncated?: boolean;
  /** Tri initial : indice de colonne et sens. Sans lui, l'ordre reçu est conservé. */
  defaultSort?: { column: number; dir: 'asc' | 'desc' };
}

const collator = new Intl.Collator('fr', { numeric: true, sensitivity: 'base' });

/** Tableau triable (aria-sort), défilement horizontal dans sa boîte, ligne « tronqué » si le résultat l'est. */
export function DataTable({ title, summary, columns, rows, format, truncated, defaultSort }: DataTableProps) {
  const [sort, setSort] = useState<{ column: number; dir: 'asc' | 'desc' } | null>(defaultSort ?? null);
  const shown = sort
    ? [...rows].sort((a, b) => {
        const x = a[sort.column];
        const y = b[sort.column];
        const nx = x === null || x === undefined;
        const ny = y === null || y === undefined;
        if (nx || ny) return nx === ny ? 0 : nx ? 1 : -1; // les vides en dernier, quel que soit le sens
        const c = typeof x === 'number' && typeof y === 'number' ? x - y : collator.compare(String(x), String(y));
        return sort.dir === 'asc' ? c : -c;
      })
    : rows;
  const fmt = (i: number, v: Cell) => (format ? format(i, v) : v === null || v === undefined ? '—' : String(v));

  const toggle = (i: number) =>
    setSort((s) => (s && s.column === i ? { column: i, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { column: i, dir: columns[i]?.numeric ? 'desc' : 'asc' }));

  return (
    <figure className="ch">
      {/* Boîte de défilement focalisable : sans cela, un tableau large n'est pas atteignable au clavier (WCAG 2.1.1). */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <div className="ui-table-wrap ch-table" tabIndex={0} role="region" aria-label={title}>
        <table className="ui-table">
          <caption className="sr-only">
            {title}. {summary}
          </caption>
          <thead>
            <tr>
              {columns.map((c, i) => {
                const active = sort?.column === i;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    className={c.numeric ? 'is-num' : undefined}
                    aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  >
                    <button type="button" className="ch-sort" onClick={() => toggle(i)}>
                      {c.label}
                      <span className="ch-sort-mark" aria-hidden="true">
                        {active ? <Icon name={sort.dir === 'asc' ? 'arrowUp' : 'arrowDown'} size={14} /> : null}
                      </span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, ri) => (
              <tr key={ri}>
                {columns.map((c, ci) =>
                  ci === 0 ? (
                    <th key={c.key} scope="row" className={c.numeric ? 'is-num' : undefined}>
                      {fmt(ci, r[ci])}
                    </th>
                  ) : (
                    <td key={c.key} className={c.numeric ? 'is-num' : undefined}>
                      {fmt(ci, r[ci])}
                    </td>
                  ),
                )}
              </tr>
            ))}
            {truncated ? (
              <tr className="ch-truncated">
                <td colSpan={columns.length}>
                  <Icon name="alert" size={16} /> Résultat tronqué : seules les premières lignes sont affichées.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
