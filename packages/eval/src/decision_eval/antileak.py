"""Anti-fuite entre les exemples du prompt (semantic/examples.yaml) et le jeu de test, et hash figé.

- SQL normalisé (sqlglot, dialecte postgres, identifiants en minuscules, commentaires retirés) ;
- squelette de requête : littéraux remplacés par `?`, alias de colonnes retirés, alias de tables
  remplacés par le nom de la table ; deux requêtes qui ne diffèrent que par leurs constantes
  (dates, régions, LIMIT) ont le même squelette ;
- échec si un SQL normalisé OU un squelette du test apparaît dans les exemples, ou si une question
  du test (texte normalisé) y apparaît ;
- dev/test : question ou SQL normalisé communs = échec ; squelette commun = simple avertissement ;
- MANIFEST : `sha256sum`-compatible (`<hex>  test.yaml`) ; le runner refuse de tourner sur le test
  si le hash ne correspond pas.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlglot
import yaml
from sqlglot import exp

from .compare import norm_text
from .dataset import Dataset, EvalItem, eval_dir, load_dataset, repo_root, sha256_file

MANIFEST_NAME = "MANIFEST"
FROZEN_FILES = ("test.yaml",)


class ManifestError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------------
# Normalisation SQL
# --------------------------------------------------------------------------------------------


def _parse(sql: str) -> exp.Expression:
    tree = sqlglot.parse_one(sql, read="postgres")
    if not isinstance(tree, exp.Expression):
        raise ValueError("SQL vide")
    return tree


def normalize_sql(sql: str) -> str:
    """SQL canonique : réécrit par sqlglot, identifiants en minuscules, sans commentaires."""
    return _parse(sql).sql(dialect="postgres", normalize=True, comments=False)


def skeleton_sql(sql: str) -> str:
    """Squelette : littéraux → ?, alias de colonnes retirés, alias de tables → nom de table."""
    tree = _parse(sql).copy()
    alias_to_table: dict[str, str] = {}
    for t in tree.find_all(exp.Table):
        if t.alias:
            alias_to_table[t.alias.lower()] = t.name.lower()

    def rewrite(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Literal):
            return exp.Placeholder()
        if isinstance(node, exp.Boolean):
            return exp.Placeholder()
        if isinstance(node, exp.Table) and node.alias:
            table = node.copy()
            table.set("alias", None)
            return table
        if isinstance(node, exp.Column) and node.table and node.table.lower() in alias_to_table:
            col = node.copy()
            col.set("table", exp.to_identifier(alias_to_table[node.table.lower()]))
            return col
        if isinstance(node, exp.Alias) and isinstance(node.parent, exp.Select):
            return node.this.copy()
        return node

    tree = tree.transform(rewrite)
    return tree.sql(dialect="postgres", normalize=True, comments=False)


# --------------------------------------------------------------------------------------------
# Extraction depuis les jeux et les exemples
# --------------------------------------------------------------------------------------------


def item_sqls(item: EvalItem) -> list[str]:
    sqls = [item.reference_sql] if item.reference_sql else []
    for t in item.turns or []:
        if t.answer and t.answer.reference_sql:
            sqls.append(t.answer.reference_sql)
    return sqls


def item_questions(item: EvalItem) -> list[str]:
    if item.question is not None:
        return [item.question]
    return [t.question for t in item.turns or []]


def _walk(node: Any, key: str | None = None) -> Iterator[tuple[str | None, Any]]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, key)
    else:
        yield key, node


SQL_KEYS = {"sql", "query", "reference_sql"}
QUESTION_KEYS = {"question", "user", "q", "prompt"}


def examples_content(examples: Any) -> tuple[list[str], list[str]]:
    """(SQL, questions) trouvés dans examples.yaml, quelle que soit sa structure exacte."""
    sqls, questions = [], []
    for k, v in _walk(examples):
        if not isinstance(v, str) or k is None:
            continue
        if k.lower() in SQL_KEYS:
            sqls.append(v)
        elif k.lower() in QUESTION_KEYS:
            questions.append(v)
    return sqls, questions


# --------------------------------------------------------------------------------------------
# Contrôles
# --------------------------------------------------------------------------------------------


@dataclass
class AntileakReport:
    exact: list[str] = field(default_factory=list)  # ids du test dont le SQL normalisé est dans les exemples
    skeleton: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    dev_overlap: list[str] = field(default_factory=list)  # question ou SQL exact commun dev/test
    dev_skeleton_warnings: list[str] = field(default_factory=list)
    unparsable: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.exact or self.skeleton or self.questions or self.dev_overlap or self.unparsable)

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["ok"] = self.ok
        return d


def _sig(sqls: Iterable[str], fn: Any, bad: list[str], label: str) -> set[str]:
    out = set()
    for s in sqls:
        try:
            out.add(fn(s))
        except Exception:  # noqa: BLE001 - un SQL illisible est signalé, pas propagé
            bad.append(label)
    return out


def check_antileak(test: Dataset, examples: Any, dev: Dataset | None = None) -> AntileakReport:
    rep = AntileakReport()
    ex_sqls, ex_questions = examples_content(examples)
    ex_norm = _sig(ex_sqls, normalize_sql, rep.unparsable, "examples.yaml")
    ex_skel = _sig(ex_sqls, skeleton_sql, [], "examples.yaml")
    ex_q = {norm_text(q) for q in ex_questions}

    dev_q: set[str] = set()
    dev_norm: set[str] = set()
    dev_skel: set[str] = set()
    if dev is not None:
        for it in dev.items:
            dev_q.update(norm_text(q) for q in item_questions(it))
            dev_norm |= _sig(item_sqls(it), normalize_sql, rep.unparsable, f"dev:{it.id}")
            dev_skel |= _sig(item_sqls(it), skeleton_sql, [], f"dev:{it.id}")

    for it in test.items:
        norms = _sig(item_sqls(it), normalize_sql, rep.unparsable, f"test:{it.id}")
        skels = _sig(item_sqls(it), skeleton_sql, [], f"test:{it.id}")
        qs = {norm_text(q) for q in item_questions(it)}
        if norms & ex_norm:
            rep.exact.append(it.id)
        if skels & ex_skel:
            rep.skeleton.append(it.id)
        if qs & ex_q:
            rep.questions.append(it.id)
        if dev is not None:
            final_q = norm_text(it.final_question)
            if final_q in dev_q or (norms & dev_norm):
                rep.dev_overlap.append(it.id)
            elif skels & dev_skel:
                rep.dev_skeleton_warnings.append(it.id)
    return rep


def run_antileak(base: Path | None = None, semantic_dir: Path | None = None) -> AntileakReport:
    base = base or eval_dir()
    sem = semantic_dir or (repo_root() / "semantic")
    test = load_dataset(base / "test.yaml")
    dev_path = base / "dev.yaml"
    dev = load_dataset(dev_path) if dev_path.exists() else None
    ex_path = sem / "examples.yaml"
    examples = yaml.safe_load(ex_path.read_text(encoding="utf-8")) if ex_path.exists() else {}
    return check_antileak(test, examples or {}, dev)


# --------------------------------------------------------------------------------------------
# MANIFEST
# --------------------------------------------------------------------------------------------


def read_manifest(base: Path | None = None) -> dict[str, str]:
    path = (base or eval_dir()) / MANIFEST_NAME
    if not path.exists():
        raise ManifestError(f"{path} absent : le jeu de test n'est pas figé")
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        out[name.strip()] = digest.strip()
    return out


def verify_manifest(base: Path | None = None) -> str:
    """Vérifie le hash de test.yaml ; renvoie le hash ou lève ManifestError."""
    base = base or eval_dir()
    manifest = read_manifest(base)
    for name in FROZEN_FILES:
        if name not in manifest:
            raise ManifestError(f"{name} absent du MANIFEST")
        actual = sha256_file(base / name)
        if actual != manifest[name]:
            raise ManifestError(
                f"hash de {name} différent du MANIFEST ({actual[:12]}… ≠ {manifest[name][:12]}…) : "
                "le jeu de test a été modifié après avoir été figé"
            )
    return manifest[FROZEN_FILES[0]]


def freeze_manifest(base: Path | None = None, *, force: bool = False) -> str:
    base = base or eval_dir()
    path = base / MANIFEST_NAME
    if path.exists() and not force:
        raise ManifestError(f"{path} existe déjà ; --force pour refiger (nouvelle version du jeu)")
    lines: list[str] = []  # format sha256sum : cd eval && sha256sum -c MANIFEST
    for name in FROZEN_FILES:
        lines.append(f"{sha256_file(base / name)}  {name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines[0].split()[0]
