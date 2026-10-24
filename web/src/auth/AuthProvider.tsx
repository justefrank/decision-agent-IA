/**
 * Authentification : Keycloak (Authorization Code + PKCE, jeton en mémoire, renouvellement silencieux)
 * ou jetons de développement (VITE_AUTH_MODE=dev, signés par la CLI de l'API via le serveur Vite).
 * Le profil et les rôles viennent de GET /api/me : c'est l'API qui fait foi, la navigation ne fait que suivre.
 */
import { InMemoryWebStorage, UserManager, WebStorageStateStore } from 'oidc-client-ts';
import { createContext, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { ApiError, api, onUnauthorized, setTokenProvider } from '@/api/client';
import type { Me, Role } from '@/api/types';

import { authMode, oidcConfig, SESSION_WARNING_S } from './config';

export type AuthStatus = 'loading' | 'anonymous' | 'authenticated' | 'expired' | 'mfa_required';

export interface AuthState {
  status: AuthStatus;
  mode: typeof authMode;
  me: Me | null;
  /** Secondes restantes avant la fin de session quand un avertissement est affiché, sinon null. */
  expiresIn: number | null;
  login: (role?: Role) => Promise<void>;
  logout: () => Promise<void>;
  /** Prolonge la session (nouveau jeton) ; utilisé par l'avertissement d'expiration. */
  extend: () => Promise<void>;
  /** Erreur de connexion à afficher sur la page de connexion. */
  error: string | null;
}

export const AuthContext = createContext<AuthState | null>(null);

function jwtExp(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/')));
    return typeof payload.exp === 'number' ? payload.exp : null;
  } catch {
    return null;
  }
}

/**
 * Mode développement uniquement : le jeton survit au rechargement de page (sessionStorage de l'onglet).
 * En production (Keycloak), les jetons restent en mémoire et la session est reprise par renouvellement silencieux.
 */
const DEV_KEY = 'decision.devToken';
function readDevToken(): { token: string; role: Role } | null {
  if (authMode !== 'dev') return null;
  try {
    const raw = window.sessionStorage.getItem(DEV_KEY);
    return raw ? (JSON.parse(raw) as { token: string; role: Role }) : null;
  } catch {
    return null;
  }
}
function writeDevToken(v: { token: string; role: Role } | null): void {
  try {
    if (v) window.sessionStorage.setItem(DEV_KEY, JSON.stringify(v));
    else window.sessionStorage.removeItem(DEV_KEY);
  } catch {
    /* stockage indisponible : reconnexion au rechargement */
  }
}

let manager: UserManager | null = null;
export function oidcManager(): UserManager {
  if (!manager) {
    const origin = window.location.origin;
    manager = new UserManager({
      authority: oidcConfig.authority,
      client_id: oidcConfig.clientId,
      redirect_uri: origin + oidcConfig.redirectPath,
      silent_redirect_uri: origin + oidcConfig.silentPath,
      post_logout_redirect_uri: origin + oidcConfig.logoutPath,
      response_type: 'code',
      scope: 'openid',
      // Jetons en mémoire seulement (pas de localStorage) ; l'état PKCE reste en sessionStorage le temps
      // de la redirection.
      userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
      automaticSilentRenew: true,
      accessTokenExpiringNotificationTimeInSeconds: SESSION_WARNING_S,
    });
  }
  return manager;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(() =>
    authMode === 'dev' && !readDevToken() ? 'anonymous' : 'loading',
  );
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expiresIn, setExpiresIn] = useState<number | null>(null);
  const token = useRef<string | null>(readDevToken()?.token ?? null);
  const devRole = useRef<Role | null>(readDevToken()?.role ?? null);

  useEffect(() => {
    setTokenProvider(async () => {
      if (authMode === 'oidc') {
        const user = await oidcManager().getUser();
        return user && !user.expired ? user.access_token : null;
      }
      return token.current;
    });
    return onUnauthorized(() => setStatus((s) => (s === 'authenticated' ? 'expired' : s)));
  }, []);

  const loadMe = useCallback(async () => {
    try {
      const profile = await api<Me>('/me');
      setMe(profile);
      setStatus('authenticated');
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.code === 'mfa_required') {
        setStatus('mfa_required');
        return;
      }
      setStatus('anonymous');
      setError(e instanceof ApiError ? e.message : 'Connexion impossible.');
    }
  }, []);

  // Démarrage : retour de Keycloak, ou reprise silencieuse d'une session SSO existante.
  useEffect(() => {
    if (authMode === 'dev') {
      if (token.current) void loadMe(); // rechargement de page : reprise du jeton de développement
      return;
    }
    const mgr = oidcManager();
    const run = async () => {
      try {
        if (window.location.pathname === oidcConfig.redirectPath) {
          const user = await mgr.signinRedirectCallback();
          const target = typeof user.state === 'string' ? user.state : '/';
          window.history.replaceState(null, '', target);
        } else if (!(await mgr.getUser())) {
          await mgr.signinSilent().catch(() => null);
        }
        if (await mgr.getUser()) await loadMe();
        else setStatus('anonymous');
      } catch {
        setStatus('anonymous');
        setError('La connexion a échoué. Réessayez.');
      }
    };
    void run();
    const onExpiring = () => setExpiresIn(SESSION_WARNING_S);
    const onRenewError = () => setStatus((s) => (s === 'authenticated' ? 'expired' : s));
    const onLoaded = () => setExpiresIn(null);
    mgr.events.addAccessTokenExpiring(onExpiring);
    mgr.events.addSilentRenewError(onRenewError);
    mgr.events.addUserLoaded(onLoaded);
    return () => {
      mgr.events.removeAccessTokenExpiring(onExpiring);
      mgr.events.removeSilentRenewError(onRenewError);
      mgr.events.removeUserLoaded(onLoaded);
    };
  }, [loadMe]);

  // Jetons de développement : avertissement avant expiration, compté à partir du claim exp.
  useEffect(() => {
    if (authMode !== 'dev' || status !== 'authenticated' || !token.current) return;
    const exp = jwtExp(token.current);
    if (!exp) return;
    const tick = () => {
      const left = Math.round(exp - Date.now() / 1000);
      if (left <= 0) {
        setExpiresIn(null);
        setStatus('expired');
      } else setExpiresIn(left <= SESSION_WARNING_S ? left : null);
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [status, me]);

  const fetchDevToken = useCallback(async (role: Role) => {
    const res = await fetch(`/__dev/token?role=${role}`, { cache: 'no-store' });
    if (!res.ok) throw new Error((await res.text()) || 'Jeton de développement indisponible.');
    token.current = (await res.text()).trim();
    devRole.current = role;
    writeDevToken({ token: token.current, role });
  }, []);

  const login = useCallback(
    async (role?: Role) => {
      setError(null);
      if (authMode === 'dev') {
        try {
          await fetchDevToken(role ?? 'decideur');
          await loadMe();
        } catch (e) {
          setError((e as Error).message);
        }
        return;
      }
      const target = window.location.pathname.startsWith('/connexion') ? '/' : window.location.pathname;
      // prompt=login après un enrôlement OTP : le jeton doit porter amr=otp (exigé pour analyste et admin).
      await oidcManager().signinRedirect({
        state: target,
        ...(status === 'mfa_required' ? { prompt: 'login' } : {}),
      });
    },
    [fetchDevToken, loadMe, status],
  );

  const logout = useCallback(async () => {
    setMe(null);
    setExpiresIn(null);
    if (authMode === 'dev') {
      token.current = null;
      writeDevToken(null);
      setStatus('anonymous');
      window.history.pushState(null, '', oidcConfig.logoutPath);
      window.dispatchEvent(new PopStateEvent('popstate'));
      return;
    }
    await oidcManager().signoutRedirect();
  }, []);

  const extend = useCallback(async () => {
    if (authMode === 'dev') {
      if (devRole.current) await fetchDevToken(devRole.current);
      setExpiresIn(null);
      setStatus('authenticated');
      return;
    }
    try {
      await oidcManager().signinSilent();
      setExpiresIn(null);
    } catch {
      setStatus('expired');
    }
  }, [fetchDevToken]);

  const value = useMemo<AuthState>(
    () => ({ status, mode: authMode, me, expiresIn, login, logout, extend, error }),
    [status, me, expiresIn, login, logout, extend, error],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
