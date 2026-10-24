# Intégration LLM avec Claude : évaluation et design

Revue du 2026-10-24, sur SRS v4, AGENTIC_DESIGN v4 et SYSTEM_DESIGN v4. Aucun fichier du dépôt n'a été modifié.
Sources : documentation officielle (platform.claude.com), PyPI `anthropic` et la référence de l'API Claude embarquée dans Claude Code (mise en cache le 2026-10-06). Les URL figurent à chaque section.

---

## 0. Synthèse

| Sujet | Constat | Décision proposée |
|---|---|---|
| Modèles | Les quatre modèles existent et leurs identifiants sont exacts : `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5-1`. Contexte de 1 M, sortie maximale de 128 k. Un identifiant sans date est **un snapshot épinglé**. | Rôle principal : **Sonnet 5.5**, effort `medium` (ou `low`). Challenger : Opus 5.5 en `low`, et Haiku 5.5 testé sur le jeu de dev. Fable 5.1 est exclu. |
| Température 0 (ENF2) | **Plus supportée.** Les modèles 4.7 et suivants n'acceptent que les valeurs par défaut. Avec l'API `2026-10-21` (SDK Python ≥ 2.0.0), envoyer `temperature` renvoie une **400 sur tous les modèles**. | Réécrire ENF2 : la reproductibilité tient au snapshot épinglé, à l'effort fixé, aux hashes de prompt, aux 3 passes et aux garde-fous déterministes. |
| Choix forcé d'outil | `tool_choice` `any`/`tool` renvoie une **400** sur Opus 5.5 et Sonnet 5.5. | `tool_choice: auto`, outils en `strict: true`, outils terminaux (`clarify`, `refuse`, `final_answer`) et contrôle côté code. |
| Réflexion (thinking) | Toujours active sur Opus 5.5. Désactivable sur Sonnet 5.5 via `between_tools`. Haiku 5.5 accepte `disabled` jusqu'à l'effort `high`. | L'effort est le levier de latence. Les blocs `thinking` sont renvoyés tels quels et l'historique reste en ajout seul. |
| Mise en cache du prompt | Écriture ×1,25 (5 min) ou ×2 (1 h). Lecture ×0,05 sur Opus 5.5 et Sonnet 5.5, ×0,1 ailleurs. Préfixe minimal de 512 jetons. Les lectures ne comptent pas dans l'ITPM. | Point de cache de 1 h sur outils + système + couche sémantique (environ 12 k jetons), cache automatique de 5 min sur la boucle. |
| Coût | Environ **0,02 $/question** sur Sonnet 5.5 avec un cache chaud (0,07 $ à froid), 0,04 $ sur Opus 5.5, 0,001 $ sur Haiku 5.5. | Campagne de 1 050 exécutions : **environ 22 à 33 $** sur Sonnet, 44 à 66 $ sur Opus. |
| Latence | Aucune valeur de TTFT ni de débit n'est publiée. Selon nos hypothèses, Sonnet 5.5 en `low`/`medium` donne une médiane de 9 à 14 s ; Opus 5.5 risque de dépasser 15 s. | À mesurer dès P1. Les leviers sont la sortie minimale, l'effort, le cache et le préchauffage. |
| MCP | Le connecteur MCP côté API exige un serveur **HTTP public** (pas de stdio) et **n'est pas éligible à la ZDR**. | Le client MCP reste local dans l'API (stdio), conformément à S3. |
| Données | `inference_geo` n'offre que `global` ou `us` : pas d'UE ni d'Afrique. Batch, Files et le connecteur MCP sont hors ZDR. Fable 5.1 exige une rétention de 30 jours. | Acceptable sur données synthétiques. Bloquant à revoir avant de passer à des données réelles (Bedrock ou Vertex régional). |

---

## 1. État de l'offre Claude (octobre 2026)

### 1.1 Modèles

Source : https://platform.claude.com/docs/en/about-claude/models/overview et https://platform.claude.com/docs/en/about-claude/pricing

| | Fable 5.1 | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|---|
| ID API | `claude-fable-5-1` | `claude-opus-5-5` | `claude-sonnet-5-5` | `claude-haiku-5-5` |
| Entrée / sortie ($/MTok) | 10 / 50 | 4 / 20 | 2 / 10 | 0,10 / 0,50 (prompt ≤ 100 k), 0,50 / 2,50 au-delà |
| Écriture de cache 5 min / 1 h | 12,50 / 20 | 5 / 8 | 2,50 / 4 | 0,125 / 0,20 |
| Lecture de cache | 0,25 (×0,025) | 0,20 (×0,05) | **0,10** (×0,05) | 0,01 (×0,1) |
| Batch entrée / sortie | – | 2 / 10 | 1 / 5 | 0,05 / 0,25 |
| Latence relative (doc) | Lente | Modérée | Rapide | La plus rapide |
| Réflexion | Adaptative, toujours active | Adaptative, **toujours active** | Adaptative ; `between_tools` pour la couper | Adaptative ; `disabled` accepté jusqu'à l'effort `high` |
| Effort par défaut | `high` | **`medium`** | `high` | **`medium`** |
| Contexte / sortie | 1 M / 128 k | 1 M / 128 k | 1 M / 128 k | 1 M / 128 k |
| Retrait (au plus tôt) | 2027-09-01 | 2027-09-22 | 2027-09-28 | 2027-10-07 |
| ZDR | **Non** (rétention de 30 jours exigée, « Covered Model ») | Oui | Oui | Oui |

Remarques :
- Note de la page modèles : *« Every Claude model ID is a pinned snapshot, including the dateless IDs used from the 4.6 generation on. »* L'exigence d'un « identifiant daté » (AGENTIC §9) n'a donc plus d'objet : `claude-sonnet-5-5` est figé.
- Depuis Opus 4.7, le tokenizer produit environ 30 % de jetons de plus qu'avant. Il faut **recompter avec `count_tokens` sur le modèle cible** et ne pas reprendre d'anciens chiffres (https://platform.claude.com/docs/en/build-with-claude/token-counting).
- Pour le mode rapide d'Opus 5.5 (`speed: "fast"`, bêta `fast-mode-2026-02-01`), la doc annonce « jusqu'à 2,5× de débit de sortie » pour un tarif de 8 / 40 $/MTok. C'est un levier de latence de secours (https://platform.claude.com/docs/en/build-with-claude/fast-mode).
- Le Priority Tier n'est **pas** disponible sur Opus 5.5 ni Sonnet 5.5.
- `inference_geo: "us"` applique un multiplicateur de 1,1 (https://platform.claude.com/docs/en/manage-claude/data-residency).

### 1.2 Fonctionnalités de l'API utiles au projet

| Fonctionnalité | État et points clés | Source |
|---|---|---|
| **Usage strict des outils** | `strict: true` sur la définition de l'outil : l'entrée respecte le schéma (`additionalProperties: false` et `required`). Limites : 20 outils stricts par requête, **24 paramètres optionnels au total**, 16 paramètres en `anyOf` ou en tableau de types. `minimum`/`maximum`/`minLength` ne sont pas supportés. La grammaire compile au premier appel (latence), puis reste en cache 24 h. | https://platform.claude.com/docs/en/build-with-claude/structured-outputs |
| **Sorties structurées** | `output_config.format` (json_schema). En Python, `client.messages.parse(output_format=PydanticModel)`. Changer le format invalide le cache. | idem |
| **`tool_choice`** | `auto` (par défaut) et `none` uniquement sur Opus 5.5, Sonnet 5.5 et Fable 5.1 ; `any`/`tool` renvoient une 400. `disable_parallel_tool_use` fonctionne avec `auto` et limite alors à **au plus** un appel. | https://platform.claude.com/docs/en/api/errors |
| **Préremplissage** | Supprimé : 400 sur tous les modèles 4.6 et suivants. | idem |
| **Mise en cache du prompt** | Correspondance par préfixe dans l'ordre `tools` → `system` → `messages`. 4 points de cache au maximum. TTL de 5 min ou 1 h ; une entrée de 1 h doit précéder une entrée de 5 min. Cache automatique au niveau supérieur (`cache_control` sur la requête). Isolé par workspace. Préchauffage avec `max_tokens: 0` (pas en flux, pas en batch, pas avec `output_config.format`). | https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
| **Réflexion et effort** | `output_config.effort` : `low`, `medium`, `high`, `xhigh`, `max`. L'effort réduit aussi le nombre d'appels d'outils et leur verbosité. Changer l'effort au niveau supérieur d'une requête à l'autre invalide le cache ; l'effort par message (bêta) le préserve. La réflexion compte dans `max_tokens`. L'affichage par défaut est `omitted` (blocs `thinking` vides, mais facturés). | https://platform.claude.com/docs/en/build-with-claude/effort |
| **Réflexion préservée** | Sur Opus 5.5, Sonnet 5.5 et Haiku 5.5, un bloc `thinking` rejoué n'est valide que si `system`, `tools` et les messages précédents sont identiques à l'octet près. Comptes créés à partir du **2026-08-31** : **400** en cas d'édition. | idem, section *Thinking block no longer matches* |
| **Flux** | SSE ; `client.messages.stream(...).get_final_message()`. Une erreur peut survenir après le 200 (événement `error`). | https://platform.claude.com/docs/en/build-with-claude/streaming |
| **Batch API** | −50 %. La plupart des lots finissent en moins d'une heure, expiration à 24 h. Les résultats sont gardés 29 jours, hors ZDR. Pas de boucle d'outils multi-tours dans une même requête. | https://platform.claude.com/docs/en/build-with-claude/batch-processing |
| **Comptage des jetons** | `POST /v1/messages/count_tokens`, **gratuit**, avec une limite de RPM propre. C'est une estimation, et elle n'utilise pas le cache. | https://platform.claude.com/docs/en/build-with-claude/token-counting |
| **Limites de débit** | Palier Start : Sonnet 5.5, Opus 5.5 et Haiku 5.5 ont chacun 1 000 RPM, 2 M ITPM et 400 k OTPM, dans des pools séparés. Les **lectures de cache ne comptent pas dans l'ITPM**. Plafond de dépenses mensuel : 500 $ (Start) ; une fois atteint, la 429 n'a **pas** d'en-tête `retry-after`. | https://platform.claude.com/docs/en/api/rate-limits |
| **Erreurs** | 429 `rate_limit_error`, 500 `api_error`, 504 `timeout_error`, **529 `overloaded_error`**. Le SDK refait 2 essais par défaut et respecte `retry-after`. En-tête `request-id`. | https://platform.claude.com/docs/en/api/errors |
| **Refus des classifieurs** | HTTP 200 avec `stop_reason: "refusal"` et `stop_details.category` (cyber, bio, …). Fallback serveur `fallbacks: "default"` (bêta `server-side-fallback-2026-07-01`) disponible sur Opus 5.5 et Sonnet 5.5 (API Claude) ; **pas sur Haiku 5.5**. | référence de l'API Claude (Claude Code), migration Opus/Sonnet 5.5 |
| **Version d'API** | `2026-10-21` (SDK Python **2.0.0**, actuellement 2.3.0 sur PyPI, Python ≥ 3.10) supprime `temperature`, `top_p` et `top_k`. Le SDK 2.0 apporte aussi ses propres changements cassants (`MessageParam` en union par rôle, authentification en `Bearer`, un identifiant par client). | https://platform.claude.com/docs/en/api/migration-2026-10-21 |

### 1.3 Boucle d'agent : options

| Option | Pour | Contre | Verdict |
|---|---|---|---|
| **Boucle manuelle** sur `messages.stream` | Contrôle total sur le plafond de 6 étapes et 30 s, l'écriture de `query_log` à chaque appel, l'annulation à la déconnexion, la validation des outils terminaux, la réécriture d'erreurs et les relances bornées par l'échéance. Aucune dépendance bêta. | Une centaine de lignes à écrire et tester. | **Retenue.** |
| Tool Runner du SDK (`client.beta.messages.tool_runner`) | Moins de code. Les hooks par tour couvrent l'interception. | Bêta. L'échéance globale, l'annulation et les sorties terminales sont plus difficiles à exprimer. | Écarté. |
| Claude Agent SDK (`claude-agent-sdk`) | Harnais complet (outils fichiers et bash, sous-agents). | C'est le harnais de Claude Code : outils système de fichiers et shell inutiles et dangereux ici, surface d'attaque, latence, contrôle fin perdu. | **Écarté** (contraire à A1, ENF3 et ENF5). |
| Managed Agents | Boucle hébergée par Anthropic. | État conservé côté Anthropic (hors ZDR), bac à sable distant, pas d'accès direct au MCP stdio. | Écarté. |

### 1.4 MCP : connecteur côté API ou client local

- **Connecteur MCP côté API** (`mcp_servers` + `mcp_toolset`, bêta `mcp-client-2025-11-20`) : *« The server must be publicly exposed through HTTP … Local STDIO servers cannot be connected directly. »* Il est **hors ZDR** et le comptage de jetons ne le supporte pas (https://platform.claude.com/docs/en/agents-and-tools/mcp-connector). Il faudrait exposer publiquement la porte d'accès aux données, ce qui est contraire à S3 et à ENF3.
- **Client MCP local** : l'API lance le serveur en stdio et relaie les `tool_use` vers `ClientSession.call_tool`. Le SDK fournit des convertisseurs (`anthropic.lib.tools.mcp.async_mcp_tool`, bêta, `pip install anthropic[mcp]`), mais **il vaut mieux déclarer les schémas d'outils côté agent** (fichier versionné, `strict: true`, descriptions maîtrisées, octets stables pour le cache) et n'utiliser MCP que comme transport d'exécution. Un test CI vérifie que les schémas déclarés et le `list_tools()` du serveur restent cohérents.

### 1.5 Rétention et région

Source : https://platform.claude.com/docs/en/manage-claude/api-and-data-retention

- API Claude, hors arrangement : *« Conversation content (your prompts and Claude's outputs) is not retained by default »*, sauf pour les Covered Models (Fable, Mythos : 30 jours), les contenus signalés et les obligations légales. Rien n'est utilisé pour l'entraînement sans accord exprès.
- La ZDR se demande auprès de l'équipe commerciale, par organisation. Ne sont **pas** éligibles : Batch (29 jours), Files, connecteur MCP, exécution de code, Console et Managed Agents. Sont éligibles : Messages, comptage de jetons, mise en cache, sorties structurées (les schémas sont cachés 24 h).
- Région : `inference_geo` ∈ {`global`, `us`}, et le seul workspace geo est `us`. Il n'existe **aucune option d'inférence en UE ou en Afrique** sur l'API directe. Pour des données réelles de Wave, il faudrait passer par Bedrock ou Vertex avec un point de terminaison régional européen (hors périmètre, à acter dans le mémoire).
- Pour ce projet, les données sont synthétiques et le flux est documenté (SRS §2). Le risque est accepté, mais il faut : (1) ne pas utiliser Fable ; (2) ne pas envoyer de texte libre de la base ; (3) ne pas utiliser l'API Batch pour des données réelles futures.

---

## 2. Quel modèle pour quel rôle

### 2.1 Recommandation

| Rôle | Modèle | Réglages | Justification |
|---|---|---|---|
| **Tour d'intention + boucle SQL** (un seul agent, A5) | **`claude-sonnet-5-5`** | `thinking` omis (adaptatif), `effort: "medium"` ; balayer `low` et `medium`, et tester `thinking: {"type": "between_tools"}` si le p90 déborde | Positionné « rapide », 2× moins cher qu'Opus. Schéma de 5 tables : la difficulté vient du glossaire et des pièges, pas du raisonnement long. Accepte `between_tools`, ce qu'Opus 5.5 ne permet pas. Fallback serveur disponible. |
| Challenger justesse | `claude-opus-5-5` | `effort: "low"` (puis `medium`) | À adopter seulement si le jeu de dev montre un gain de justesse significatif (au-delà de l'intervalle). Risque sur la médiane < 15 s (latence « modérée », réflexion toujours active). Le mode rapide est le levier de secours. |
| Challenger coût et latence | `claude-haiku-5-5` | `effort: "medium"`, réflexion activée (la doc conseille de garder la réflexion avec format JSON + outils) | 20× moins cher que Sonnet. Instructions bien mieux suivies qu'Haiku 4.5. Pas de fallback serveur. À comparer sur le dev (AGENTIC §3 le prévoit déjà pour l'intention). |
| **Mode analyse du tableau de bord** (RF17) | `claude-sonnet-5-5` | `effort: "medium"`, **un seul appel** avec `output_config.format` (schéma `{lead, constats[≤3], follow[]}`), **sans outils** | Voir §4.6 : le code appelle `get_kpi` pour les 6 KPI × 2 périodes, ce qui rend les chiffres déterministes, puis le LLM rédige. Coût d'environ 0,02 $ par analyse, mise en cache dans `app.analysis`. Haiku 5.5 est candidat après évaluation. |
| Juge (optionnel) | `claude-opus-5-5`, via **Batch API** | `effort: "medium"`, sortie structurée | **Jamais pour O1** (compare.py est déterministe, conformément à A4). Seulement comme aide pour RF17 : détecter une « cause affirmée sans étiquette hypothèse » et repérer des constats douteux, en confrontant à un échantillon annoté à la main. Un modèle différent de l'agent limite l'auto-complaisance. |
| Refusé | `claude-fable-5-1` | – | Lent, 2,5× plus cher qu'Opus, rétention de 30 jours obligatoire (pas de ZDR). Disproportionné pour ce besoin. |

Ne pas faire de cascade de modèles dans une même question (par exemple Haiku pour l'intention puis Sonnet pour le SQL) : chaque modèle a son propre espace de cache, le fallback casse la chaîne de réflexion, et cela ajoute un aller-retour. A5 reste valable.

### 2.2 Hypothèses de jetons

À recompter avec `count_tokens` dès que les fichiers YAML existent.

| Bloc | Jetons (estimés) | Stabilité |
|---|---|---|
| Définitions de 6 outils (+286 jetons système ajoutés par l'API) | ~1 800 | Figée (version de prompt) |
| Prompt système (rôle, règles, politique d'intention, format de sortie, consignes de sécurité) | ~3 000 | Figée |
| Couche sémantique : `tables.yaml` (~2 500), `kpis.yaml` (~2 000), `glossary.yaml` (~700), `examples.yaml` 20 exemples (~3 000) | ~8 200 | Figée par `semantic_version` |
| **Préfixe stable (en cache)** | **~12 000** (fourchette 8 à 16 k) | Point de cache 1 h |
| `REFERENCE_DATE`, rôle, état résolu, 6 derniers échanges (compactés), question | ~1 500 | Change à chaque question |
| Sortie par appel (réflexion + appel d'outil) | 250 à 500 | – |
| Résultat d'outil `get_kpi` | ~300 | – |
| Résultat d'outil `run_query` (**≤ 50 lignes envoyées au LLM** + statistiques) | ~1 500 | – |
| `final_answer` (sans table ni graphique, voir §4.3) | ~450 | – |

Scénarios et répartition supposée : **K** (KPI, 2 appels) 45 %, **S3** (describe + run_query + final) 30 %, **C4** (avec une correction SQL) 15 %, **CLR** (clarify ou refuse, 1 appel) 10 %.

### 2.3 Coût par question

Calcul : script `cost.py` dans le scratchpad. Le préfixe est lu depuis le cache de 1 h, la boucle utilise le cache automatique de 5 min. « Froid » veut dire que le préfixe est réécrit au TTL de 1 h.

| Modèle | K | S3 | C4 | CLR | **Moyenne (chaud)** | Moyenne (froid) | Sans aucun cache |
|---|---|---|---|---|---|---|---|
| Opus 5.5 | 0,031 $ | 0,054 $ | 0,070 $ | 0,015 $ | **0,042 $** | 0,136 $ | 0,164 $ |
| **Sonnet 5.5** | 0,015 $ | 0,027 $ | 0,035 $ | 0,008 $ | **0,021 $** | 0,068 $ | 0,082 $ |
| Haiku 5.5 | 0,0009 $ | 0,0015 $ | 0,0020 $ | 0,0004 $ | **0,0012 $** | 0,0035 $ | 0,0041 $ |

Lecture :
- La mise en cache divise le coût par 4 environ (le préfixe pèse 12 k jetons, lu à ×0,05).
- La sortie (réflexion comprise) représente 40 à 50 % du coût à chaud : l'effort et la taille de `final_answer` sont les leviers principaux.
- Si la réflexion double à l'effort `medium` (+400 jetons par appel), Sonnet monte à environ 0,03 $ par question.
- Budget proposé pour ENF9, à confirmer après la première mesure : **plafond dur de 0,10 $ par question** (Sonnet) et **0,15 $** (Opus), avec arrêt et repli honnête au-delà.

### 2.4 Campagne d'évaluation

Hypothèse : 70 questions (dev ~30 + test 40) × 3 passes = 210 exécutions, plus 4 ablations × 210 = 840, soit **1 050 exécutions**. S'y ajoutent RF17 (12 cas × 3 = 36 analyses).

| Modèle | Campagne (chaud) | Avec marge ×1,5 (relances, réflexion plus longue) | Sans cache |
|---|---|---|---|
| Opus 5.5 | 44 $ | **66 $** | 172 $ |
| **Sonnet 5.5** | 22 $ | **33 $** | 86 $ |
| Haiku 5.5 | 1,3 $ | **2 $** | 4 $ |
| RF17 (36 analyses, Sonnet) | ~0,8 $ | – | – |

- Une itération de dev typique (30 × 3 = 90 exécutions) coûte environ 2 à 3 $ sur Sonnet. Même 20 itérations restent sous 60 $.
- Un comparatif à trois modèles sur le dev (Sonnet, Opus, Haiku × 30 × 3) coûte environ 6 $ : il faut le faire en P1.
- **API Batch : pas pour la boucle d'agent.** Une boucle de 2 à 4 tours imposerait 2 à 4 lots successifs (jusqu'à 1 h chacun), la latence (O2) ne serait pas mesurable, et l'économie serait d'environ 10 à 15 $. La réserver au juge optionnel et aux analyses RF17 en un seul appel, sur des données synthétiques uniquement (29 jours de rétention).
- La campagne tient très largement dans le plafond de 500 $ du palier Start. Créer un **workspace « eval » séparé** avec sa propre limite de dépenses : les caches sont isolés par workspace, donc l'évaluation ne réchauffe pas la production.

### 2.5 Latence face à O2 (médiane < 15 s, p90 < 30 s)

La documentation ne publie **ni TTFT ni débit**. Hypothèses à vérifier dès P1 : avec un préfixe en cache, Sonnet 5.5 a un TTFT de 0,8 à 1,5 s et sort 80 à 120 jetons/s ; Opus 5.5 a un TTFT de 1 à 2 s et sort 50 à 70 jetons/s ; Haiku 5.5 a un TTFT inférieur à 0,8 s et sort plus de 150 jetons/s. Sans cache, un préfixe de 12 k jetons ajoute un temps de prefill non négligeable : la mise en cache réduit aussi le TTFT.

| Scénario | Appels LLM | Sortie totale | Outils | Sonnet 5.5 (effort low/medium) | Opus 5.5 (low) |
|---|---|---|---|---|---|
| K | 2 | ~750 | ~0,3 s | **7 à 11 s** | 11 à 16 s |
| S3 | 3 | ~1 200 | 1 à 3 s | **12 à 18 s** | 18 à 26 s |
| C4 | 4 | ~1 700 | 2 à 5 s | **17 à 25 s** | 25 à 35 s |
| CLR | 1 | ~250 | 0 | 3 à 4 s | 4 à 6 s |

Conclusion : sous ces hypothèses, Sonnet 5.5 tient **une médiane d'environ 10 à 13 s et un p90 d'environ 22 à 27 s**, avec peu de marge. Opus 5.5 dépasse probablement la médiane. Leviers, par ordre d'efficacité :

1. **Réduire la sortie** : `final_answer` ne contient ni lignes ni graphique, qui sont calculés par le code (A9). Le modèle renvoie une référence au résultat d'outil (§4.3).
2. **Effort** `low` sur la boucle (`between_tools` sur Sonnet en dernier recours). Mesurer l'effet sur la justesse.
3. **Appels d'outils parallèles** : deux `get_kpi` dans un même tour pour les comparaisons de périodes, ce qui économise un aller-retour complet.
4. **Mise en cache** du préfixe : 1 h, préchauffé au démarrage de l'API avec `max_tokens: 0`, sans flux et avec les mêmes `thinking`/`effort`.
5. Plafond de **2 corrections SQL** (déjà prévu) et `describe_table` évité grâce au schéma en contexte.
6. En dernier recours : mode rapide d'Opus 5.5 (×2 sur le prix), ou Haiku 5.5 si la justesse tient.

Point à clarifier dans le SRS : O2 dit « sans cache ». Préciser que cela désigne l'absence de **cache de réponses ou de SQL** (S8, A8). La mise en cache du préfixe côté fournisseur ne change pas les sorties et fait partie de la configuration de production. Publier aussi la latence « cache froid » (première question après plus d'une heure d'inactivité) à part.

---

## 3. Évaluation de l'existant : `LLMClient`, température, reproductibilité

### 3.1 Température 0 (ENF2, AGENTIC §9)

- **Elle n'est plus possible.** Pour Claude 4.7 et suivants, la doc parle de *« models that already accept only the defaults »*. Avec l'API `2026-10-21`, *« a request that sends temperature, top_p, or top_k returns a 400 error, even at the parameter's default value »* (https://platform.claude.com/docs/en/api/migration-2026-10-21). Le SDK Python ≥ 2.0.0 utilise cette version par défaut.
- Même à l'époque où elle était acceptée, la température 0 ne garantissait pas un résultat déterministe, et elle est sans objet avec la réflexion adaptative.
- **Réécriture proposée d'ENF2** : « Réponses justes et stables : snapshot de modèle épinglé (`claude-sonnet-5-5`), effort fixé et versionné, prompts et couche sémantique hashés, version d'API et de SDK figées ; 3 passes en évaluation ; questions KPI à 3/3 ; garde-fous déterministes (`get_kpi`, validateur, graphique par le code) ; pas de cache SQL. » Retirer « température » de la traçabilité d'AGENTIC §9 et la remplacer par `effort`, `thinking.type`, `anthropic-version` et la version du SDK.
- La variance devient une **métrique** (cohérence 3/3, 2/3, 1/3) et non un paramètre. Les leviers de stabilité sont `get_kpi` en priorité, des exemples ciblés, le choix explicite clarify ou answer et un validateur strict.

### 3.2 Identifiants datés

Les identifiants de la génération 4.6 et suivantes sont des **snapshots épinglés sans date** ; il n'existe pas de `claude-sonnet-5-5-2026xxxx` et il ne faut pas en construire. À tracer dans `eval_run.model_id` et `query_log.model_id` :
- `model_requested` (configuration) et **`model_served`** (`response.model`). Ce dernier diffère si un fallback de refus a été déclenché.
- `anthropic-version` et version du SDK (`anthropic.__version__`).
- `effort`, `thinking.type`, `prompt_version`, `semantic_version`, hash des schémas d'outils.
- Date de retrait (Sonnet 5.5 au plus tôt le 2027-09-28) : aucun risque pendant le projet, mais à mentionner.

### 3.3 Interface `LLMClient`

L'idée d'une interface mince est bonne (tests hors ligne, journalisation, changement de fournisseur). Le risque est de construire un **plus petit dénominateur commun** qui ferait perdre : le placement des points de cache, le renvoi fidèle des blocs `thinking`, les outils stricts, `stop_reason: refusal`, l'usage détaillé (lectures et écritures de cache) et l'annulation. Proposition :

```python
# agent/llm/client.py
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, Callable, Awaitable

@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int            # non mis en cache (après le dernier point de cache)
    cache_read_tokens: int
    cache_write_5m_tokens: int
    cache_write_1h_tokens: int
    output_tokens: int           # inclut la réflexion (facturée même si display=omitted)

@dataclass(frozen=True)
class LLMStep:
    content: list[dict[str, Any]]   # blocs bruts (thinking, text, tool_use) à rejouer tels quels
    tool_calls: list[dict[str, Any]] # {id, name, input}
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "refusal", "pause_turn", "stop_sequence"]
    refusal_category: str | None
    usage: LLMUsage
    model_served: str
    request_id: str
    ttft_ms: int
    latency_ms: int

@dataclass(frozen=True)
class LLMRequest:
    model: str
    system: list[dict[str, Any]]       # blocs système, dont le point de cache 1 h
    tools: list[dict[str, Any]]        # schémas stricts, ordre et octets stables
    messages: list[dict[str, Any]]     # format Anthropic natif, en ajout seul
    effort: Literal["low", "medium", "high"]
    max_tokens: int
    deadline_s: float                  # temps restant du budget de 30 s
    output_format: dict[str, Any] | None = None   # mode analyse

class LLMClient(Protocol):
    async def step(self, req: LLMRequest,
                   on_event: Callable[[str, dict], Awaitable[None]] | None = None) -> LLMStep: ...
```

- Le format interne des messages reste **celui d'Anthropic** : convertir vers un autre fournisseur est le travail d'une seconde implémentation, pas de l'interface.
- Implémentations : `AnthropicClient` (SDK `AsyncAnthropic` en flux) et `ReplayClient` (cassettes JSON pour les tests unitaires de la boucle, du validateur et du formateur, sans réseau ni coût).
- L'annulation passe par l'annulation de la tâche asyncio (déconnexion SSE), qui ferme le flux HTTP.

### 3.4 Autres points du design existant

- **A5 (intention au premier tour)** : compatible, mais **sans choix forcé d'outil**. Il faut une règle de prompt (« ta première action est soit un outil de données, soit `clarify`, soit `refuse` ») et une vérification par le code : une réponse en texte seul est une violation de protocole, qui donne lieu à un nouvel essai puis à un repli.
- **« 6 derniers échanges »** avec la réflexion préservée : ne pas rejouer les blocs `thinking` d'une question à l'autre. Chaque question part d'un **nouveau tableau `messages`** : historique compacté en texte, état résolu, question. Dans la boucle, l'historique est **en ajout seul** et les blocs `thinking` sont renvoyés tels quels. La fenêtre glissante ne casse donc rien, puisqu'aucun bloc n'est lié à l'historique tronqué.
- **Données non fiables** : les résultats vont dans des blocs `tool_result` (canal prévu par l'API). Ne pas mettre de « rappels opérateur » dans un `tool_result` ni juste après : la doc de Sonnet 5.5 note que le modèle peut lire un texte placé là comme une injection.
- Le squelette du backend (`api/backend/pyproject.toml`) inclut Redis, taskiq et memcached, ce qui contredit « pas de cache distribué » (SYSTEM_DESIGN §1). Hors périmètre LLM, à trancher séparément.

---

## 4. Design concret

### 4.1 Structure de la requête

```
tools   : [get_kpi, describe_table, run_query, clarify, refuse, final_answer]   (ordre fixe, JSON trié)
system  : [ bloc 1 : rôle, règles, politique d'intention, format          ]
          [ bloc 2 : couche sémantique (tables, kpis, glossaire, exemples)   ] ← cache_control {ephemeral, ttl: 1h}
messages: [ user : <contexte>REFERENCE_DATE, rôle, état résolu</contexte>
                   <historique>6 échanges compactés</historique>
                   <question>…</question> ]
          [ assistant : thinking + tool_use ]  [ user : tool_result … ]  …  (ajout seul)
cache_control (niveau supérieur) : {type: ephemeral}  → cache automatique de 5 min sur la boucle
```

Règles de stabilité (prompt-caching, « silent invalidators ») :
- Rien de variable dans `system` : **pas de date du jour**. `REFERENCE_DATE` et le rôle vont dans le premier message `user`, après le point de cache.
- La couche sémantique est sérialisée de façon déterministe (YAML vers texte canonique, clés triées) et son hash vaut `semantic_version`.
- Une seule valeur d'`effort` par modèle et par route : la changer invalide le cache.
- Le jeu d'outils est **le même pour toutes les requêtes** d'une route. Pour les ablations « sans `get_kpi` », on accepte un préfixe différent : c'est une autre configuration, avec son propre cache.
- Vérification en CI : deux requêtes identiques successives doivent donner `cache_read_input_tokens` > 0, et `count_tokens` doit placer le préfixe dans le budget (par exemple ≤ 16 k).

### 4.2 Appel (Python, SDK `anthropic` ≥ 2.0)

```python
import anthropic, time
client = anthropic.AsyncAnthropic(max_retries=0, timeout=20.0)   # relances gérées par la boucle

async def step(req: LLMRequest) -> LLMStep:
    t0 = time.monotonic(); ttft = None
    async with client.messages.stream(
        model=req.model,
        max_tokens=req.max_tokens,                 # 8 000 : réflexion + sortie
        system=req.system,                         # le dernier bloc porte cache_control ttl=1h
        tools=req.tools,                           # strict: True ; eager_input_streaming laissé à False
        tool_choice={"type": "auto"},
        messages=req.messages,
        output_config={"effort": req.effort},
        cache_control={"type": "ephemeral"},       # cache automatique du reste (5 min)
    ) as stream:
        async for ev in stream:
            if ttft is None and ev.type == "content_block_start":
                ttft = time.monotonic() - t0
                # émettre l'événement d'étape « outil en cours » quand ev.content_block.type == "tool_use"
        msg = await stream.get_final_message()
    ...
```

- Ne pas activer `eager_input_streaming` : il désactive la validation côté API, ce qui annule la garantie de `strict`, et les entrées sont courtes.
- `stop_reason` est contrôlé **avant** de lire le contenu : `refusal` donne un `AssistantMessage(kind="refusal")` neutre, `max_tokens` donne un nouvel essai avec une limite plus haute ou un repli.
- Fallback de refus : `fallbacks: "default"` (bêta `server-side-fallback-2026-07-01`) sur Sonnet et Opus. Journaliser `model_served`, et en évaluation compter ces cas à part : une réponse donnée par un autre modèle n'est pas une réponse de Sonnet.

### 4.3 Outils (`strict: true`, `additionalProperties: false`, tout en `required`)

Limite à respecter : au plus 24 paramètres optionnels et 16 en `anyOf`. On rend tout **requis**, avec des valeurs sentinelles (`"none"`, liste vide) plutôt que des `null`.

```jsonc
{"name": "get_kpi", "strict": true,
 "description": "Chemin prioritaire. Calcule un KPI défini dans kpis.yaml avec SQL validé et paramètres liés. Utiliser pour toute question qui correspond à un KPI. Appels parallèles autorisés (ex. deux périodes).",
 "input_schema": {"type": "object", "additionalProperties": false,
   "required": ["kpi", "date_from", "date_to", "region_role", "region_ids", "txn_type", "active_window_days"],
   "properties": {
     "kpi": {"type": "string", "enum": ["volume_transactions", "valeur_transferee", "revenus_frais", "clients_actifs", "agents_actifs", "taux_echec"]},
     "date_from": {"type": "string", "format": "date"},
     "date_to":   {"type": "string", "format": "date"},
     "region_role": {"type": "string", "enum": ["agent", "client", "none"]},
     "region_ids": {"type": "array", "items": {"type": "integer"}},
     "txn_type": {"type": "string", "enum": ["tous", "depot", "retrait", "transfert", "paiement"]},
     "active_window_days": {"type": "integer"}            // borne 1..365 vérifiée côté code (minimum non supporté)
   }}}

{"name": "describe_table", "strict": true,
 "input_schema": {"type": "object", "additionalProperties": false, "required": ["table"],
   "properties": {"table": {"type": "string", "enum": ["fact_transaction", "dim_client", "dim_agent", "dim_region", "dim_date"]}}}}

{"name": "run_query", "strict": true,
 "description": "SELECT Postgres en lecture seule sur analytics.* (tables qualifiées). Passe par le garde SQL. Retourne au plus 50 lignes d'aperçu + statistiques ; le résultat complet est conservé par le serveur sous result_id.",
 "input_schema": {"type": "object", "additionalProperties": false, "required": ["sql", "purpose"],
   "properties": {"sql": {"type": "string"}, "purpose": {"type": "string"}}}}

{"name": "clarify", "strict": true,                                   // terminal
 "input_schema": {"type": "object", "additionalProperties": false, "required": ["question", "missing", "choices"],
   "properties": {"question": {"type": "string"},
     "missing": {"type": "array", "items": {"type": "string", "enum": ["periode", "perimetre", "kpi", "region_client_ou_agent", "autre"]}},
     "choices": {"type": "array", "items": {"type": "string"}}}}}  // 2-3 choix vérifiés côté code

{"name": "refuse", "strict": true,                                    // terminal
 "input_schema": {"type": "object", "additionalProperties": false, "required": ["category", "reason"],
   "properties": {"category": {"type": "string", "enum": ["hors_modele", "modification", "contournement", "autre"]},
                  "reason": {"type": "string"}}}}

{"name": "final_answer", "strict": true,                              // terminal
 "input_schema": {"type": "object", "additionalProperties": false,
   "required": ["text", "period", "scope", "result_ids", "cited_numbers", "resolved_state", "caveats"],
   "properties": {
     "text": {"type": "string"}, "period": {"type": "string"}, "scope": {"type": "string"},
     "result_ids": {"type": "array", "items": {"type": "string"}},     // résultats d'outils qui fondent la réponse
     "cited_numbers": {"type": "array", "items": {"type": "string"}},  // nombres cités, contrôlés par le validateur
     "caveats": {"type": "array", "items": {"type": "string", "enum": ["truncated", "empty", "default_period", "region_assumed"]}},
     "resolved_state": {"type": "object", "additionalProperties": false,
       "required": ["kpi", "periode", "perimetre", "filtres"],
       "properties": {"kpi": {"type": "string"}, "periode": {"type": "string"},
                      "perimetre": {"type": "string"}, "filtres": {"type": "array", "items": {"type": "string"}}}}}}}
```

- **Le LLM ne recopie ni les lignes, ni le SQL, ni le graphique.** Le formateur construit `table`, `chart`, `tables` et `sql` (rôle analyste) à partir de `result_ids`. On gagne en jetons de sortie et en latence, et une source d'hallucination disparaît. Le contrat `AssistantMessage` de SYSTEM_DESIGN §5 reste inchangé côté interface.
- Un outil terminal doit être **seul** dans son tour. Sinon, on renvoie une erreur `is_error` au modèle et on lui laisse un nouvel essai.
- Erreur d'outil : `tool_result` avec `is_error: true` et l'erreur Postgres normalisée (classe d'erreur, sans noms d'objets). Tous les `tool_result` d'un tour sont rendus dans **un seul** message `user`.
- `list_tables` est retiré des outils exposés (le schéma est déjà en contexte ; RF8 reste couvert par `describe_table`). S'il est gardé pour le SRS §8, il doit être présent dès le début : ajouter un outil en cours de route casse le préfixe.

### 4.4 Gestion des erreurs et relances (respect de l'échéance de 30 s)

| Cas | Détection | Action |
|---|---|---|
| 429 limite de débit | `anthropic.RateLimitError`, en-tête `retry-after` | Si `retry-after` est inférieur au temps restant moins 5 s : attendre puis 1 essai. Sinon, message clair « service saturé ». |
| 429 plafond de dépenses | `error.details.error_code == "enforced_spend_limit_reached"`, pas de `retry-after` | **Aucun essai.** Alerte admin (RF20) et message clair. |
| 400 limite de dépenses du workspace | `BadRequestError`, message « specified API usage limits » | Idem, sans nouvel essai. |
| 529 surcharge, 500, 504, erreur réseau | `InternalServerError` (statut ≥ 500), `APIConnectionError`, `APITimeoutError` | 1 nouvel essai après 0,5 à 1,5 s (gigue), si le budget le permet. Sinon, erreur explicite (AGENTIC §10). |
| Erreur en cours de flux (SSE `error` après 200) | Exception du flux | Traité comme un 529 : nouvel essai de l'**étape** entière. |
| 400 de validation (`tool_choice`, réflexion, préfixe modifié) | `BadRequestError` | Bug : aucun essai, journalisation `error_class=llm_bad_request` et alerte. |
| `stop_reason == "refusal"` | 200 | Refus neutre. `refusal_category` est journalisée. |
| `stop_reason == "max_tokens"` | 200 | 1 nouvel essai avec `max_tokens` × 2, puis repli. |
| Texte sans outil terminal | Contenu | 1 nouvel essai avec un texte de rappel ajouté (« termine par final_answer, clarify ou refuse »), puis repli. |
| Sortie de `final_answer` refusée par le validateur | Code | 1 nouvel essai avec le motif dans un `tool_result` `is_error`, puis repli honnête (AGENTIC §7). |

- Le SDK est configuré avec `max_retries=0` en production, car les 2 essais par défaut peuvent dépasser 30 s. Pour `make eval`, on peut être plus patient (3 à 5 essais, attente jusqu'à 30 s), mais une **exécution relancée est marquée** et sa latence publiée à part.
- Timeout du SDK : 20 s par appel. Le budget restant est passé à chaque étape.

### 4.5 Budget de jetons par question

| Garde-fou | Valeur initiale |
|---|---|
| Étapes LLM | ≤ 6 (dont ≤ 2 corrections SQL) |
| `max_tokens` par appel | 8 000 (la réflexion compte dedans) |
| Résultat d'outil envoyé au LLM | ≤ 50 lignes, ≤ 4 000 jetons (texte libre exclu) ; le reste est référencé par `result_id` |
| Entrée cumulée (hors lectures de cache) | ≤ 40 000 jetons |
| Sortie cumulée | ≤ 6 000 jetons |
| Coût | ≤ 0,10 $ (Sonnet), à recalibrer après P1 |
| Historique | 6 échanges compactés (≤ 1 500 jetons), état résolu inclus |

Le budget de tâche (`task_budget`, bêta, minimum 20 k) n'est pas utile : les plafonds du code suffisent.

### 4.6 Mode analyse du tableau de bord (RF17)

1. Le **code** appelle `get_kpi` pour les 6 KPI × {période, période précédente} × région, sans LLM, et calcule les dérivés (variations, écarts en points).
2. Un seul appel LLM : `output_config.format` avec le schéma `{lead, constats[≤3]{tag, text, confidence, sources[]}, follow[]}`, et les données en JSON dans le message `user`. Pas d'outils.
3. Validateur : chaque nombre de `text` doit appartenir à l'ensemble {sorties `get_kpi`, dérivés calculés} ; toute phrase causale doit porter `confidence = "hypothese"`.
4. Le résultat est stocké dans `app.analysis`. Coût d'environ 6 k jetons en entrée et 900 en sortie, soit **0,021 $ (Sonnet)** ou 0,001 $ (Haiku).

Cette version respecte « `get_kpi` seul » plus strictement qu'une boucle d'outils : le modèle ne choisit même pas les appels. Elle est aussi plus rapide (un appel) et plus facile à évaluer.

### 4.7 Journalisation dans `query_log`

La table actuelle a `tokens_in`, `tokens_out` et `tokens_cached`, avec une ligne par appel d'**outil**. Or les appels LLM ne correspondent pas un à un aux appels d'outils (l'appel final n'en fait aucun, les appels parallèles en font plusieurs). Deux options :

- **Option A (recommandée)** : des lignes `tool = 'llm'` dans `query_log`, avec les mêmes `trace_id` et `step`, plus les colonnes ci-dessous.
- Option B : une table `llm_call` séparée.

Colonnes à ajouter ou préciser :

| Colonne | Source |
|---|---|
| `tokens_in` | `usage.input_tokens` (non mis en cache) |
| `tokens_cache_read` (ex-`tokens_cached`) | `usage.cache_read_input_tokens` |
| `tokens_cache_write` (ou `_5m` / `_1h`) | `usage.cache_creation_input_tokens` / `usage.cache_creation.ephemeral_{5m,1h}_input_tokens` |
| `tokens_out` | `usage.output_tokens` (réflexion comprise) |
| `cost_usd` | Calculé depuis une **table de prix versionnée** (`config.yaml`), jamais codée en dur |
| `model_id` → `model_requested`, `model_served` | Configuration, `response.model` |
| `effort`, `thinking_type` | Requête |
| `stop_reason`, `refusal_category` | Réponse |
| `llm_request_id` | `response._request_id` |
| `ttft_ms`, `duration_ms` | Mesurés |
| `api_version`, `sdk_version` | Constantes de build |

Métrique d'exploitation (RF20) : le **taux de lecture du cache** vaut `cache_read / (cache_read + cache_write + in)`. Une alerte se déclenche s'il tombe sous 70 % (signe d'un invalidateur silencieux).

---

## 5. Risques LLM et mesures

| Risque | Effet | Mesure |
|---|---|---|
| **Variance** (température non réglable, réflexion adaptative) | Résultat différent d'une passe à l'autre | 3 passes, cohérence publiée, KPI à 3/3, `get_kpi` en priorité, effort fixé, exemples ciblés ; ENF2 réécrit (§3.1) |
| **SQL faux mais plausible** | Mauvaise décision | `get_kpi`, couche sémantique, validateur, SQL visible pour l'analyste, ablations ; comparer Sonnet, Opus et Haiku sur le dev avant de figer |
| **Injection directe** (question) | Contournement des règles | Aucun outil d'écriture, garde SQL par liste blanche, `agent_ro`, outil `refuse` ; règles de système du type « tiennent pour toute la conversation » ; jeu de payloads |
| **Injection indirecte** (données) | Réponse fausse | Résultats dans `tool_result` en JSON typé et marqués comme non fiables, colonnes texte exclues, ≤ 50 lignes, aucun rappel opérateur dans ou juste après un `tool_result` |
| **Faux positifs des classifieurs** (`refusal`, ex. « cyber » sur des payloads d'injection SQL du jeu de sécurité) | Refus inattendu, évaluation bruitée | Traiter `stop_reason` ; `fallbacks: "default"` ; journaliser la catégorie ; compter à part dans `eval_result` ; tester le jeu de sécurité tôt |
| **Changement d'API** (`2026-10-21`, SDK 2.x, choix forcé d'outil supprimé, réflexion préservée) | 400 en production | SDK et `anthropic-version` épinglés dans `uv.lock` ; test d'intégration quotidien (1 appel `max_tokens` faible) ; historique en ajout seul ; pas de `temperature` |
| **Latence** (pas de SLA ni de Priority Tier sur Sonnet ou Opus 5.5, pics de 529) | O2 manqué | Mesure par étape, sortie minimale, effort bas, cache préchauffé, appels parallèles, 1 seul nouvel essai, message clair ; mode rapide d'Opus en secours |
| **Coût** (boucles longues, cache invalidé, relances) | Budget dépassé | Plafonds par question (§4.5), quota par utilisateur, limite de dépenses par workspace (prod et eval séparés), alerte sur le taux de cache, coût suivi dans le back-office |
| **Plafond du palier** (500 $/mois, Start) | API coupée jusqu'au mois suivant | Limite de workspace inférieure ; alerte à 50 et 80 % ; distinguer `enforced_spend_limit_reached` |
| **Dépendance au fournisseur** | Blocage si l'accès est coupé ou si le modèle est retiré | `LLMClient` + `ReplayClient` ; logique métier (garde, `get_kpi`, validateur, formateur) indépendante du LLM ; mêmes modèles disponibles sur Bedrock, Vertex et Foundry ; retrait au plus tôt en 09/2027 |
| **Confidentialité** (questions et résultats envoyés aux États-Unis ou en routage global) | Non conforme pour des données réelles (loi sénégalaise 2008-12, transfert hors du pays) | Données synthétiques uniquement ; pas de texte libre ; pas de Batch, Files ni connecteur MCP pour des données réelles ; pas de Fable (rétention de 30 jours) ; demander la ZDR si besoin ; avant toute bascule réelle, passer par un point de terminaison régional (Bedrock/Vertex UE) et faire une analyse d'impact |
| **Fuite du prompt ou de la couche sémantique** | Faible (aucun secret dedans) | Aucun secret ni donnée personnelle dans les prompts ; schémas stricts sans données sensibles (cache de grammaire de 24 h) |
| **Fuite exemples → test** | Score gonflé | Déjà couvert (SQL normalisé, hash figé) ; inclure le **texte des exemples dans le hash du préfixe** tracé |

---

## 6. Décisions proposées (ADR)

| N° | Décision | Raison | Écarté |
|---|---|---|---|
| L1 | `claude-sonnet-5-5`, effort `medium` (balayage `low`), pour l'agent ; Opus 5.5 et Haiku 5.5 en challengers sur le dev | Latence « rapide », coût de 0,02 $/question ; choix final fondé sur la mesure | Opus par défaut (risque O2), Fable (coût, rétention) |
| L2 | Boucle manuelle sur `messages.stream`, SDK `anthropic` ≥ 2.0 épinglé | Échéance, annulation, journalisation par étape | Tool Runner (bêta), Agent SDK |
| L3 | Outils stricts, `tool_choice: auto`, outils terminaux `clarify`, `refuse` et `final_answer` | Le choix forcé d'outil est refusé (400) ; le schéma reste garanti | `tool_choice: tool`, préremplissage |
| L4 | `final_answer` sans données : référence aux `result_ids`, et rendu par le code | Moins de jetons et de latence, pas d'hallucination de lignes | Table recopiée par le LLM |
| L5 | Préfixe de ~12 k jetons en cache 1 h, préchauffé ; boucle en cache automatique de 5 min | Coût ÷4, TTFT réduit, l'ITPM n'est pas consommé | Pas de cache |
| L6 | Pas de température ; reproductibilité par snapshot, effort, hashes et 3 passes | Paramètre supprimé par l'API | Température 0 |
| L7 | Client MCP local (stdio), schémas d'outils déclarés dans l'agent | Connecteur MCP public et hors ZDR | Connecteur MCP de l'API |
| L8 | Analyse du tableau de bord en un appel à sortie structurée, KPI récupérés par le code | Traçabilité, latence, évaluation | Boucle d'outils `get_kpi` |
| L9 | Batch API réservée au juge optionnel et à RF17, sur données synthétiques | Boucle multi-tours incompatible ; 29 jours de rétention | Batch pour toute l'évaluation |
| L10 | Workspaces prod et eval séparés, avec limites de dépenses propres | Isolation du cache et du budget | Workspace unique |

## 7. Actions P1, dans l'ordre

1. `count_tokens` sur le préfixe réel (Sonnet, Opus, Haiku), puis mise à jour du §2.3.
2. `AnthropicClient` + `ReplayClient`, migration `query_log` (colonnes du §4.7).
3. Banc de latence : 20 questions du dev × 3 modèles × effort `low`/`medium`, pour mesurer TTFT, débit et p50/p90.
4. Comparatif de justesse sur le dev (~6 $), puis choix L1 définitif.
5. Réécriture d'ENF2 et d'AGENTIC §9 (température et identifiant daté), et précision d'O2 (« sans cache » = sans cache de réponses).
