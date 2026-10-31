import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { BarChart, DataTable, DonutChart, LineChart } from '.';

const f = (v: number) => `${v} FCFA`;

describe('LineChart', () => {
  const series = [
    { name: 'Septembre', points: [{ x: '2026-08', y: 10 }, { x: '2026-09', y: 14 }] },
    { name: 'Août', tone: 'previous' as const, points: [{ x: '2026-08', y: 9 }, { x: '2026-09', y: null }] },
  ];
  it('a un titre, un résumé et un équivalent tabulaire', async () => {
    render(<LineChart title="Valeur" summary="Hausse de 10 à 14." series={series} formatY={f} />);
    expect(screen.getByRole('img', { name: 'Valeur' })).toHaveAccessibleDescription('Hausse de 10 à 14.');
    await userEvent.click(screen.getByText('Afficher les valeurs en tableau'));
    const table = screen.getByRole('table', { name: 'Valeur' });
    expect(within(table).getByRole('columnheader', { name: 'Août' })).toBeInTheDocument();
    expect(within(table).getAllByText('—')).toHaveLength(1); // valeur absente : jamais un zéro inventé
  });
  it('la légende donne la dernière valeur de chaque série', () => {
    render(<LineChart title="Valeur" summary="s" series={series} formatY={f} />);
    const legend = within(screen.getByRole('list'));
    expect(legend.getByText('14 FCFA')).toBeInTheDocument();
    expect(legend.getByText('9 FCFA')).toBeInTheDocument();
  });
});

describe('BarChart', () => {
  it('trie les barres de la plus grande à la plus petite avec valeurs écrites', async () => {
    render(
      <BarChart title="Régions" summary="s" format={f} items={[{ label: 'Thiès', value: 5 }, { label: 'Dakar', value: 20 }, { label: 'Kaolack', value: 1 }]} />,
    );
    await userEvent.click(screen.getByText('Afficher les valeurs en tableau'));
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1);
    expect(rows.map((r) => within(r).getAllByRole('cell', { hidden: true })[0]?.textContent ?? r.textContent)).toEqual([
      '20 FCFA',
      '5 FCFA',
      '1 FCFA',
    ]);
    expect(screen.getAllByText('20 FCFA').length).toBeGreaterThan(0);
  });
});

describe('DonutChart', () => {
  it('affiche part et valeur dans la légende', () => {
    render(<DonutChart title="Types" summary="s" format={f} parts={[{ label: 'Retrait', value: 75 }, { label: 'Transfert', value: 25 }]} />);
    const legend = within(screen.getByRole('list'));
    expect(legend.getByText('Retrait')).toBeInTheDocument();
    expect(legend.getByText(/75,0\s%/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Types' })).toBeInTheDocument();
  });
});

describe('DataTable', () => {
  const columns = [{ key: 'a', label: 'Agent' }, { key: 'v', label: 'Valeur', numeric: true }];
  const rows = [['B', 2], ['A', 30], ['C', null]];
  it('trie au clic avec aria-sort et place les vides en dernier', async () => {
    render(<DataTable title="Agents" summary="s" columns={columns} rows={rows} />);
    const th = screen.getByRole('columnheader', { name: 'Valeur' });
    expect(th).toHaveAttribute('aria-sort', 'none');
    await userEvent.click(within(th).getByRole('button'));
    expect(th).toHaveAttribute('aria-sort', 'descending');
    const names = () => screen.getAllByRole('rowheader').map((r) => r.textContent);
    expect(names()).toEqual(['A', 'B', 'C']);
    await userEvent.click(within(th).getByRole('button'));
    expect(th).toHaveAttribute('aria-sort', 'ascending');
    expect(names()).toEqual(['B', 'A', 'C']);
  });
  it('signale un résultat tronqué', () => {
    render(<DataTable title="Agents" summary="s" columns={columns} rows={rows} truncated />);
    expect(screen.getByText(/Résultat tronqué/)).toBeInTheDocument();
  });
});
