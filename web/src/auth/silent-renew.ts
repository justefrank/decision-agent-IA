/** Page du renouvellement silencieux (iframe cachée) : transmet la réponse de Keycloak à la page parente. */
import { UserManager } from 'oidc-client-ts';

import { oidcConfig } from './config';

void new UserManager({ authority: oidcConfig.authority, client_id: oidcConfig.clientId, redirect_uri: '' })
  .signinSilentCallback()
  .catch(() => undefined);
