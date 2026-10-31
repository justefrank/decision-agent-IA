import type { AssistantMessage, EvidenceStep, Fact } from '@/api/types';

/** Message dont les champs à valeur par défaut sont toujours présents (le schéma les déclare optionnels). */
export type Message = Omit<AssistantMessage, 'tables' | 'evidence' | 'facts' | 'caveats' | 'follow_up' | 'truncated' | 'certified' | 'simplified'> & {
  tables: string[];
  evidence: EvidenceStep[];
  facts: Fact[];
  caveats: string[];
  follow_up: string[];
  truncated: boolean;
  certified: boolean;
  simplified: boolean;
};

export function normalize(m: AssistantMessage): Message {
  return {
    ...m,
    tables: m.tables ?? [],
    evidence: m.evidence ?? [],
    facts: m.facts ?? [],
    caveats: m.caveats ?? [],
    follow_up: m.follow_up ?? [],
    truncated: m.truncated ?? false,
    certified: m.certified ?? false,
    simplified: m.simplified ?? false,
  };
}

/** Mentions affichées en français clair. Un code inconnu n'est pas affiché : aucun texte non validé. */
const CAVEAT_TEXT: Record<string, string> = {
  calcul_ad_hoc: 'Calcul ad hoc : ce résultat ne vient pas d’un indicateur certifié. Vérifiez-le avant de le diffuser.',
  resultat_tronque: 'Résultat tronqué : seules les premières lignes sont affichées, aucun total n’est calculé.',
  defaut_periode_applique: 'Période non précisée : la période par défaut a été appliquée.',
  defaut_region_applique: 'Sens de « région » non précisé : le sens par défaut de l’indicateur a été appliqué.',
  reponse_simplifiee: 'Réponse simplifiée : seuls les chiffres vérifiés sont affichés, sans formulation détaillée.',
  ex_aequo: 'Des valeurs sont à égalité : le classement n’est pas strict.',
  hypothese: 'Cette réponse contient une hypothèse, pas un fait établi par les données.',
};

/** `resultat_vide` et les refus ont leur propre présentation : pas de mention en plus. */
export function caveatSentences(caveats: string[]): string[] {
  return caveats.map((c) => CAVEAT_TEXT[c]).filter((s): s is string => Boolean(s));
}

export const EVIDENCE_LABEL = {
  table: 'Table',
  filtre: 'Filtre',
  periode: 'Période',
  operation: 'Opération',
} as const;

/** Texte copié : la phrase, puis la chaîne de preuve (pour qu'une réponse collée reste vérifiable). */
export function copyText(m: Message): string {
  const lines = [m.text.trim()];
  if (m.evidence.length) {
    lines.push('', ...m.evidence.map((e) => `${EVIDENCE_LABEL[e.kind]} : ${e.label}`));
  }
  const notes = caveatSentences(m.caveats);
  if (notes.length) lines.push('', ...notes);
  return lines.join('\n');
}

export const EXAMPLE_QUESTIONS = [
  'Quelle est la valeur transférée ce mois-ci ?',
  'Quelles sont les cinq régions avec le plus de transactions ?',
  'Comment évolue le taux d’échec sur les trois derniers mois ?',
  'Quelle est la répartition des revenus de frais par type de transaction ?',
  'Combien d’agents actifs à Dakar sur les 30 derniers jours ?',
] as const;

export const MAX_QUESTION = 1000;
