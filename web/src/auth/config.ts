/** Configuration de l'authentification, lue au build (variables VITE_*). */
export type AuthMode = 'oidc' | 'dev';

export const authMode: AuthMode = import.meta.env.VITE_AUTH_MODE === 'dev' ? 'dev' : 'oidc';

export const oidcConfig = {
  // Keycloak est servi par le proxy sur la même origine (/auth) : pas de CORS.
  authority: import.meta.env.VITE_OIDC_AUTHORITY ?? `${window.location.origin}/auth/realms/decision`,
  clientId: import.meta.env.VITE_OIDC_CLIENT_ID ?? 'decision-web',
  redirectPath: '/connexion/retour',
  silentPath: '/silent-renew.html',
  logoutPath: '/deconnecte',
};

/** Délai d'avertissement avant la fin de session (WCAG 2.2.1 : au moins 20 s pour prolonger). */
export const SESSION_WARNING_S = 60;
