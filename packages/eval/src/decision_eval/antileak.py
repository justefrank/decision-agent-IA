"""Anti-fuite entre les exemples du prompt (semantic/examples.yaml) et le jeu de test, et hash figé.

- SQL normalisé (sqlglot, dialecte postgres, identifiants en minuscules, commentaires retirés) ;
- squelette de requête : littéraux remplacés par `?`, alias de colonnes retirés, alias de tables
  remplacés par le nom de la table ; deux requêtes qui ne diffèrent que par leurs constantes
  (dates, régions, LIMIT) ont le même squelette ;
- échec si un SQL normalisé OU un squelette du test apparaît dans les exemples, ou si une question
  du test (texte normalisé) y apparaît ;
- appels query_metric des exemples : arguments ramenés à un squelette (métriques triées, dimensions de
  découpage, comparaison, grain, dimensions filtrées SANS valeurs, classement oui/non) et comparés au
  squelette des questions du test, dérivé de `reference_sql` (+ filtres de `expected_scope`) ;
- exemples terminaux (refuse, ask_clarification) : même intention (catégorie de refus ou champ
  manquant, dérivé du `trap` du test) ET même sujet (concepts du glossaire, Jaccard ≥ 0,5) = fuite ;
- dev/test : question ou SQL normalisé communs = échec ; squelette commun = simple avertissement ;
- MANIFEST : `sha256sum`-compatible (`<hex>  test.yaml`) ; le runner refuse de tourner sur le test
  si le hash ne correspond pas.
"""

from __future__ import annotations

import re
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
# Squelette des appels query_metric
# --------------------------------------------------------------------------------------------

DIMENSIONS = ("region_agent", "region_client", "type", "segment", "agent")
DATE_COLUMNS = {"date_id", "date", "annee", "trimestre", "mois", "debut_mois", "semaine_iso", "annee_iso"}
GRAIN_COLUMNS = {"date": "day", "debut_mois": "month"}


def metric_skeleton(
    metrics: Iterable[str],
    group_by: Iterable[str] = (),
    compare_to: str | None = None,
    grain: str | None = None,
    filter_dims: Iterable[str] = (),
    ranked: bool = False,
) -> str:
    """Forme canonique d'un appel query_metric, sans aucune valeur (dates, régions, limite)."""
    return (
        f"metrics={','.join(sorted(set(metrics)))}|group_by={','.join(sorted(set(group_by)))}"
        f"|compare={compare_to or 'none'}|grain={grain or 'none'}"
        f"|filters={','.join(sorted(set(filter_dims)))}|ranked={'oui' if ranked else 'non'}"
    )


def call_skeleton(args: dict[str, Any]) -> str:
    """Squelette des `arguments` d'un appel query_metric (exemples du prompt)."""
    filters = [
        f.get("dimension")
        for f in args.get("filters") or []
        if isinstance(f, dict) and f.get("dimension") and f.get("op") != "not_in"
    ]
    return metric_skeleton(
        [str(m) for m in args.get("metrics") or []],
        [str(g) for g in args.get("group_by") or []],
        None if args.get("compare_to") in (None, "none") else str(args["compare_to"]),
        None if args.get("grain") in (None, "none") else str(args["grain"]),
        [str(f) for f in filters],
        args.get("limit") is not None,
    )


def _metric_of(node: exp.Expression) -> str | None:
    text = node.sql(dialect="postgres").lower()
    if "echouee" in text and "nullif" in text:
        return "taux_echec"
    if "count(distinct" in text and "client_id" in text:
        return "clients_actifs"
    if "count(distinct" in text and "agent_id" in text:
        return "agents_actifs"
    if "sum(" in text and "montant_xof" in text:
        return "valeur_transferee"
    if "sum(" in text and "frais_xof" in text:
        return "revenus_frais"
    if "count(*)" in text:
        return "volume_transactions"
    return None


def _period_signature(node: exp.Expression) -> tuple[str, ...]:
    """Littéraux des clauses FILTER (dates) d'une agrégation : distingue les périodes comparées."""
    lits: list[str] = []
    for f in node.find_all(exp.Filter):
        cond = f.expression
        if cond is None:
            continue
        if not any(c.name.lower() in DATE_COLUMNS for c in cond.find_all(exp.Column)):
            continue
        lits.extend(
            str(lit.this).replace("-", "")
            for lit in cond.find_all(exp.Literal)
            if str(lit.this).replace("-", "").isdigit()
        )
    return tuple(lits)


def select_period_signatures(sql: str) -> list[tuple[str, str | None, tuple[str, ...]]]:
    """(alias, métrique, littéraux des FILTER de dates) pour chaque expression du SELECT de tête."""
    tree = _parse(sql)
    if not isinstance(tree, exp.Select):
        return []
    out: list[tuple[str, str | None, tuple[str, ...]]] = []
    for e in tree.expressions:
        inner = e.unalias()
        if isinstance(inner, exp.Column):
            out.append((e.alias_or_name.lower(), None, ()))
        else:
            out.append((e.alias_or_name.lower(), _metric_of(inner), _period_signature(inner)))
    return out


def _compare_kind(a: tuple[str, ...], b: tuple[str, ...]) -> str:
    """previous_year si la 2e période est la 1re décalée d'un an (AAAAMMJJ), sinon previous_period."""
    if a and b and all(len(x) == 8 and x.isdigit() for x in (a[0], b[0])) and int(a[0]) - int(b[0]) == 10000:
        return "previous_year"
    return "previous_period"


def sql_metric_skeleton(sql: str, scope_filters: Iterable[str] = ()) -> str | None:
    """Squelette query_metric équivalent à un SQL de référence ; None s'il n'est pas exprimable
    (table autre que fact_transaction, sous-requête, colonne hors dimensions certifiées…)."""
    tree = _parse(sql)
    if not isinstance(tree, exp.Select) or tree.find(exp.Subquery) or tree.find(exp.Exists):
        return None
    from_ = tree.args.get("from") or tree.args.get("from_")
    main = from_.find(exp.Table) if from_ is not None else None
    if main is None or main.name.lower() != "fact_transaction":
        return None
    tables: dict[str, str] = {}
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if name == "dim_region":
            join = t.parent if isinstance(t.parent, exp.Join) else None
            on = join.sql().lower() if join is not None else ""
            name = "region_client" if "region_client_id" in on else "region_agent"
        tables[(t.alias or t.name).lower()] = name

    def dim_of(col: exp.Column) -> str | None:
        table = tables.get(col.table.lower(), "fact_transaction") if col.table else "fact_transaction"
        name = col.name.lower()
        if table in ("region_agent", "region_client") and name == "region":
            return table
        if table == "fact_transaction" and name == "type":
            return "type"
        if table == "dim_client" and name == "segment":
            return "segment"
        if table == "dim_agent" and name in ("agent_id", "nom"):
            return "agent"
        return None

    metrics: list[str] = []
    periods: dict[str, list[tuple[str, ...]]] = {}
    for e in tree.expressions:
        inner = e.unalias()
        if isinstance(inner, exp.Column):
            continue  # colonne de découpage
        m = _metric_of(inner)
        if m is None:
            return None
        metrics.append(m)
        periods.setdefault(m, []).append(_period_signature(inner))
    if not metrics:
        return None
    compare: str | None = None
    for sigs in periods.values():
        distinct = list(dict.fromkeys(s for s in sigs if s))
        if len(distinct) >= 2:
            compare = _compare_kind(distinct[0], distinct[1])

    group_by: list[str] = []
    grain: str | None = None
    group = tree.args.get("group")
    for g in group.expressions if group is not None else []:
        if not isinstance(g, exp.Column):
            return None
        d = dim_of(g)
        if d is not None:
            group_by.append(d)
        elif tables.get(g.table.lower()) == "dim_date" and g.name.lower() in GRAIN_COLUMNS:
            grain = GRAIN_COLUMNS[g.name.lower()]
        else:
            return None  # ex. a.ville : pas une dimension de query_metric

    filters: set[str] = set(scope_filters)
    where = tree.args.get("where")
    for c in where.find_all(exp.Column) if where is not None else []:
        table = tables.get(c.table.lower(), "fact_transaction") if c.table else "fact_transaction"
        name = c.name.lower()
        if table == "fact_transaction" and name in ("statut", "date_id", "agent_id"):
            continue
        if table == "dim_date" and name in DATE_COLUMNS:
            continue
        d = dim_of(c)
        if d is None:
            return None  # ex. d.jour_ferie : non exprimable par query_metric
        filters.add(d)
    return metric_skeleton(metrics, group_by, compare, grain, filters, tree.args.get("limit") is not None)


def item_metric_skeletons(item: EvalItem) -> set[str]:
    scope = list(item.expected_scope.filters) if item.expected_scope else []
    out: set[str] = set()
    for i, sql in enumerate(item_sqls(item)):
        try:
            sk = sql_metric_skeleton(sql, scope if i == 0 else ())
        except Exception:  # noqa: BLE001 - SQL illisible : déjà signalé par les autres contrôles
            sk = None
        if sk:
            out.add(sk)
    return out


# --------------------------------------------------------------------------------------------
# Exemples d'appels (query_metric, outils terminaux)
# --------------------------------------------------------------------------------------------

ARG_KEYS = ("arguments", "args", "params", "input")
TOOL_KEYS = ("outil", "tool", "name")


@dataclass
class ExampleCall:
    example_id: str
    tool: str | None
    arguments: dict[str, Any]
    question: str | None


def example_calls(examples: Any) -> list[ExampleCall]:
    """Appels d'outils des exemples, quelle que soit la structure (clés `arguments`/`args`/…)."""
    out: list[ExampleCall] = []

    def walk(node: Any, ex_id: str, question: str | None) -> None:
        if isinstance(node, dict):
            ex_id = str(node.get("id", ex_id))
            q = next((node[k] for k in QUESTION_KEYS if isinstance(node.get(k), str)), None)
            question = q or question
            tool = next((node[k] for k in TOOL_KEYS if isinstance(node.get(k), str)), None)
            args = next((node[k] for k in ARG_KEYS if isinstance(node.get(k), dict)), None)
            if args is not None:
                out.append(ExampleCall(ex_id, tool, args, question))
            for k, v in node.items():
                if k not in ARG_KEYS:
                    walk(v, ex_id, question)
        elif isinstance(node, list):
            for v in node:
                walk(v, ex_id, question)

    walk(examples, "?", None)
    return out


def is_metric_call(c: ExampleCall) -> bool:
    return c.tool == "query_metric" or (c.tool is None and "metrics" in c.arguments)


# Intention attendue d'une question du test sans SQL (dérivée du `trap`, test.yaml étant figé).
TRAP_INTENT = {
    "kpi_manquant": "clarification:kpi",
    "sens_region_sans_defaut": "clarification:sens_region",
    "hors_modele": "refusal:hors_modele",
    "ecriture": "refusal:modification_demandee",
    "injection_directe": "refusal:contournement",
    "donnee_personnelle": "refusal:donnee_personnelle",
}

# Concepts du glossaire reconnus dans une question (texte normalisé sans accents).
CONCEPTS = {
    "destinataire": r"destinataire|\brecu|\brecoi|\brecev",
    "transfert": r"transfert",
    "classement": r"\ble plus\b|\btop\b|meilleur|\bpremiers?\b|classe",
    "valeur": r"valeur|argent|montant",
    "volume": r"\btransactions?\b|\boperations?\b|volume",
    "frais": r"frais|revenu",
    "client": r"\bclients?\b",
    "agent": r"points? de service|\bagents?\b",
    "region": r"region",
    "ecriture": r"supprim|ajout|modifi|efface|insere|corrig|mets? a jour",
    "echec": r"echou|echec",
    "activite": r"activite|se porte|evolu",
    "personnel": r"telephone|adresse|\bnoms?\b|numero",
    "reseau": r"reseau",
    "prompt": r"prompt|instruction|administrateur|grant",
}


def concepts(text: str) -> set[str]:
    t = norm_text(text)
    return {k for k, rx in CONCEPTS.items() if re.search(rx, t)}


def same_subject(a: str, b: str) -> bool:
    ca, cb = concepts(a), concepts(b)
    inter = ca & cb
    return len(inter) >= 2 and len(inter) / len(ca | cb) >= 0.5


def example_intent(c: ExampleCall) -> str | None:
    if c.tool == "refuse":
        return f"refusal:{c.arguments.get('category')}"
    if c.tool == "ask_clarification":
        return f"clarification:{c.arguments.get('missing')}"
    return None


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
    # « T40 ↔ ex03 » : même squelette query_metric (ou même intention et même sujet pour un exemple
    # terminal) entre une question du test et un exemple
    metric_calls: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.exact
            or self.skeleton
            or self.questions
            or self.dev_overlap
            or self.unparsable
            or self.metric_calls
            or self.intents
        )

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
    calls = example_calls(examples)
    ex_metric: dict[str, list[str]] = {}
    for c in calls:
        if is_metric_call(c):
            ex_metric.setdefault(call_skeleton(c.arguments), []).append(c.example_id)
    terminal = [(example_intent(c), c) for c in calls if example_intent(c)]

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
        for sk in sorted(item_metric_skeletons(it)):
            rep.metric_calls.extend(f"{it.id} ↔ {ex}" for ex in ex_metric.get(sk, []))
        intent = TRAP_INTENT.get(it.trap or "") if it.expected_kind != "answer" else None
        for ex_intent, c in terminal:
            if intent and ex_intent == intent and c.question and same_subject(it.final_question, c.question):
                rep.intents.append(f"{it.id} ↔ {c.example_id}")
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
