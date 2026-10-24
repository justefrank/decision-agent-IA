/**
 * Pages hors session : connexion, déconnexion, session expirée, MFA à refaire, accès refusé.
 * La saisie du mot de passe et du code OTP se fait sur les pages Keycloak (jamais dans l'application).
 */
import type { ReactNode } from 'react';
import { Link } from 'react-router';

import type { Role } from '@/api/types';
import { Logo } from '@/app/Logo';
import { ROLE_LABEL } from '@/app/nav';
import { useAuth } from '@/auth/useAuth';
import { Button } from '@/shared/ui';

import './auth.css';

function AuthFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="auth" id="contenu">
      <div className="auth-panel">
        <Logo />
        <h1>{title}</h1>
        {children}
      </div>
    </main>
  );
}

export function LoginPage() {
  const { mode, login, error, status } = useAuth();
  const busy = status === 'loading';
  return (
    <AuthFrame title="Interrogez vos transactions en français">
      <p className="auth-lead">
        Posez une question sur les volumes, les frais, les clients ou les agents. Chaque chiffre est
        accompagné de son calcul : table, filtre, période.
      </p>
      {mode === 'oidc' ? (
        <Button onClick={() => void login()} disabled={busy}>
          Se connecter
        </Button>
      ) : (
        <div className="auth-roles">
          <p className="auth-note">Mode développement : jetons signés localement, sans Keycloak.</p>
          {(['decideur', 'analyste', 'admin'] as Role[]).map((r) => (
            <Button key={r} variant={r === 'decideur' ? 'primary' : 'secondary'} onClick={() => void login(r)}>
              Entrer comme {ROLE_LABEL[r].toLowerCase()}
            </Button>
          ))}
        </div>
      )}
      {error ? (
        <p className="auth-error" role="alert">
          {error}
        </p>
      ) : null}
    </AuthFrame>
  );
}

export function LoggedOutPage() {
  return (
    <AuthFrame title="Vous êtes déconnecté">
      <p className="auth-lead">Votre session est fermée sur cet appareil.</p>
      <Link className="ui-btn" data-variant="primary" to="/connexion">
        Se reconnecter
      </Link>
    </AuthFrame>
  );
}

export function SessionExpiredPage() {
  const { login } = useAuth();
  return (
    <AuthFrame title="Votre session a expiré">
      <p className="auth-lead">
        Reconnectez-vous pour continuer. Vos conversations sont enregistrées : vous les retrouverez dans
        l’historique.
      </p>
      <Button onClick={() => void login()}>Se reconnecter</Button>
    </AuthFrame>
  );
}

export function MfaRequiredPage() {
  const { login } = useAuth();
  return (
    <AuthFrame title="Vérification en deux étapes requise">
      <p className="auth-lead">
        Votre rôle exige un code de vérification à chaque connexion. Reconnectez-vous et saisissez le code
        de votre application d’authentification.
      </p>
      <Button onClick={() => void login()}>Se reconnecter avec le code</Button>
    </AuthFrame>
  );
}

export function AccessDenied() {
  return (
    <section className="ui-state" aria-labelledby="refus-titre">
      <h1 id="refus-titre">Accès réservé</h1>
      <p>
        Cette page est réservée à un autre rôle. Si vous pensez en avoir besoin, demandez l’accès à un
        administrateur.
      </p>
      <Link to="/questions">Revenir aux questions</Link>
    </section>
  );
}
