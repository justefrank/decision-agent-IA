import { fmtMonth } from '@/shared/format';

/** Régions du Sénégal acceptées par l'API (semantic/kpis.yaml, `regions`). */
export const REGIONS = [
  'Dakar',
  'Thiès',
  'Diourbel',
  'Kaolack',
  'Saint-Louis',
  'Ziguinchor',
  'Louga',
  'Fatick',
  'Kolda',
  'Tambacounda',
  'Kaffrine',
  'Kédougou',
  'Matam',
  'Sédhiou',
] as const;

export const MONTHS_AVAILABLE = 18;
export const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Les `count` mois se terminant à `ref` (AAAA-MM), du plus récent au plus ancien. */
export function monthsEnding(ref: string, count = MONTHS_AVAILABLE): { value: string; label: string }[] {
  const [y, m] = ref.split('-').map(Number) as [number, number];
  const out: { value: string; label: string }[] = [];
  for (let i = 0; i < count; i += 1) {
    const d = new Date(y, m - 1 - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    out.push({ value, label: cap(fmtMonth(value)) });
  }
  return out;
}
