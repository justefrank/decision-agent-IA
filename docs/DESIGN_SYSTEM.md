# Design System

Version 2, alignée sur la maquette interactive (45 écrans). Complète [SRS.md](../SRS.md) (ENF7, ENF12) et [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md). Cible : l'application React + Vite (`web/`), dont les routes `/admin`.

Maquette de référence : « Maquette — Agent décisionnel », artefact privé de l'auteur (45 écrans interactifs, composants sources en bas du canvas).

## 1. Direction

**Indigo profond, craie froide, safran.** Le produit est un outil de décision : le chiffre est le héros, la phrase qui l'entoure donne le sens, la **chaîne de preuve** montre d'où il vient. Le SQL reste en retrait et n'est visible que pour l'analyste.

| Choix | Décision | Pourquoi |
|---|---|---|
| Palette | Indigo (teinture de tissu), craie froide, **un seul signal : le safran** | Évite le papier crème + serif + terre cuite, très courant dans les designs générés |
| Signature | La **chaîne de preuve** : pastilles reliées (table → filtre → période → opération) | Rend ENF6 visible sans exposer le SQL au décideur |
| Moment mémorable | À l'accueil, un compteur à chiffres qui roule, un soulignement safran qui se trace, une courbe qui se dessine, puis la chaîne qui se monte | Les trois premières secondes disent ce que fait le produit |
| Hiérarchie | Chiffres clés très grands, texte courant sobre, code en mono | Contraste d'échelle fort |
| Profondeur | Surfaces superposées (page, carte, panneau SQL), rayons de 14 à 38 px, ombres douces | Distingue réponse, données et trace technique |
| Marque | Aucun logo, couleur ou texte de Wave ni d'Anthropic. Le back-office reprend la **structure** des consoles d'administration (navigation par groupes, tableaux avec filtres, tiroirs, barre d'enregistrement), pas leur habillage | Éviter toute confusion de marque |
| Thèmes | Clair et sombre conçus séparément, bascule dans l'interface | Pas d'inversion mécanique |

## 2. Jetons (variables CSS posées sur la racine de chaque composant)

```
clair  = { ground:#F3F5F9 card:#FFFFFF panel:#E9EDF6 line:#D3D9E8 line2:#8A90B5 ink:#14163D soft:#4B507D
           brand:#14164A brandInk:#EDEEFA brandSoft:#A8AEE6 primary:#2B2F8F primaryInk:#FFFFFF saff:#F2A900
           pos:#0C7356 neg:#B83A55 chip:#E7E9FA c1:#2B2F8F c2:#F2A900 c3:#0E8C86 c4:#C2415D }
sombre = { ground:#090B26 card:#151848 panel:#0E1038 line:#262A68 line2:#7076C8 ink:#EDEEFA soft:#A9AEE0
           brand:#1B1F66 brandInk:#EDEEFA brandSoft:#B6BBEE primary:#8C93FF primaryInk:#0E1033 saff:#FFC233
           pos:#7FE0BC neg:#FF8FA5 chip:#232766 c1:#8C93FF c2:#FFC233 c3:#4FD1C5 c4:#FF8FA5 }
```

Règles : jamais de couleur en dur dans un composant (sauf `#14163D` sur fond safran) ; `line` pour les séparateurs, **`line2` pour toute bordure de composant interactif** (≥ 3:1 dans les deux thèmes) ; texte sur fond safran toujours en `#14163D` ; les valeurs de `pos` et `line2` ont été ajustées après l'audit d'accessibilité (`pos` clair 5,0:1 sur `panel`, `line2` sombre ≥ 4:1).

Espacements et rayons : gouttières de 8, 12, 18, 28 px ; cartes de 22 à 28 px de rayon, grandes scènes 34 à 38 px, pastilles 999 px. Ombre de carte `--sh`.

## 3. Typographie

| Rôle | Police | Usage |
|---|---|---|
| Titres et chiffres | Bricolage Grotesque (300 à 800, axe optique) | Chiffre clé (jusqu'à 150 px, graisse 300), titres de page, questions |
| Interface | Instrument Sans (400, 500, 600) | Texte courant, boutons, tableaux |
| Code | JetBrains Mono (400, 500) | SQL, identifiants, trace_id, diff YAML |

Chiffres tabulaires pour tout nombre. Montants en FCFA, espace insécable, virgule décimale. Pas de majuscules espacées en étiquettes, pas de mot isolé accentué dans un titre.

## 4. Composants

| Famille | Composants | Remarques |
|---|---|---|
| Navigation | Rail flottant de 76 px (application), barre latérale de 272 px par groupes (back-office), barre du bas sur mobile | `aria-current="page"`, lien d'évitement |
| Saisie | Zone de question avec frappe d'exemples, boutons radio pour les choix exclusifs, champs avec aide et erreur reliées par `aria-describedby`, cases du code à 6 chiffres | L'indicateur de focus passe par le conteneur (`:focus-within`) avec contour transparent pour le contraste forcé |
| Réponse | Carte de réponse (chiffre, delta, phrase, graphique), pastilles de contexte, **chaîne de preuve**, volet SQL (analyste), questions de suivi, étapes de calcul | Le graphique est choisi par le code, jamais par le modèle |
| Graphiques | Courbe (période courante pleine, précédente en pointillés, pic cerclé), barres horizontales triées, anneau avec légende, tableau trié, chiffre clé seul | Étiquettes directes, résumé textuel et équivalent tabulaire |
| États | Calcul en cours, précision demandée, refus, résultat vide, résultat tronqué, panne du modèle, session expirée, accès refusé, chargement en squelette, tuile en erreur | Chacun a un écran de référence |
| Tableaux | Tableau avec légende masquée, tri annoncé (`aria-sort`), ligne dépliable, défilement horizontal en boîte | Cibles ≥ 44 px |
| Back-office | En-tête de page (titre, description, actions), cartes, statistiques, segments, badges (icône + texte), interrupteurs (`role="switch"`), tiroir latéral, boîte de confirmation, barre d'enregistrement qui apparaît avec les modifications, diff `-` / `+`, toast permanent annoncé | Classes partagées `ad-`, une seule coque |
| Analyse | Bloc « Analyse de l'agent de données » : phrase d'accroche écrite en direct, 3 constats avec étiquette, texte et niveau de confiance | Hypothèse toujours étiquetée |

## 5. Écrans (45)

| Groupe | Écrans |
|---|---|
| Prototype | App : tous les écrans reliés, bouton « Démo : états » |
| Authentification (A01 à A10) | Connexion, mot de passe oublié, message envoyé, nouveau mot de passe, vérification en deux étapes, compte verrouillé, première connexion, session expirée, déconnecté, connexion réussie |
| Application (U01 à U18) | Accueil, calcul en cours, réponse avec courbe, précision demandée, classement, répartition, tableau tronqué, résultat vide, refus hors périmètre, refus de modification, panne du modèle, indicateurs avec analyse, indicateurs en sombre, journal d'audit analyste, accès refusé, session expirée, réponse avec SQL, réponse en sombre |
| Mobile (M1 à M3) | Accueil, conversation, indicateurs |
| Back-office (B01 à B13) | Vue d'ensemble, utilisateurs, invitation, détail d'un utilisateur, catalogue de KPI, éditeur de KPI, couche sémantique, journal d'audit, détail d'un appel, sécurité, évaluation, signalements, paramètres |

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

React + Vite + TypeScript, organisation par fonctionnalités (`conversation`, `dashboard`, `auth`, `admin`), composants tiers enveloppés, styles CSS à variables. Graphiques SVG maison ou Recharts enveloppé. Tests : Vitest et Testing Library, MSW, Playwright (parcours connexion → question → graphique, captures aux largeurs 320, 768, 1024, 1440 dans les deux thèmes), axe-core en CI. Budget : JS ≤ 300 kB gzippé, LCP < 2,5 s, CLS < 0,1, INP < 200 ms. Les pages d'authentification sont un thème Keycloak qui reprend ces jetons.

## 8. À valider

1. Navigation restreinte du back-office pour l'analyste.
2. Rendu réel des animations d'accueil (compteur, soulignement, chaîne) et de la version mobile, jamais encore vus dans un navigateur.
3. Choix des segments de l'évaluation en thème clair (mélange de couleurs à vérifier visuellement).
