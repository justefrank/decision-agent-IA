# Design System

Version 4 : **l'interface réelle (`web/`) remplace la maquette de 45 écrans**, que l'auteur a jugée trop éloignée de l'usage (« trop bizarre »). Elle ne garde que deux choses de la maquette : le **logo** et les **jetons de design** (§2). Complète [SRS.md](../SRS.md) (ENF7, ENF12) et [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md). Cible : l'application React + Vite (`web/`), dont les routes `/admin`.

## 1. Direction : le relevé

Le produit répond avec des chiffres qu'on doit pouvoir vérifier. Le vocabulaire visuel est celui d'un **relevé de compte** : sobre, aligné à gauche, lisible d'un coup d'œil, sans décor.

| Choix | Décision | Pourquoi |
|---|---|---|
| Palette | Bleus de la maquette (§2) : **marine** pour le texte, bleu d'action `#2A5FD4`, cyan du logo en surface ; **jaune soleil** comme unique signal : le soulignement du chiffre clé | Fidélité à la couleur de marque, un seul accent qui désigne ce qui compte |
| Réponse = reçu | Le chiffre clé en grand (Bricolage Grotesque), souligné de jaune, puis la phrase, puis les lignes de preuve à points de conduite : Table, Filtre, Période, Opération. Bord bas perforé (CSS), **nulle part ailleurs** | Rend ENF6 visible sans exposer le SQL au décideur ; une seule signature, pas un décor |
| Tableau de bord = relevé | Une ligne par indicateur : valeur, période précédente, écart signé, barre de comparaison dans la cellule. Pas de grille de cartes identiques | Se lit comme un relevé, se compare d'un regard |
| Back-office = tableaux | Listes à filtres, tiroirs de détail, lignes libellé/valeur séparées par des filets ; le score d'évaluation est le seul « reçu » (chiffre clé souligné + intervalle) | Un outil d'exploitation, pas une vitrine |
| Questions | Chaque question sert de titre à sa réponse ; pas de bulles de messagerie. Précision, refus et erreur : un filet à gauche, sans carte | Un fil de questions-réponses, pas une discussion |
| Mouvement | Un seul : le chiffre clé d'une réponse qui apparaît. Tout respecte `prefers-reduced-motion` | Le mouvement dit « voici le résultat », pas autre chose |
| Hiérarchie | Chiffres clés très grands, texte courant sobre, code en mono réservé au SQL et aux identifiants | Contraste d'échelle fort |
| Écarts | Hausse/baisse portées par une icône, le signe + / − et un texte masqué pour les lecteurs d'écran ; la couleur n'est jamais seule | WCAG 2.2 AA |
| Marque | **Logo repris de la maquette** (pastille cyan avec la mascotte et le mot « wave », `web/src/app/Logo.tsx`) à la demande de l'auteur ; données synthétiques, projet académique. Les bleus des jetons ont été mesurés sur des captures de l'auteur, pas sur un kit de marque officiel | À confirmer avec le kit de Wave si le projet leur est présenté (§8) |
| Thèmes | Clair et sombre conçus séparément ; « système » par défaut, choix mémorisé par navigateur | Pas d'inversion mécanique |
| Interdits | Cartes identiques avec la même ombre, dégradés décoratifs, étiquettes en majuscules espacées, emoji, numérotation sans séquence réelle, entrées animées sur chaque section | Signes d'un rendu générique |

## 2. Jetons (variables CSS posées sur la racine de chaque composant)

```
clair  = { ground:#F2F7FC card:#FFFFFF panel:#E4EEF8 line:#CFDDEC line2:#6F8CAA ink:#0B2545 soft:#41607F
           brand:#2D5ECE brandInk:#EAF4FD brandSoft:#E3EEFF primary:#2A5FD4 primaryInk:#FFFFFF sky:#1DC8FE
           saff:#FFC83D pos:#0C7356 neg:#B83A55 chip:#E1EBFD c1:#2F6FED c2:#FFC83D c3:#0E8C86 c4:#C2415D }
sombre = { ground:#071A33 card:#0E2A4D panel:#0A2140 line:#1F3F66 line2:#6E93BD ink:#EAF4FD soft:#9FC0E0
           brand:#17458F brandInk:#EAF4FD brandSoft:#B9D0FA primary:#6FA3FF primaryInk:#071A33 sky:#3DD3FF
           saff:#FFD25E pos:#7FE0BC neg:#FF8FA5 chip:#12365F c1:#6FA3FF c2:#FFD25E c3:#4FD1C5 c4:#FF8FA5 }
```

Dans le CSS (`web/src/styles/tokens.css`) les jetons sont en kebab-case : `brandInk` devient `--brand-ink`, `brandSoft` `--brand-soft`, `primaryInk` `--primary-ink`, `saff` `--saff`. `saff` désigne le jaune soleil (nom conservé dans le code). Pour changer de bleu de marque, on remplace `primary`, `sky` et `brand` à un seul endroit par composant racine.

Règles : jamais de couleur en dur dans un composant (sauf `#0B2545` sur fond jaune) ; `line` pour les séparateurs, **`line2` pour toute bordure de composant interactif** (≥ 3:1 dans les deux thèmes) ; texte sur fond jaune ou ciel toujours en `#0B2545`. Contrastes calculés (formule WCAG) : texte `ink` et `soft` ≥ 4,5:1 sur `ground`, `card` et `panel` ; blanc sur `primary` ≥ 4,5:1 ; `brandSoft` sur `brand` ≥ 4,5:1 ; `line2` sur `card` ≥ 3:1. Le cyan du logo (`#1DC8FE`) ne porte pas de texte blanc (1,9:1) : il sert aux surfaces et aux accents, avec du texte marine (7,9:1). Le bleu d'action exact `#2F6FED` donne 4,55:1 avec du blanc mais seulement 3,8 à 4,2:1 en texte sur fond teinté : les contrôles, liens et contours utilisent `primary` (`#2A5FD4`), et `#2F6FED` reste réservé aux aplats (`c1` : barres de graphique). Tous les couples ont été recalculés avec les valeurs ci-dessus : zéro échec dans les deux thèmes.

### Photographies

Les six photographies de la maquette (Dakar, Gorée, marché, Saint-Louis, en bichromie) ne sont **pas reprises** : l'interface réelle n'a pas de page d'accueil illustrée, et un outil de décision gagne à rester sans image. La section est conservée dans l'historique Git (version 3) si une page publique en avait besoin.

## 3. Typographie

| Rôle | Police | Usage |
|---|---|---|
| Titres et chiffres | Bricolage Grotesque (300 à 800, axe optique) | Chiffre clé (jusqu'à 150 px, graisse 300), titres de page, questions |
| Interface | Instrument Sans (400, 500, 600) | Texte courant, boutons, tableaux |
| Code | JetBrains Mono (400, 500) | SQL, identifiants, trace_id, diff YAML |

Chiffres tabulaires pour tout nombre. Montants en FCFA, espace insécable, virgule décimale. Pas de majuscules espacées en étiquettes, pas de mot isolé accentué dans un titre.

## 4. Composants

Composants partagés dans `web/src/shared/ui` (Radix pour les dialogues et tiroirs), graphiques dans `web/src/shared/charts`, styles par fonctionnalité.

| Famille | Composants | Remarques |
|---|---|---|
| Navigation | Barre latérale par groupes (Analyse, Administration) filtrée par rôle ; tiroir sur mobile avec bouton de menu | `aria-current="page"`, lien d'évitement, ouverture propre à la page |
| Saisie | Zone de question (Entrée envoie, Maj+Entrée saute une ligne, compteur sur 1 000, bouton Arrêter), `Field` avec aide et erreur reliées par `aria-describedby`, segments, boutons | Cibles ≥ 44 px, focus visible |
| Réponse | **Reçu** : chiffre clé, phrase, lignes de preuve, sceau « calcul certifié » ou « calcul ad hoc » (icône + texte), actions (copier, signaler), volet « Voir le calcul » (analyste), questions de suivi, étapes de calcul annoncées | Le graphique est choisi par le code, jamais par le modèle |
| Graphiques | Courbe (période précédente en pointillés), barres horizontales étiquetées (hachurées pour comparer), anneau (hachures au-delà de 4 parts), tableau trié (`aria-sort`), chiffre clé | SVG maison ; résumé textuel et équivalent tabulaire sur chacun |
| États | Squelettes, vide (avec la prochaine action), erreur (avec Réessayer), précision demandée, refus, résultat vide, 429, 503, session expirée, accès réservé | Rendus par `EmptyState` / `ErrorState` ; erreurs annoncées |
| Tableaux | `ui-table` avec légende masquée, défilement horizontal en boîte, pagination à départage stable | |
| Détail | Tiroir latéral (focus piégé, Échap, retour au déclencheur) et dialogue de confirmation | Radix Dialog |
| Relevé | Lignes libellé / valeur ou indicateur / valeur / écart, barre de comparaison dans la cellule | Remplace les cartes de statistiques |
| Analyse | Phrase d'accroche (faits seulement), 3 constats avec étiquette, niveau de confiance en toutes lettres, **hypothèse** en bloc pointillé avec le mot « Hypothèse » | Sources cliquables : la ligne citée du relevé est mise en évidence |

## 5. Écrans (routes)

| Zone | Route | Rôles | Contenu |
|---|---|---|---|
| Hors session | `/connexion` (page de connexion), `/deconnecte`, session expirée, vérification en deux étapes à refaire | tous | Connexion Keycloak (PKCE) ; en développement, trois boutons de rôle |
| Questions | `/questions`, `/questions/:id` | tous | Accueil, fil de questions-réponses, historique (panneau ou tiroir), signalement |
| Indicateurs | `/indicateurs?periode=&region=` | tous | Relevé des 6 indicateurs, analyse de l'agent |
| Exploitation | `/admin` | analyste, admin | Requêtes, latence face aux cibles O2, coût, jetons, cache, garde SQL, santé |
| Journal d'audit | `/admin/audit`, `/admin/audit/:trace` | analyste, admin | Tableau filtrable, détail en tiroir (lecture journalisée), export CSV |
| Évaluation | `/admin/evaluation`, `/admin/evaluation/:run` | analyste, admin | Scores avec Wilson, phrase honnête, catégories, ablations, coût |
| Signalements | `/admin/signalements` | analyste, admin | Traiter, rejeter (motif), promouvoir vers le jeu de dev |
| KPI, couche sémantique | `/admin/kpi`, `/admin/semantique` | analyste, admin | Lecture seule ; modification par demande de modification (PR Git) |
| Sécurité, paramètres | `/admin/securite`, `/admin/parametres` | admin | Blocages du garde, test de droits de `agent_ro`, paramètres en lecture |

Un rôle insuffisant affiche « Accès réservé » ; l'API refuse de toute façon (403). La maquette de 45 écrans n'est plus la référence : ses écrans de récupération d'accès (mot de passe oublié, compte verrouillé…) relèvent des pages Keycloak, thémables plus tard (`web/keycloak-theme/`).

## 6. Accessibilité (WCAG 2.2 AA)

Vérifiée par audit d'un agent d'accessibilité sur les 45 écrans ; les points bloquants ont été corrigés, et les corrections restent à vérifier dans un navigateur.

- Focus visible partout ; **tiroirs et dialogues** : le focus entre à l'ouverture, boucle avec Tab, revient au déclencheur à la fermeture, Échap ferme, un seul `aria-modal` actif.
- Menus d'actions : flèches, Début, Fin, Échap ; éléments inactifs en `aria-disabled`.
- Onglets en `tablist` avec flèches ; interrupteurs en `role="switch"` avec l'état écrit à côté.
- Zones dynamiques : conteneur `role="status"` **permanent** dans lequel on injecte le texte ; une seule alerte à la fois ; pas d'annonce à chaque frappe.
- Minuteurs : redirection ≥ 20 s avec bouton « Rester sur cette page » ; compteur en direct avec bouton pause ; avertissement 20 s avant expiration de session.
- La couleur ne porte jamais seule le sens (icône, signe `+`/`−` ou texte).
- Mouvement réduit : animations et transitions coupées, frappe progressive de l'analyse remplacée par le texte entier.
- Reflow de 320 à 1440 px.

## 7. Implémentation

`web/` : React 19, Vite 8, TypeScript strict, React Router 7, TanStack Query, Radix (dialogues), `oidc-client-ts` (PKCE, jeton en mémoire, renouvellement silencieux). Organisation par fonctionnalités (`features/conversation`, `dashboard`, `admin`, `auth`), composants partagés, polices installées en local (CSP stricte : aucun appel à un CDN, aucun script en ligne). Types TypeScript générés depuis l'OpenAPI de l'API et les contrats Python (`npm run api-types`).

Tests : Vitest, Testing Library et MSW (comportement observable), Playwright de bout en bout avec l'API simulée, axe-core (WCAG 2.2 AA, deux thèmes, 1280 et 390 px). Budget : JS ≤ 300 kB gzippé (aujourd'hui 148 kB), LCP < 2,5 s, CLS < 0,1, INP < 200 ms. Commandes : `make web-check` (types, lint, tests), `make web-dev`, `make web-build`.

## 8. À valider

1. **Logo et marque** : le logo vient de la maquette de l'auteur ; les bleus ont été mesurés sur des captures, pas sur un kit officiel. À confirmer avec le kit de Wave si le projet leur est présenté.
2. **Pages d'authentification** : aujourd'hui les pages Keycloak par défaut ; un thème Keycloakify aux jetons du produit reste à faire (`infra/keycloak/theme/README.md`).
3. **Rendu réel** avec une vraie clé Claude : les réponses de l'agent ont été simulées dans les captures et les tests.
4. **Réponse signalée dans le back-office** : `GET /admin/feedback` ne renvoie pas la réponse ni la chaîne de preuve ; le détail renvoie à la trace d'audit.
