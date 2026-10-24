import { useContext } from 'react';

import type { Role } from '@/api/types';

import { AuthContext, type AuthState } from './AuthProvider';

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth doit être utilisé sous <AuthProvider>.');
  return ctx;
}

/** Le rôle donne accès à la page : la vérification réelle est faite par l'API (403). */
export function hasRole(role: Role | undefined, allowed: readonly Role[]): boolean {
  return !!role && allowed.includes(role);
}
