"""Écrit web/src/api/openapi.json : l'OpenAPI de l'API complétée des contrats de decision_core.

Les types TypeScript de l'interface en sont générés (`make web-api-types`). Les contrats de `decision_core`
(AssistantMessage, StepEvent…) ne figurent pas dans les routes JSON classiques (flux SSE) : on les ajoute
aux schémas pour que le front les importe depuis un seul endroit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from decision_api.main import create_app
from decision_core import models

EXTRA = (
    "AssistantMessage",
    "StepEvent",
    "DashboardAnalysis",
    "ResolvedState",
    "Fact",
    "EvidenceStep",
    "Chart",
    "TableData",
    "ColumnInfo",
    "PendingClarification",
)


def build() -> dict:
    spec = create_app().openapi()
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})
    for name in EXTRA:
        schema = getattr(models, name).model_json_schema(ref_template="#/components/schemas/{model}")
        for key, value in schema.pop("$defs", {}).items():
            schemas.setdefault(key, value)
        schemas[name] = schema
    return spec


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "web/src/api/openapi.json")
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"écrit : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
