# Design System

Version 3, alignée sur la maquette interactive (45 écrans), palette bleu ciel et photographies. Complète [SRS.md](../SRS.md) (ENF7, ENF12) et [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md). Cible : l'application React + Vite (`web/`), dont les routes `/admin`.

Maquette de référence : « Maquette — Agent décisionnel », artefact privé de l'auteur (45 écrans interactifs, composants sources en bas du canvas).

## 1. Direction

**Bleu ciel, marine, jaune soleil, et de la vraie photographie.** Le produit est un outil de décision : le chiffre est le héros, la phrase qui l'entoure donne le sens, la **chaîne de preuve** montre d'où il vient. Le SQL reste en retrait et n'est visible que pour l'analyste.

| Choix | Décision | Pourquoi |
|---|---|---|
| Palette | Bleus **mesurés par échantillonnage de pixels sur deux captures de l'interface Wave fournies par l'auteur** : cyan du logo `#1DC8FE`, bleu d'action `#2F6FED`, bleu de barre latérale `#2D5ECE` ; **marine** pour le texte ; **jaune soleil** comme unique signal | Fidélité à la couleur de marque sur les grandes surfaces ; le bleu des contrôles est un peu plus foncé (`#2A5FD4`) parce que `#2F6FED` tombe à 3,8 à 4,2:1 en texte sur fond teinté |
| Photographie | Six photos de Dakar, Gorée, d'un marché et de pirogues de Saint-Louis, en bichromie bleue | La version précédente, sans image, faisait générique ; la photo ancre le produit dans son contexte |
| Signature | La **chaîne de preuve** : pastilles reliées (table → filtre → période → opération) | Rend ENF6 visible sans exposer le SQL au décideur |
| Moment mémorable | À l'accueil, un compteur à chiffres qui roule, un soulignement jaune soleil qui se trace sur une photo de Dakar en bichromie, une courbe qui se dessine, puis la chaîne qui se monte | Les trois premières secondes disent ce que fait le produit |
| Hiérarchie | Chiffres clés très grands, texte courant sobre, code en mono | Contraste d'échelle fort |
| Profondeur | Surfaces superposées (page, carte, panneau SQL), rayons de 14 à 38 px, ombres douces | Distingue réponse, données et trace technique |
| Marque | Aucun logo, nom ni texte de Wave ou d'Anthropic (les captures de référence montrent une mascotte et un logotype qui ne sont pas repris) ; seuls les bleus sont mesurés. Aucun code officiel n'est publié dans les sources consultées : les valeurs viennent des captures de l'auteur. Le back-office reprend la **structure** des consoles d'administration (navigation par groupes, tableaux avec filtres, tiroirs, barre d'enregistrement), pas leur habillage | Éviter toute confusion de marque |
| Thèmes | Clair et sombre conçus séparément, bascule dans l'interface | Pas d'inversion mécanique |

## 2. Jetons (variables CSS posées sur la racine de chaque composant)

```
clair  = { ground:#F2F7FC card:#FFFFFF panel:#E4EEF8 line:#CFDDEC line2:#6F8CAA ink:#0B2545 soft:#41607F
           brand:#2D5ECE brandInk:#EAF4FD brandSoft:#E3EEFF primary:#2A5FD4 primaryInk:#FFFFFF sky:#1DC8FE
           saff:#FFC83D pos:#0C7356 neg:#B83A55 chip:#E1EBFD c1:#2F6FED c2:#FFC83D c3:#0E8C86 c4:#C2415D }
sombre = { ground:#071A33 card:#0E2A4D panel:#0A2140 line:#1F3F66 line2:#6E93BD ink:#EAF4FD soft:#9FC0E0
           brand:#17458F brandInk:#EAF4FD brandSoft:#B9D0FA primary:#6FA3FF primaryInk:#071A33 sky:#3DD3FF
           saff:#FFD25E pos:#7FE0BC neg:#FF8FA5 chip:#12365F c1:#6FA3FF c2:#FFD25E c3:#4FD1C5 c4:#FF8FA5 }
```

`saff` désigne le jaune soleil (nom conservé dans le code). Pour changer de bleu de marque, on remplace `primary`, `sky` et `brand` à un seul endroit par composant racine.

Règles : jamais de couleur en dur dans un composant (sauf `#0B2545` sur fond jaune) ; `line` pour les séparateurs, **`line2` pour toute bordure de composant interactif** (≥ 3:1 dans les deux thèmes) ; texte sur fond jaune ou ciel toujours en `#0B2545`. Contrastes calculés (formule WCAG) : texte `ink` et `soft` ≥ 4,5:1 sur `ground`, `card` et `panel` ; blanc sur `primary` ≥ 4,5:1 ; `brandSoft` sur `brand` ≥ 4,5:1 ; `line2` sur `card` ≥ 3:1. Le cyan du logo (`#1DC8FE`) ne porte pas de texte blanc (1,9:1) : il sert aux surfaces et aux accents, avec du texte marine (7,9:1). Le bleu d'action exact `#2F6FED` donne 4,55:1 avec du blanc mais seulement 3,8 à 4,2:1 en texte sur fond teinté : les contrôles, liens et contours utilisent `primary` (`#2A5FD4`), et `#2F6FED` reste réservé aux aplats (`c1` : barres de graphique). Tous les couples ont été recalculés avec les valeurs ci-dessus : zéro échec dans les deux thèmes.

### Photographies

Six photos de la banque Unsplash (licence Unsplash : usage libre, crédit non obligatoire mais affiché), redimensionnées à 1600 ou 1800 px, 3,2 Mo au total, téléversées dans l'artefact.

| Fichier | Auteur | Lieu | Écrans |
|---|---|---|---|
| `dakar-skyline` | Kurt Cotoaga | Dakar | Accueil, connexion, connexion réussie |
| `dakar-monument` | Bamby Diagne | Dakar | Vérification en deux étapes, première connexion |
| `goree-maison-orange` | Anton Lecock | Gorée | Résultat vide, accès refusé |
| `goree-ruelle-rouge` | Anton Lecock | Gorée | Refus, compte verrouillé |
| `senegal-marche` | Wietse Jongsma | Sénégal | Mot de passe oublié, message envoyé, nouveau mot de passe |
| `saint-louis-pirogues` | Mohamed Habib Mbodj | Saint-Louis | Panne du modèle, session expirée, déconnexion |

Traitement : niveaux de gris, couche `sky` en multiplication (bichromie bleue), dégradé de lisibilité vers `brand` en bas, crédit « Photo : nom, Unsplash » toujours visible. Les photos sont décoratives (`alt=""`). La photo du marché montre des personnes identifiables : elle sert d'ambiance, jamais de portrait de clients du produit. Le back-office reste sans photo.

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

1. **Origine des bleus** : mesurés sur des captures fournies par l'auteur, pas sur un kit de marque officiel. À confirmer avec le kit presse de Wave si le projet est présenté à Wave.
2. Navigation restreinte du back-office pour l'analyste.
3. Rendu réel des photos en bichromie (lisibilité du texte sur l'image), des animations d'accueil et de la version mobile, jamais encore vus dans un navigateur.
4. Choix des segments de l'évaluation en thème clair (mélange de couleurs à vérifier visuellement).
