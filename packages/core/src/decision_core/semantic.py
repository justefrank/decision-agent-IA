"""Chargement de la couche sémantique (semantic/*.yaml) et calcul de sa version (hash)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

FILES = ("tables.yaml", "kpis.yaml", "glossary.yaml", "examples.yaml", "config.yaml")


def default_semantic_dir() -> Path:
    """Dossier `semantic/` à la racine du dépôt, surchargeable par SEMANTIC_DIR."""
    import os

    env = os.environ.get("SEMANTIC_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "semantic" / "kpis.yaml").exists():
            return parent / "semantic"
    raise FileNotFoundError("Dossier semantic/ introuvable ; définir SEMANTIC_DIR.")


@dataclass(frozen=True)
class SemanticLayer:
    tables: dict[str, Any]
    kpis: dict[str, Any]
    glossary: dict[str, Any]
    examples: dict[str, Any]
    config: dict[str, Any]
    version: str  # sha256 tronqué du contenu canonique, enregistré dans chaque trace
    raw: dict[str, str] = field(repr=False, default_factory=dict)

    @property
    def metrics(self) -> dict[str, Any]:
        return self.kpis["metrics"]

    @property
    def dimensions(self) -> dict[str, Any]:
        return self.kpis["dimensions"]

    @property
    def allowed_tables(self) -> frozenset[str]:
        schema = self.tables["schema"]
        return frozenset(f"{schema}.{name}" for name in self.tables["tables"])

    def canonical_text(self, *, include_examples: bool = True) -> str:
        """Texte déterministe (clés triées) injecté dans le préfixe mis en cache du prompt."""
        parts = {"tables": self.tables, "kpis": self.kpis, "glossary": self.glossary}
        if include_examples:
            parts["examples"] = self.examples
        return yaml.safe_dump(parts, allow_unicode=True, sort_keys=True, width=120)


def _canonical_hash(docs: dict[str, Any]) -> str:
    blob = json.dumps(docs, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def load_semantic(directory: Path | str | None = None) -> SemanticLayer:
    root = Path(directory) if directory else default_semantic_dir()
    docs: dict[str, Any] = {}
    raw: dict[str, str] = {}
    for name in FILES:
        path = root / name
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        raw[name] = text
        docs[name.removesuffix(".yaml")] = yaml.safe_load(text) or {}
    return SemanticLayer(
        tables=docs["tables"],
        kpis=docs["kpis"],
        glossary=docs["glossary"],
        examples=docs["examples"],
        config=docs["config"],
        version=_canonical_hash(docs),
        raw=raw,
    )


@lru_cache(maxsize=1)
def get_semantic() -> SemanticLayer:
    return load_semantic()
