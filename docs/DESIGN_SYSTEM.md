# Design System

Complète [SRS.md](../SRS.md) (ENF7) et [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md). Cible : l'interface React + Vite (`web/`).

## 1. Direction

**« Cahier de bord » : éditorial sobre, orienté lecture de chiffres.** Le produit est un outil de décision, pas un tableau de bord décoratif. Le chiffre est le héros, la phrase qui l'entoure donne le sens, le SQL reste en retrait.

| Choix | Décision | Pourquoi |
|---|---|---|
| Ambiance | Papier chaud, encre profonde, un seul accent | Lecture longue, sérieux, distinct d'un gabarit SaaS gris-bleu |
| Hiérarchie | Très grands chiffres clés (serif), texte courant sobre (sans), SQL en mono | Contraste d'échelle fort |
| Profondeur | Surfaces superposées (papier / carte / panneau SQL), ombres douces, filets fins | Distinguer réponse, données et trace technique |
| Marque | Pas de logo, couleurs ni nom de Wave : identité propre au projet | Éviter toute confusion avec une marque réelle |
| Thème | Clair par défaut, sombre soigné | Les deux sont conçus, pas inversés mécaniquement |

Quatre qualités vérifiables en revue : contraste d'échelle, rythme d'espacement non uniforme, états interactifs dessinés, couleur sémantique.

## 2. Jetons (CSS custom properties, `web/src/styles/tokens.css`)

Couleurs en `oklch`. Valeurs de départ, à ajuster à l'écran puis à contrôler (contraste ≥ 4,5:1 pour le texte, 3:1 pour les composants).

```css
:root {
  --paper:        oklch(97.5% 0.012 85);   /* fond de page */
  --card:         oklch(99.2% 0.006 85);   /* réponses, cartes */
  --panel:        oklch(94.5% 0.014 85);   /* panneau SQL, zones secondaires */
  --line:         oklch(88% 0.016 85);
  --ink:          oklch(21% 0.025 260);    /* texte principal */
  --ink-soft:     oklch(42% 0.02 260);     /* texte secondaire */
  --accent:       oklch(46% 0.095 190);    /* vert-bleu profond : actions, liens, focus */
  --accent-ink:   oklch(98% 0.01 190);
  --positive:     oklch(50% 0.12 150);
  --negative:     oklch(50% 0.17 25);
  --warning:      oklch(62% 0.13 75);
  --focus-ring:   0 0 0 3px oklch(46% 0.095 190 / 0.35);

  --font-ui:      "IBM Plex Sans", system-ui, sans-serif;
  --font-mono:    "IBM Plex Mono", ui-monospace, monospace;
  --font-figure:  "Fraunces", Georgia, serif;

  --text-sm:      0.875rem;
  --text-base:    1rem;
  --text-lg:      1.25rem;
  --text-figure:  clamp(2.5rem, 1.5rem + 4vw, 4.5rem);

  --space-1: 0.25rem; --space-2: 0.5rem; --space-3: 0.75rem; --space-4: 1.25rem;
  --space-5: 2rem;    --space-6: 3.25rem;
  --radius-sm: 6px;   --radius-md: 12px;   --radius-pill: 999px;

  --shadow-card:  0 1px 2px oklch(20% 0.02 260 / 0.06), 0 8px 24px oklch(20% 0.02 260 / 0.06);
  --dur-fast: 150ms;  --dur-normal: 280ms;  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
}

:root[data-theme="dark"] {
  --paper: oklch(19% 0.02 260); --card: oklch(23% 0.022 260); --panel: oklch(16% 0.02 260);
  --line: oklch(32% 0.02 260);  --ink: oklch(94% 0.012 85);   --ink-soft: oklch(75% 0.015 85);
  --accent: oklch(74% 0.1 190); --accent-ink: oklch(18% 0.02 260);
  --positive: oklch(74% 0.13 150); --negative: oklch(72% 0.15 25); --warning: oklch(80% 0.12 75);
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { /* mêmes valeurs que ci-dessus */ } }
```

Règles : jamais de couleur, d'espacement ou de durée en dur dans un composant ; le thème se lit du système puis d'un choix explicite ; `font-display: swap`, deux familles (Plex Sans et Plex Mono forment une famille, plus Fraunces), sous-ensemble latin.

## 3. Typographie

| Rôle | Police | Taille | Usage |
|---|---|---|---|
| Chiffre clé | Fraunces, chiffres tabulaires | `--text-figure` | Résultat principal d'une réponse, KPI |
| Titre de réponse | Plex Sans 600 | `--text-lg` | Phrase d'accroche |
| Texte | Plex Sans 400 | `--text-base` | Explications, libellés |
| Métadonnées | Plex Sans 500 | `--text-sm`, majuscules espacées | Période, périmètre, rôle |
| Code | Plex Mono | `--text-sm` | SQL, noms de table |

Montants en XOF, espace fine insécable, locale `fr-FR` (`1 234 567 FCFA`). Pourcentages et écarts : signe explicite, jamais seulement la couleur.

## 4. Couleur dans les graphiques

- Une série : `--accent`. Plusieurs : palette catégorielle de 6 teintes distinctes en luminosité (pas seulement en teinte), testée en simulation de daltonisme avant adoption.
- Comparaison de périodes : période courante en `--accent`, période de référence en `--ink-soft` (trait pointillé ou motif).
- Rouge et vert réservés aux écarts, toujours doublés d'un signe `+`/`−` et d'une flèche.
- Axes et grilles en `--line`, jamais plus contrastés que les données.

Formes (le graphique est choisi par le code, AGENTIC §7) : courbe pour un temps, barres horizontales triées pour un classement, répartition pour ≤ 6 parts, chiffre clé seul pour une valeur. Pas d'axe tronqué sur les barres ; étiquettes directes plutôt que légende lointaine quand il y a peu de séries. Chaque graphique a un tableau équivalent accessible.

## 5. Composants

`web/src/components/ui/` : primitives accessibles (Radix UI) **enveloppées** dans nos composants, un composant par fichier, sans fichier d'export global.

| Composant | Rôle | États dessinés |
|---|---|---|
| `Button` | Actions principale, secondaire, discrète | repos, survol, focus, actif, désactivé, chargement |
| `ChatInput` | Saisie de la question, envoi au clavier | focus, envoi, désactivé pendant la réponse |
| `AnswerCard` | Chiffre clé, phrase, pastilles période/périmètre, graphique, tableau | chargement par étapes, succès, erreur, repli |
| `ClarificationCard` | Question de précision avec 2-3 choix | choix survolé, choisi |
| `RefusalNote` | Refus motivé | — |
| `StepStream` | Événements d'étape (« Je consulte les KPI… ») | en cours, terminé |
| `Chart` | Courbe, barres, répartition depuis `AssistantMessage.chart` | info-bulle, focus clavier sur les points |
| `DataTable` | Tableau trié | tri, ligne tronquée (`truncated`) |
| `SqlPanel` | SQL et tables, **analyste uniquement** | replié, déplié, copier |
| `KpiTile` | Chiffre, variation, mini-courbe | chargement, vide, erreur |
| `ConversationList` | Historique, relance | actif, survol |
| `AuditTable` | Journal technique (analyste) | filtre, pagination |
| `Banner` / `Toast` | Erreurs, session expirée | info, avertissement, erreur |
| `ThemeToggle` | Clair / sombre / système | — |

Chaque composant couvre : repos, survol, focus visible (`--focus-ring`), actif, désactivé, chargement, vide, erreur.

## 6. Écrans

| Écran | Contenu | Rôle |
|---|---|---|
| Conversation | Fil d'`AnswerCard`, saisie fixe en bas, historique latéral | tous |
| Tableau de bord | `KpiTile` pilotées par `get_kpi`, sélecteur de période | tous |
| Audit | `AuditTable` technique | analyste |
| Connexion | Redirection Keycloak, page de retour | tous |

Colonne de lecture centrée (≈ 72 caractères) ; tableau de bord asymétrique (une grande tuile principale, les autres plus petites). Mobile : une colonne, saisie ancrée en bas, historique en tiroir. Contrôles visuels : 320, 768, 1024, 1440 px, deux thèmes.

## 7. Accessibilité (WCAG 2.2 AA)

- Contrastes mesurés pour chaque couple de jetons, dans les deux thèmes ; l'information n'est jamais portée par la couleur seule.
- Navigation 100 % clavier, ordre logique, focus visible.
- Zone de réponse en `aria-live="polite"` : étapes, réponse finale, refus et précision sont annoncés.
- Graphiques : résumé textuel en une phrase et tableau équivalent ; info-bulles atteignables au clavier.
- Cibles tactiles ≥ 44 px ; zoom 200 % sans perte ; `prefers-reduced-motion` coupe les animations non essentielles.
- Document en `fr` ; champs étiquetés ; erreurs associées aux champs.

## 8. Mouvement

Court et fonctionnel : apparition d'une réponse (opacité + léger décalage vertical, 280 ms), progression des étapes, repli/dépli du SQL. Seules `transform` et `opacity` sont animées ; en `prefers-reduced-motion`, changement instantané.

## 9. Ton et texte (français)

Phrases courtes, chiffre d'abord, période et périmètre rappelés : « **12 480 transactions** réussies en septembre 2026, toutes régions. » Les incertitudes sont dites (« résultat tronqué à 1 000 lignes »). Les erreurs expliquent quoi faire. Pas de jargon SQL pour le décideur, qui n'a d'ailleurs pas accès au SQL.

## 10. Implémentation et qualité

- React + Vite + TypeScript, organisation par fonctionnalités (`features/conversation`, `features/dashboard`, `features/audit`), composants tiers enveloppés.
- Styles : CSS avec jetons, modules CSS par composant.
- Graphiques : Recharts enveloppé dans `Chart`.
- Tests : Vitest et Testing Library, MSW pour l'API, Playwright pour « question → graphique » et captures aux 4 largeurs et 2 thèmes, axe-core en CI.
- Budget : JS ≤ 300 kB gzippé, LCP < 2,5 s, CLS < 0,1, INP < 200 ms.

## 11. Points à valider

1. La direction « cahier de bord » (papier chaud, vert-bleu profond, Fraunces) vous convient-elle ?
2. Voulez-vous une maquette HTML statique de l'écran de conversation avant de coder `web/` ?
