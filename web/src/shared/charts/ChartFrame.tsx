import { useId, type ReactNode } from 'react';

/**
 * Cadre commun des graphiques : titre visible, résumé textuel pour les lecteurs d'écran, et l'équivalent
 * tabulaire dans un `<details>` (disponible pour tout le monde, pas seulement au lecteur d'écran).
 */
export function ChartFrame({
  title,
  summary,
  children,
  legend,
  valuesTable,
}: {
  title: string;
  summary: string;
  children: (ids: { describedBy: string; titleId: string }) => ReactNode;
  legend?: ReactNode;
  valuesTable?: ReactNode;
}) {
  const id = useId();
  const titleId = `${id}-t`;
  const describedBy = `${id}-s`;
  return (
    <figure className="ch" aria-labelledby={titleId}>
      <figcaption id={titleId} className="ch-title">
        {title}
      </figcaption>
      <p id={describedBy} className="sr-only">
        {summary}
      </p>
      {legend}
      {children({ describedBy, titleId })}
      {valuesTable ? (
        <details className="ch-values">
          <summary>Afficher les valeurs en tableau</summary>
          {valuesTable}
        </details>
      ) : null}
    </figure>
  );
}

export const SERIES_COLORS = ['var(--c1)', 'var(--c3)', 'var(--c4)', 'var(--c2)'] as const;
