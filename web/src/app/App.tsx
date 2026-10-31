/** Routes. Les pages du back-office sont filtrées par rôle ici, et l'API refuse de toute façon (403). */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router';

import { ApiError } from '@/api/client';
import type { Role } from '@/api/types';
import { AuthProvider } from '@/auth/AuthProvider';
import { hasRole, useAuth } from '@/auth/useAuth';
import {
  AdminAuditPage,
  AdminEvalPage,
  AdminFeedbackPage,
  AdminKpiPage,
  AdminOverviewPage,
  AdminSecurityPage,
  AdminSemanticPage,
  AdminSettingsPage,
} from '@/features/admin/AdminPages';
import {
  AccessDenied,
  LoggedOutPage,
  LoginPage,
  MfaRequiredPage,
  SessionExpiredPage,
} from '@/features/auth/AuthPages';
import { ConversationPage } from '@/features/conversation/ConversationPage';
import { DashboardPage } from '@/features/dashboard/DashboardPage';
import { LiveRegion, Skeleton } from '@/shared/ui';

import { Shell } from './Shell';

const STAFF: Role[] = ['analyste', 'admin'];
const ADMIN: Role[] = ['admin'];

function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { me } = useAuth();
  return hasRole(me?.role, roles) ? children : <AccessDenied />;
}

/** Garde de session : la page affichée dépend de l'état d'authentification. */
function Gate() {
  const { status } = useAuth();
  if (status === 'loading')
    return (
      <div style={{ padding: '3rem', display: 'grid', gap: '1rem', maxWidth: '30rem' }} aria-busy="true">
        <span className="sr-only">Chargement de la session…</span>
        <Skeleton height={36} width="50%" />
        <Skeleton height={18} />
        <Skeleton height={18} width="80%" />
      </div>
    );
  if (status === 'expired') return <SessionExpiredPage />;
  if (status === 'mfa_required') return <MfaRequiredPage />;
  if (status === 'anonymous') return <LoginPage />;
  return <Shell />;
}

const router = createBrowserRouter([
  { path: '/deconnecte', element: <LoggedOutPage /> },
  {
    path: '/',
    element: <Gate />,
    children: [
      { index: true, element: <Navigate to="/questions" replace /> },
      { path: 'connexion', element: <Navigate to="/questions" replace /> },
      { path: 'connexion/retour', element: <Navigate to="/questions" replace /> },
      { path: 'questions', element: <ConversationPage /> },
      { path: 'questions/:conversationId', element: <ConversationPage /> },
      { path: 'indicateurs', element: <DashboardPage /> },
      {
        path: 'admin',
        children: [
          { index: true, element: <RequireRole roles={STAFF}><AdminOverviewPage /></RequireRole> },
          { path: 'audit', element: <RequireRole roles={STAFF}><AdminAuditPage /></RequireRole> },
          { path: 'audit/:traceId', element: <RequireRole roles={STAFF}><AdminAuditPage /></RequireRole> },
          { path: 'evaluation', element: <RequireRole roles={STAFF}><AdminEvalPage /></RequireRole> },
          { path: 'evaluation/:runId', element: <RequireRole roles={STAFF}><AdminEvalPage /></RequireRole> },
          { path: 'signalements', element: <RequireRole roles={STAFF}><AdminFeedbackPage /></RequireRole> },
          { path: 'kpi', element: <RequireRole roles={STAFF}><AdminKpiPage /></RequireRole> },
          { path: 'semantique', element: <RequireRole roles={STAFF}><AdminSemanticPage /></RequireRole> },
          { path: 'securite', element: <RequireRole roles={ADMIN}><AdminSecurityPage /></RequireRole> },
          { path: 'parametres', element: <RequireRole roles={ADMIN}><AdminSettingsPage /></RequireRole> },
        ],
      },
      { path: '*', element: <Navigate to="/questions" replace /> },
    ],
  },
]);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // Pas de nouvel essai sur une erreur client (401, 403, 404, 422) : le message suffit.
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
        <LiveRegion />
      </AuthProvider>
    </QueryClientProvider>
  );
}
