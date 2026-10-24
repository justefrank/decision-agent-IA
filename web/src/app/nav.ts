/** Navigation : les entrées suivent le rôle ; l'API vérifie les droits côté serveur (403 sinon). */
import type { Role } from '@/api/types';
import type { IconName } from '@/shared/ui';

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  roles: readonly Role[];
  end?: boolean;
}

const ALL: readonly Role[] = ['decideur', 'analyste', 'admin'];
const STAFF: readonly Role[] = ['analyste', 'admin'];
const ADMIN: readonly Role[] = ['admin'];

export const MAIN_NAV: NavItem[] = [
  { to: '/questions', label: 'Questions', icon: 'ask', roles: ALL },
  { to: '/indicateurs', label: 'Indicateurs', icon: 'chart', roles: ALL },
];

export const ADMIN_NAV: NavItem[] = [
  { to: '/admin', label: 'Exploitation', icon: 'gauge', roles: STAFF, end: true },
  { to: '/admin/audit', label: 'Journal d’audit', icon: 'list', roles: STAFF },
  { to: '/admin/evaluation', label: 'Évaluation', icon: 'flask', roles: STAFF },
  { to: '/admin/signalements', label: 'Signalements', icon: 'flag', roles: STAFF },
  { to: '/admin/kpi', label: 'Catalogue de KPI', icon: 'book', roles: STAFF },
  { to: '/admin/semantique', label: 'Couche sémantique', icon: 'layers', roles: STAFF },
  { to: '/admin/securite', label: 'Sécurité', icon: 'shield', roles: ADMIN },
  { to: '/admin/parametres', label: 'Paramètres', icon: 'settings', roles: ADMIN },
];

export const ROLE_LABEL: Record<Role, string> = {
  decideur: 'Décideur',
  analyste: 'Analyste',
  admin: 'Administrateur',
};
