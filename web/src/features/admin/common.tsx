import type { UseQueryResult } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { ApiError } from '@/api/client';
import { AccessDenied } from '@/features/auth/AuthPages';
import { Badge, ErrorState, Icon, Skeleton, type IconName } from '@/shared/ui';

import './admin.css';

export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

/** Chargement, 403 (même message que le garde de routes), erreur avec « Réessayer », puis le contenu. */
export function Loaded<T>({
  query,
  rows = 4,
  children,
}: {
  query: UseQueryResult<T>;
  rows?: number;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending)
    return (
      <div className="adm-loading" aria-busy="true">
        <span className="sr-only">Chargement…</span>
        {Array.from({ length: rows }, (_, i) => (
          <Skeleton key={i} height={22} width={i % 2 ? '70%' : '100%'} />
        ))}
      </div>
    );
  if (query.isError) {
    if (isForbidden(query.error)) return <AccessDenied />;
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  return <>{children(query.data)}</>;
}

/** Page à garde de 403 : si la requête principale répond 403, tout le contenu est remplacé. */
export function Section({
  title,
  note,
  children,
  id,
}: {
  title: string;
  note?: ReactNode;
  children: ReactNode;
  id: string;
}) {
  return (
    <section className="adm-section" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {note ? <p className="adm-note">{note}</p> : null}
      {children}
    </section>
  );
}

/** Une ligne de relevé : libellé, pointillés, valeur. */
export function Line({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="adm-line">
      <dt>
        {label}
        {hint ? <span className="adm-hint">{hint}</span> : null}
      </dt>
      <dd className="num">{value}</dd>
    </div>
  );
}

export function Ledger({ children, label }: { children: ReactNode; label: string }) {
  return (
    <dl className="adm-ledger" aria-label={label}>
      {children}
    </dl>
  );
}

const MARK: Record<'ok' | 'bad' | 'warn', { icon: IconName; tone: 'ok' | 'bad' | 'warn' }> = {
  ok: { icon: 'check', tone: 'ok' },
  bad: { icon: 'close', tone: 'bad' },
  warn: { icon: 'alert', tone: 'warn' },
};

/** Statut : toujours icône + texte, jamais la couleur seule. */
export function Mark({ kind, children }: { kind: 'ok' | 'bad' | 'warn'; children: ReactNode }) {
  const m = MARK[kind];
  return (
    <Badge tone={m.tone}>
      <Icon name={m.icon} size={14} />
      {children}
    </Badge>
  );
}

export function Pager({
  page,
  pageSize,
  total,
  onPage,
  noun,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
  noun: string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav className="adm-pager" aria-label="Pagination">
      <p className="num" aria-live="polite">
        {total} {noun} · page {page} sur {pages}
      </p>
      <div>
        <button type="button" className="ui-btn" data-variant="secondary" data-size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Page précédente
        </button>
        <button type="button" className="ui-btn" data-variant="secondary" data-size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Page suivante
        </button>
      </div>
    </nav>
  );
}

export const shortId = (s: string | null | undefined, n = 8): string => (s ? s.slice(0, n) : '—');

export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(v)}\u202f$`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return '—';
  return `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v * 100)}\u202f%`;
}
