# decision-agent

Agent IA (Claude) du backend MVP v5 : boucle bornée à outils contraints, registre de faits, validateur
déterministe, formateur français et analyse du tableau de bord en workflow. Références :
`docs/reviews/2026-10-24-agentic-design.md` §3 et `docs/reviews/2026-10-24-llm-claude.md` §3-§4.

## Modules (`src/decision_agent/`)

| Module | Rôle |
|---|---|
| `loop.py` | `Agent(llm, tools, semantic, settings).answer(...)` : 6 appels LLM, 8 appels d'outils, 2 corrections SQL par requête, 1 nouvel essai du validateur, 30 s (délai propagé aux outils), plafond de coût (`config.yaml` `agent.cost_cap_usd`). Message système « réponds maintenant » au dernier tour, `stop_reason` refusal/max_tokens, appels parallèles regroupés dans un seul message `tool_result`, historique en ajout seul. Un `QueryLogRecord` par appel d'outil et par appel LLM, des `StepEvent` pour le flux SSE. |
| `llm.py` | `LLMClient` (format natif Anthropic, blocs `thinking` rejoués tels quels), `AnthropicClient` (SDK `anthropic` 2.x, `max_retries=0`, flux pour le TTFT, `output_config.effort`, `thinking: adaptive`, aucun paramètre d'échantillonnage, `fallbacks: "default"` désactivable), `ScriptedClient`/`ReplayClient`, table de prix versionnée (`PRICING_VERSION`). |
| `tools.py` | Schémas des 6 outils Claude (`strict`, `additionalProperties: false`, tout `required`), `ToolClient`, `McpToolClient.start(settings)` (sous-processus stdio, env restreint à `AGENT_RO_DSN`, `SEMANTIC_DIR`, `REFERENCE_DATE`, `PATH`), `FakeToolClient`. |
| `facts.py` | Registre `f…` (cellules de l'aperçu, totaux, nombre de lignes) et `d…` (écart, variation %, écart en points, part), vue du modèle limitée à `rows_to_llm` lignes, étiquettes opaques `A1…` pour `nom`/`ville`, mention « données non fiables ». |
| `validator.py` | Références, extracteur de littéraux FR (séparateurs, échelles, %, pts), appariement à la demi-unité, années/dates/rangs tolérés, total sur résultat tronqué interdit, résultat vide signalé, marqueurs causaux hors « Hypothèse : ». |
| `formatting.py` | Rendu FR (espace fine insécable, « 1,23 milliard FCFA », % à une décimale, pts), graphique choisi par la forme du résultat, chaîne de preuve, `template_answer` (repli juste par construction). |
| `state.py` | État résolu produit par le code (`query_metric` ou `scope` de l'AST), étiquettes `explicite`/`herite`/`defaut`, `resolve_clarification_reply` déterministe, politique par champ. |
| `periods.py` | Périodes relatives à `REFERENCE_DATE`, période précédente / année précédente, libellés (« mars 2026 », « T2 2026 », « du 1er au 15 mars 2026 »). |
| `prompts.py` | Prompt système stable + couche sémantique (`cache_control` 1 h), `prompt_version` (hash), contexte variable du tour (date, rôle, état, 6 échanges compactés). |
| `dashboard.py` | `fetch_dashboard` (6 KPI, période courante et précédente, dérivés) et `run_dashboard_analysis` (constats candidats par règles versionnées `analysis_rules.yaml`, un appel LLM sans outil en `output_config.format`, validateur, « analyse indisponible » en cas d'échec). |
| `testing.py` | Fabriques de `ToolResult` pour les tests (agent, évaluation). |

## Choix notables

- `query_metric` côté modèle accepte `period.kind = absolute | relative | defaut` ; le code résout la période
  (libellé compris) et envoie au serveur MCP un `QueryMetricParams` conforme au contrat.
- Le modèle ne fournit aucun nombre : `submit_answer` = texte à gabarits, `result_ids`, `caveats`,
  `follow_up`. Tableau, graphique, période, périmètre, SQL et caveats de défaut sont produits par le code.
- Clarification : une seule par question d'origine ; la réponse courte est résolue sans LLM puis la question
  d'origine est rejouée avec le champ fixé.

## Lancer

```bash
uv sync --all-packages
uv run pytest packages/agent -q          # sans clé API ni Postgres
uv run ruff check packages/agent
ANTHROPIC_API_KEY=... uv run pytest packages/agent/tests/test_integration_api.py   # API réelle (optionnel)
AGENT_RO_DSN=postgresql://agent_ro:agent_ro@localhost:55430/warehouse uv run pytest packages/agent -m db
```

Utilisation :

```python
async with McpToolClient.start(settings) as tools:
    agent = Agent(AnthropicClient.from_settings(settings), tools, get_semantic(), settings)
    msg = await agent.answer(question, history=[], state=None, role="analyste", trace_id=tid,
                             on_event=send_step, on_log=write_log)
    payload = msg.for_role(role)
```
