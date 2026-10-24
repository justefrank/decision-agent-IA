"""Garde SQL par liste blanche sur l'AST sqlglot (dialecte postgres).

Principe (SYSTEM_DESIGN §6, revue system design §3.2) :
1. bornes de longueur et de profondeur **avant** l'analyse complète (déni de service) ;
2. analyse en une seule instruction ``SELECT`` (CTE, sous-requêtes, jointures comprises) ;
3. liste blanche des **types de nœuds**, des fonctions (noms normalisés) et des tables
   ``analytics.{5 tables}`` sur **tout** l'AST ;
4. ``LIMIT`` imposé ou écrasé à ``row_limit + 1`` ;
5. réécriture du SQL depuis l'AST validé : c'est la seule version exécutée.

Le module est une bibliothèque pure : aucune connexion, aucune E/S.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlglot
from decision_core.models import ToolError
from decision_core.semantic import SemanticLayer
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError
from sqlglot.tokens import TokenType

from decision_sql_guard.semantic_rules import extract_scope, semantic_issues

DIALECT = "postgres"
DEFAULT_MAX_SQL_CHARS = 5000
DEFAULT_MAX_AST_DEPTH = 40
MAX_STRING_LITERAL_CHARS = 200

# --- Listes blanches -----------------------------------------------------------------------------

# Structure de requête et expressions usuelles.
_STRUCTURE: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
    exp.Subquery,
    exp.With,
    exp.CTE,
    exp.From,
    exp.Join,
    exp.Table,
    exp.TableAlias,
    exp.Column,
    exp.Identifier,
    exp.Star,
    exp.Alias,
    exp.Where,
    exp.Group,
    exp.Having,
    exp.Order,
    exp.Ordered,
    exp.Limit,
    exp.Offset,
    exp.Literal,
    exp.Boolean,
    exp.Null,
    exp.Paren,
    exp.Distinct,
    exp.Window,
    exp.WindowSpec,
    exp.DataType,
    exp.DataTypeParam,
    exp.Interval,
    exp.Var,
    exp.Placeholder,
)
# Opérateurs logiques, arithmétiques et de comparaison.
_OPERATORS: tuple[type[exp.Expression], ...] = (
    exp.And,
    exp.Or,
    exp.Not,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Is,
    exp.In,
    exp.Between,
    exp.Like,
    exp.ILike,
    exp.NullSafeEQ,
    exp.NullSafeNEQ,
    exp.Exists,
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
    exp.Mod,
    exp.Neg,
    exp.Pow,
)
# Fonctions de la liste fermée (sqlglot les représente par des classes dédiées).
_FUNCTIONS: dict[type[exp.Expression], str] = {
    exp.Count: "count",
    exp.Sum: "sum",
    exp.Avg: "avg",
    exp.Min: "min",
    exp.Max: "max",
    exp.Stddev: "stddev",
    exp.StddevSamp: "stddev_samp",
    exp.StddevPop: "stddev_pop",
    exp.Variance: "variance",
    exp.VariancePop: "var_pop",
    exp.PercentileCont: "percentile_cont",
    exp.PercentileDisc: "percentile_disc",
    exp.WithinGroup: "within group",
    exp.Filter: "filter",
    exp.DateTrunc: "date_trunc",
    exp.TimestampTrunc: "date_trunc",
    exp.Extract: "extract",
    exp.Coalesce: "coalesce",
    exp.Round: "round",
    exp.Nullif: "nullif",
    exp.Lower: "lower",
    exp.Upper: "upper",
    exp.Abs: "abs",
    exp.Greatest: "greatest",
    exp.Least: "least",
    exp.Floor: "floor",
    exp.Ceil: "ceil",
    exp.Cast: "cast",
    exp.Case: "case",
    exp.If: "case",
    exp.RowNumber: "row_number",
    exp.Rank: "rank",
    exp.DenseRank: "dense_rank",
    exp.PercentRank: "percent_rank",
    exp.Ntile: "ntile",
    exp.Lag: "lag",
    exp.Lead: "lead",
}
ALLOWED_NODE_TYPES: frozenset[type[exp.Expression]] = frozenset((*_STRUCTURE, *_OPERATORS, *_FUNCTIONS))
ALLOWED_FUNCTION_NAMES: frozenset[str] = frozenset(_FUNCTIONS.values())

# Fonctions explicitement dangereuses : message dédié (la liste blanche les refuse de toute façon).
DENIED_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "txid_", "set_config", "current_setting")
DENIED_FUNCTIONS = frozenset(
    {
        "generate_series",
        "set_config",
        "current_setting",
        "dblink",
        "dblink_exec",
        "pg_sleep",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "lo_import",
        "lo_export",
        "txid_current",
        "query_to_xml",
        "version",
        "inet_server_addr",
        "current_user",
        "session_user",
        "current_role",
        "system_user",
        "current_catalog",
        "current_schema",
        "current_schemas",
        "current_database",
        "inet_client_addr",
        "inet_server_port",
        "user",
    }
)

# Mots-clés SQL niladiques (sans parenthèses) que sqlglot lit comme des colonnes non qualifiées :
# Postgres les évalue comme fonctions système (identité, base, horloge). Refusés hors guillemets.
NILADIC_KEYWORDS = frozenset(
    {
        "user",
        "current_user",
        "current_role",
        "session_user",
        "system_user",
        "current_catalog",
        "current_schema",
        "current_database",
        "current_date",
        "current_time",
        "current_timestamp",
        "localtime",
        "localtimestamp",
    }
)
_CLOCK_KEYWORDS = frozenset(
    {"current_date", "current_time", "current_timestamp", "localtime", "localtimestamp"}
)

# Arguments scalaires admis par type de nœud ; tout autre argument non vide est refusé.
_SELECT_ARGS = frozenset(
    {
        "expressions",
        "distinct",
        "from_",
        "from",
        "joins",
        "where",
        "group",
        "having",
        "order",
        "limit",
        "offset",
        "with_",
        "with",
        "windows",
    }
)
_TABLE_ARGS = frozenset({"this", "db", "catalog", "alias"})
_JOIN_ARGS = frozenset({"this", "on", "using", "side", "kind"})
_SETOP_ARGS = frozenset(
    {
        "this",
        "expression",
        "distinct",
        "by_name",
        "order",
        "limit",
        "offset",
        "with_",
        "with",
        "side",
        "kind",
        "on",
    }
)

_DT = exp.DataType.Type
ALLOWED_CAST_TYPES = frozenset(
    {
        _DT.INT,
        _DT.BIGINT,
        _DT.SMALLINT,
        _DT.DECIMAL,
        _DT.DOUBLE,
        _DT.FLOAT,
        _DT.TEXT,
        _DT.VARCHAR,
        _DT.CHAR,
        _DT.DATE,
        _DT.TIMESTAMP,
        _DT.TIMESTAMPTZ,
        _DT.BOOLEAN,
        _DT.INTERVAL,
    }
)

_VAR_PARENTS = (
    exp.Extract,
    exp.Interval,
    exp.DateTrunc,
    exp.TimestampTrunc,
    exp.DataType,
    exp.Cast,
    exp.WindowSpec,
    exp.Window,
)


@dataclass
class GuardResult:
    """Résultat du garde (contrat du brief, champs `warnings` et `ast` en plus)."""

    ok: bool
    sql: str | None = None  # réécrit depuis l'AST validé, LIMIT imposé (row_limit + 1)
    tables: list[str] = field(default_factory=list)
    error: ToolError | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)  # règles sémantiques (si declared_scope fourni)
    ast: exp.Expression | None = field(default=None, repr=False)


class GuardViolation(Exception):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint


def _blocked(message: str, hint: str | None = None) -> GuardResult:
    return GuardResult(ok=False, error=ToolError(error_class="guard_blocked", message=message, hint=hint))


def _config(semantic: SemanticLayer | None, key: str, default: int) -> int:
    try:
        return int((semantic.config.get("sql") or {}).get(key, default)) if semantic else default
    except (TypeError, ValueError, AttributeError):
        return default


def normalize_identifier(node: exp.Expression | str | None) -> str | None:
    """Nom normalisé : minuscules si non cité (repli Postgres), tel quel s'il est cité."""
    if node is None:
        return None
    if isinstance(node, str):
        return node.lower()
    if isinstance(node, exp.Identifier):
        return node.this if node.quoted else node.this.lower()
    return node.name.lower() if node.name else None


def normalize_function_name(name: str) -> str:
    """Minuscules, sans guillemets ni préfixe de schéma (``"PG_CATALOG"."pg_sleep"`` → ``pg_sleep``)."""
    cleaned = name.replace('"', "").replace("`", "").strip()
    return cleaned.rsplit(".", 1)[-1].strip().lower()


# --- Contrôles préalables (avant analyse complète) -----------------------------------------------


def _precheck(sql: str, max_chars: int, max_depth: int) -> None:
    if not sql or not sql.strip():
        raise GuardViolation("Requête vide.")
    if len(sql) > max_chars:
        raise GuardViolation(
            f"Requête trop longue ({len(sql)} caractères, maximum {max_chars}).",
            "Simplifier la requête : agréger en SQL, éviter les listes de valeurs énormes.",
        )
    if "\x00" in sql:
        raise GuardViolation("Caractère nul interdit dans la requête.")
    try:
        tokens = sqlglot.Dialect.get_or_raise(DIALECT).tokenize(sql)
    except TokenError as exc:
        raise GuardViolation("Requête illisible (analyse lexicale impossible).") from exc
    depth = 0
    statements = 0
    seen_content = False
    for tok in tokens:
        tt = tok.token_type
        if tt == TokenType.L_PAREN:
            depth += 1
            if depth > max_depth:
                raise GuardViolation(f"Requête trop imbriquée (profondeur > {max_depth}).")
        elif tt == TokenType.R_PAREN:
            depth -= 1
        elif tt == TokenType.SEMICOLON:
            if seen_content:
                statements += 1
            seen_content = False
            continue
        if tt in (
            TokenType.HEREDOC_STRING,
            TokenType.RAW_STRING,
            TokenType.BYTE_STRING,
            TokenType.NATIONAL_STRING,
            TokenType.UNICODE_STRING,
            TokenType.BIT_STRING,
            TokenType.HEX_STRING,
        ):
            raise GuardViolation(
                "Forme de chaîne interdite (E'…', $$…$$, U&'…', B'…', X'…').",
                "Utiliser des chaînes simples entre apostrophes, sans antislash.",
            )
        if tt == TokenType.STRING:
            if "\\" in tok.text:
                raise GuardViolation("Antislash interdit dans une chaîne littérale.")
            if len(tok.text) > MAX_STRING_LITERAL_CHARS:
                raise GuardViolation("Chaîne littérale trop longue.")
        if tt == TokenType.PARAMETER or tok.text.upper().startswith("U&"):
            raise GuardViolation("Syntaxe U&/paramètre positionnel interdite.")
        seen_content = True
    if seen_content:
        statements += 1
    if statements != 1:
        raise GuardViolation(
            "Une seule instruction SELECT est autorisée (multi-instructions refusées).",
            "Retirer le point-virgule et toute instruction supplémentaire.",
        )


def _ast_depth(root: exp.Expression) -> int:
    best = 0
    stack: list[tuple[exp.Expression, int]] = [(root, 1)]
    while stack:
        node, d = stack.pop()
        best = max(best, d)
        for child in node.iter_expressions():
            stack.append((child, d + 1))
    return best


# --- Parcours de l'AST ---------------------------------------------------------------------------


def _check_scalar_args(node: exp.Expression, allowed: frozenset[str], what: str) -> None:
    for key, value in node.args.items():
        if key in allowed or value in (None, False, [], ""):
            continue
        raise GuardViolation(f"Clause non autorisée dans {what} : {key.rstrip('_').upper()}.")


def _function_violation(node: exp.Expression) -> GuardViolation:
    if isinstance(node, exp.Anonymous):
        raw = node.name if isinstance(node.this, str) else node.this.sql() if node.this else ""
    elif isinstance(node, exp.Func):
        try:
            raw = node.sql(dialect=DIALECT).split("(", 1)[0] or node.sql_name()
        except Exception:  # génération impossible : nom interne sqlglot
            raw = node.sql_name()
    else:
        raw = type(node).__name__
    name = normalize_function_name(str(raw))
    if name in DENIED_FUNCTIONS or name.startswith(DENIED_FUNCTION_PREFIXES):
        hint = "Fonction système interdite."
        if name == "generate_series":
            hint = "Utiliser analytics.dim_date pour les séries de dates."
        return GuardViolation(f"Fonction interdite : {name}.", hint)
    return GuardViolation(
        f"Fonction non autorisée : {name}.",
        "Fonctions permises : " + ", ".join(sorted(ALLOWED_FUNCTION_NAMES)) + ", opérateurs usuels.",
    )


def _node_violation(node: exp.Expression) -> GuardViolation:
    if isinstance(node, exp.CurrentDate | exp.CurrentTimestamp | exp.CurrentTime):
        return GuardViolation(
            "Date système interdite (CURRENT_DATE, now()…).",
            "Les périodes se calculent depuis REFERENCE_DATE : écrire les bornes en littéraux.",
        )
    if isinstance(node, exp.Func | exp.Anonymous):
        return _function_violation(node)
    if isinstance(node, exp.Dot):
        inner = node.expression
        if isinstance(inner, exp.Anonymous | exp.Func):
            return _function_violation(inner)
        return GuardViolation("Référence qualifiée non autorisée (schéma.objet hors analytics).")
    labels = {
        exp.Into: "SELECT … INTO",
        exp.Lock: "FOR UPDATE / FOR SHARE",
        exp.Delete: "DELETE",
        exp.Insert: "INSERT",
        exp.Update: "UPDATE",
        exp.Copy: "COPY",
        exp.Set: "SET",
        exp.Command: "commande",
        exp.Lateral: "LATERAL",
        exp.TableSample: "TABLESAMPLE",
        exp.Values: "VALUES",
        exp.ByteString: "chaîne E'…'",
        exp.RawString: "chaîne $$…$$",
        exp.BitwiseAnd: "opérateur & (ou syntaxe U&)",
    }
    for cls, label in labels.items():
        if isinstance(node, cls):
            return GuardViolation(f"Construction interdite : {label}.")
    return GuardViolation(f"Construction SQL non autorisée : {type(node).__name__}.")


def _cte_names(root: exp.Expression) -> set[str]:
    names: set[str] = set()
    for cte in root.find_all(exp.CTE):
        alias = cte.args.get("alias")
        if alias is not None and normalize_identifier(alias.this) is not None:
            names.add(normalize_identifier(alias.this) or "")
    return names


def _validate(root: exp.Expression, semantic: SemanticLayer, *, allow_placeholders: bool) -> list[str]:
    schema = semantic.tables["schema"]
    table_names = set(semantic.tables["tables"])
    ctes = _cte_names(root)
    used: set[str] = set()

    for node in root.walk():
        if type(node) not in ALLOWED_NODE_TYPES:
            raise _node_violation(node)
        if isinstance(node, exp.Placeholder) and not allow_placeholders:
            raise GuardViolation("Paramètres liés interdits ici : écrire des littéraux.")
        if isinstance(node, exp.Var) and not isinstance(node.parent, _VAR_PARENTS):
            raise GuardViolation(f"Mot-clé inattendu : {node.name}.")
        if isinstance(node, exp.Select):
            _check_scalar_args(node, _SELECT_ARGS, "SELECT")
            distinct = node.args.get("distinct")
            if distinct is not None and not isinstance(distinct, exp.Distinct):
                raise GuardViolation("Forme de DISTINCT non autorisée.")
        elif isinstance(node, exp.Union | exp.Intersect | exp.Except):
            _check_scalar_args(node, _SETOP_ARGS, "l'opération ensembliste")
        elif isinstance(node, exp.With):
            if node.args.get("recursive"):
                raise GuardViolation("CTE récursive interdite (WITH RECURSIVE).")
            _check_scalar_args(node, frozenset({"expressions"}), "WITH")
        elif isinstance(node, exp.CTE):
            if not isinstance(node.this, exp.Select | exp.Union | exp.Intersect | exp.Except):
                raise GuardViolation("Une CTE doit être un SELECT (CTE modifiante interdite).")
            _check_scalar_args(node, frozenset({"this", "alias"}), "la CTE")
        elif isinstance(node, exp.Subquery):
            _check_scalar_args(node, frozenset({"this", "alias"}), "la sous-requête")
        elif isinstance(node, exp.Join):
            _check_join(node)
        elif isinstance(node, exp.Table):
            used.add(_check_table(node, schema, table_names, ctes))
        elif isinstance(node, exp.Column):
            if node.args.get("catalog") is not None:
                raise GuardViolation("Colonne qualifiée par une base : interdit.")
            db = node.args.get("db")
            if db is not None and normalize_identifier(db) != schema:
                raise GuardViolation(f"Seul le schéma {schema} est autorisé.")
            _check_niladic(node)
        elif isinstance(node, exp.DataType):
            if node.this not in ALLOWED_CAST_TYPES:
                raise GuardViolation(
                    f"Type de conversion non autorisé : {node.sql(dialect=DIALECT)}.",
                    "Types permis : integer, bigint, numeric, double precision, text, date, "
                    "timestamp, boolean.",
                )
        elif isinstance(node, exp.Literal) and node.is_string and len(node.this) > MAX_STRING_LITERAL_CHARS:
            raise GuardViolation("Chaîne littérale trop longue.")
    used.discard("")
    return sorted(used)


def _check_join(node: exp.Join) -> None:
    _check_scalar_args(node, _JOIN_ARGS, "JOIN")
    kind = (node.args.get("kind") or "").upper()
    if kind == "CROSS" or (node.args.get("method") or "").upper() == "NATURAL":
        raise GuardViolation(
            "CROSS JOIN / NATURAL JOIN interdits (produit cartésien).",
            "Écrire une jointure explicite : JOIN … ON a.cle = b.cle.",
        )
    on = node.args.get("on")
    if on is None and not node.args.get("using"):
        raise GuardViolation(
            "Jointure sans condition (FROM a, b) interdite : produit cartésien.",
            "Écrire JOIN analytics.<table> x ON x.cle = f.cle.",
        )
    if on is not None:
        _check_join_condition(node, on)


def _check_niladic(node: exp.Column) -> None:
    """Refuse `user`, `current_role`, `system_user`… lus comme colonnes sans table (fonctions système)."""
    ident = node.this
    if node.args.get("table") is not None or not isinstance(ident, exp.Identifier) or ident.quoted:
        return
    name = ident.this.lower()
    if name in _CLOCK_KEYWORDS:
        raise GuardViolation(
            "Date système interdite (CURRENT_DATE, now()…).",
            "Les périodes se calculent depuis REFERENCE_DATE : écrire les bornes en littéraux.",
        )
    if name in NILADIC_KEYWORDS:
        raise GuardViolation(f"Fonction interdite : {name}.", "Fonction système interdite.")


def _join_target(node: exp.Join) -> str | None:
    """Nom par lequel la table jointe est référencée (alias, sinon nom de table)."""
    target = node.this
    alias = target.args.get("alias") if isinstance(target, exp.Expression) else None
    if isinstance(alias, exp.TableAlias) and alias.this is not None:
        return normalize_identifier(alias.this)
    if isinstance(target, exp.Table):
        return normalize_identifier(target.this)
    return None


def _conjuncts(cond: exp.Expression) -> list[exp.Expression]:
    cond = cond.unnest()
    if isinstance(cond, exp.And):
        return _conjuncts(cond.left) + _conjuncts(cond.right)
    return [cond]


def _check_join_condition(node: exp.Join, on: exp.Expression) -> None:
    """Condition conjonctive dont une égalité relie la table jointe à une autre source (F3).

    `ON f.a = f.b OR true` ou `ON TRUE AND f.a = f.a` reviennent à un produit cartésien : refusés.
    """
    hint = (
        "Écrire JOIN analytics.<table> x ON x.cle = f.cle (AND … facultatifs, pas de OR au premier niveau)."
    )
    parts = _conjuncts(on)
    if isinstance(on.unnest(), exp.Or):
        raise GuardViolation(
            "OR au premier niveau d'une condition de jointure : interdit (produit cartésien).", hint
        )
    target = _join_target(node)
    for part in parts:
        if not (
            isinstance(part, exp.EQ)
            and isinstance(part.left, exp.Column)
            and isinstance(part.right, exp.Column)
        ):
            continue
        sides = {
            normalize_identifier(part.left.args.get("table")),
            normalize_identifier(part.right.args.get("table")),
        }
        if None in sides or len(sides) != 2:
            continue
        if target is not None and target in sides:
            return
    raise GuardViolation(
        "Condition de jointure sans égalité entre une colonne de la table jointe et une colonne d'une autre "
        "table (produit cartésien).",
        "La condition ON doit comparer deux colonnes qualifiées de part et d'autre, par exemple "
        "ON d.date_id = f.date_id.",
    )


def _check_table(node: exp.Table, schema: str, table_names: set[str], ctes: set[str]) -> str:
    _check_scalar_args(node, _TABLE_ARGS, "FROM")
    if not isinstance(node.this, exp.Identifier):
        raise (
            _node_violation(node.this)
            if isinstance(node.this, exp.Expression)
            else GuardViolation("Source de données non autorisée.")
        )
    if node.args.get("catalog") is not None:
        raise GuardViolation("Référence à une autre base interdite.")
    name = normalize_identifier(node.this) or ""
    db_node = node.args.get("db")
    allowed = ", ".join(f"{schema}.{t}" for t in sorted(table_names))
    if db_node is None:
        if name in ctes:
            return ""
        if name in table_names:
            # Résolution : on qualifie la table dans l'AST réécrit.
            node.set("db", exp.to_identifier(schema))
            node.set("this", exp.to_identifier(name))
            return f"{schema}.{name}"
        raise GuardViolation(f"Table non autorisée : {name}.", f"Tables autorisées : {allowed}.")
    db = normalize_identifier(db_node)
    if db != schema:
        raise GuardViolation(
            f"Schéma non autorisé : {db}.", f"Seul le schéma {schema} est lisible. Tables : {allowed}."
        )
    if name not in table_names:
        raise GuardViolation(f"Table non autorisée : {schema}.{name}.", f"Tables autorisées : {allowed}.")
    node.set("db", exp.to_identifier(schema))
    node.set("this", exp.to_identifier(name))
    return f"{schema}.{name}"


def _impose_limit(root: exp.Expression, cap: int) -> exp.Expression:
    limit = root.args.get("limit")
    current: int | None = None
    if isinstance(limit, exp.Limit):
        value = limit.expression
        if isinstance(value, exp.Literal) and value.is_int:
            current = int(value.this)
    new = cap if current is None else min(current, cap)
    root.set("limit", exp.Limit(expression=exp.Literal.number(new)))
    return root


# --- Point d'entrée ------------------------------------------------------------------------------


def parse_select(sql: str, semantic: SemanticLayer | None = None) -> exp.Expression:
    """Analyse brute (sans validation) ; sert aux tests et à `semantic_warnings`."""
    return sqlglot.parse_one(sql, read=DIALECT)


def guard_sql(
    sql: str,
    semantic: SemanticLayer,
    *,
    row_limit: int,
    declared_scope: dict[str, Any] | None = None,
    allow_placeholders: bool = False,
) -> GuardResult:
    """Valide `sql` et renvoie la version réécrite depuis l'AST, seule exécutable.

    `allow_placeholders` n'est utilisé que pour le SQL compilé par `query_metric` (paramètres
    ``%(nom)s`` liés par psycopg) ; `run_query` n'accepte que des littéraux.
    """
    max_chars = _config(semantic, "max_sql_chars", DEFAULT_MAX_SQL_CHARS)
    max_depth = _config(semantic, "max_ast_depth", DEFAULT_MAX_AST_DEPTH)
    try:
        _precheck(sql, max_chars, max_depth)
        try:
            statements = sqlglot.parse(sql, read=DIALECT, error_level=sqlglot.ErrorLevel.RAISE)
        except (ParseError, TokenError) as exc:
            raise GuardViolation(
                "Requête SQL invalide (analyse syntaxique impossible).",
                "Vérifier la syntaxe PostgreSQL ; une seule instruction SELECT.",
            ) from exc
        statements = [s for s in statements if s is not None]
        if len(statements) != 1:
            raise GuardViolation("Une seule instruction SELECT est autorisée (multi-instructions refusées).")
        root = statements[0]
        if not isinstance(root, exp.Select | exp.Union | exp.Intersect | exp.Except):
            raise (
                _node_violation(root)
                if type(root) not in ALLOWED_NODE_TYPES
                else GuardViolation("Seule une instruction SELECT est autorisée.")
            )
        if _ast_depth(root) > max_depth * 3:
            raise GuardViolation(f"Arbre syntaxique trop profond (> {max_depth * 3} niveaux).")
        tables = _validate(root, semantic, allow_placeholders=allow_placeholders)
        if not tables:
            raise GuardViolation("La requête doit lire au moins une table du schéma analytics.")
        _impose_limit(root, row_limit + 1)
        rewritten = root.sql(dialect=DIALECT)
    except GuardViolation as v:
        return _blocked(v.message, v.hint)
    except RecursionError:
        return _blocked("Requête trop complexe (récursion).")

    scope = extract_scope(root, semantic)
    warnings: list[str] = []
    if declared_scope is not None:
        warnings = [issue.message for issue in semantic_issues(root, declared_scope, semantic)]
    return GuardResult(ok=True, sql=rewritten, tables=tables, scope=scope, warnings=warnings, ast=root)
