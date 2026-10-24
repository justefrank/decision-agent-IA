/**
 * Formats français : espace fine insécable comme séparateur de milliers, virgule décimale, FCFA.
 * Les chiffres des réponses de l'agent arrivent déjà rendus par l'API (`Fact.rendered`) : ces fonctions
 * servent aux tableaux, axes de graphiques et au back-office.
 */
const NNBSP = ' ';

const intFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
const decFmt = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1, minimumFractionDigits: 1 });

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return intFmt.format(v);
}

/** Montant en FCFA ; au-delà du million, 3 chiffres significatifs (« 1,23 milliard FCFA »). */
export function fmtXof(v: number | null | undefined, { compact = false } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  if (compact && a >= 1e9) return `${sig(v / 1e9)} ${a >= 2e9 ? 'milliards' : 'milliard'} FCFA`;
  if (compact && a >= 1e6) return `${sig(v / 1e6)} ${a >= 2e6 ? 'millions' : 'million'} FCFA`;
  return `${intFmt.format(v)}${NNBSP}FCFA`;
}

function sig(v: number): string {
  return new Intl.NumberFormat('fr-FR', { maximumSignificantDigits: 3 }).format(v);
}

/** Ratio (0,062) en pourcentage (« 6,2 % »). */
export function fmtRatio(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${decFmt.format(v * 100)}${NNBSP}%`;
}

/** Variation signée en % (« +4,3 % », « −2,1 % ») ; le signe porte le sens, pas seulement la couleur. */
export function fmtDeltaPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const s = decFmt.format(Math.abs(v));
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${s}${NNBSP}%`;
}

export function fmtByUnit(v: unknown, unit: string | null | undefined): string {
  if (typeof v !== 'number') return v === null || v === undefined ? '—' : String(v);
  if (unit === 'xof') return fmtXof(v);
  if (unit === 'ratio') return fmtRatio(v);
  if (unit === 'pct') return `${decFmt.format(v)}${NNBSP}%`;
  if (unit === 'pp') return `${decFmt.format(v)}${NNBSP}pts`;
  if (unit === 'count') return fmtInt(v);
  return Number.isInteger(v) ? fmtInt(v) : decFmt.format(v);
}

const dateFmt = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });
const dateTimeFmt = new Intl.DateTimeFormat('fr-FR', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
});
const monthFmt = new Intl.DateTimeFormat('fr-FR', { month: 'long', year: 'numeric' });

export function fmtDate(iso: string | null | undefined): string {
  return iso ? dateFmt.format(new Date(iso)) : '—';
}

export function fmtDateTime(iso: string | null | undefined): string {
  return iso ? dateTimeFmt.format(new Date(iso)) : '—';
}

export function fmtMonth(isoMonth: string): string {
  const [y, m] = isoMonth.split('-').map(Number);
  return monthFmt.format(new Date(y!, (m ?? 1) - 1, 1));
}

/** Durée en ms lisible (« 840 ms », « 12,4 s »). */
export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  return ms < 1000 ? `${Math.round(ms)}${NNBSP}ms` : `${decFmt.format(ms / 1000)}${NNBSP}s`;
}
