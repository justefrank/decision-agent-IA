# decision-core

Contrats partagés entre le serveur MCP, l'agent, l'API et l'évaluation (module `decision_core`).

| Module | Contenu |
|---|---|
| `models.py` | `QueryMetricParams`, `ToolResult` (avec `ColumnInfo.free_text`), `ResolvedState`, `Fact`, `AssistantMessage` (`for_role` retire le SQL pour le décideur), `StepEvent`, `DashboardAnalysis`, `QueryLogRecord`, `HistoryItem` |
| `semantic.py` | `load_semantic()` / `get_semantic()` : lit `semantic/*.yaml` et calcule `semantic_version` (hash du contenu canonique, enregistré dans chaque trace) |
| `settings.py` | `Settings` / `get_settings()` : variables d'environnement (DSN par rôle, Claude, Keycloak, `REFERENCE_DATE`) |

Un changement de ces contrats touche tous les paquets : le faire dans une PR dédiée, tests de tous les paquets verts.
