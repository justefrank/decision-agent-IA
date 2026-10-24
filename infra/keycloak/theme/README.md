# Thème Keycloak (hors périmètre backend)

Les pages d'authentification (A01-A07 : connexion, OTP, mot de passe oublié, compte verrouillé…)
sont rendues par Keycloak. Leur thème est construit avec **Keycloakify** à partir des jetons de
design de la SPA ; il relève donc du frontend (`web/keycloak-theme/`, décision D1).

Intégration prévue :

1. `web/keycloak-theme` produit un `.jar` (`npx keycloakify build`).
2. Le `.jar` est monté dans le conteneur : `./keycloak/providers:/opt/keycloak/providers:ro`
   (service `keycloak` de `infra/compose.yaml`).
3. Le realm sélectionne le thème : `"loginTheme": "<nom du thème>"` dans
   `infra/keycloak/realm/decision-realm.json` (ou dans la console pour un realm déjà importé,
   `--import-realm` n'écrasant pas un realm existant).

Contraintes (SYSTEM_DESIGN §6) : aucune logique propre ni secret dans le thème ; messages neutres
(pas d'énumération de comptes : pendant un verrouillage temporaire, Keycloak affiche volontairement
« identifiant ou mot de passe invalide ») ; CSP de Keycloak conservée.
