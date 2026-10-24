"""Garde SQL (liste blanche sur l'AST sqlglot) et règles de cohérence sémantique."""

from decision_sql_guard.guard import (
    ALLOWED_FUNCTION_NAMES,
    ALLOWED_NODE_TYPES,
    GuardResult,
    guard_sql,
    normalize_function_name,
)
from decision_sql_guard.provenance import free_text_columns, free_text_projections
from decision_sql_guard.semantic_rules import SemanticIssue, extract_scope, semantic_issues, semantic_warnings

__all__ = [
    "ALLOWED_FUNCTION_NAMES",
    "ALLOWED_NODE_TYPES",
    "GuardResult",
    "SemanticIssue",
    "extract_scope",
    "free_text_columns",
    "free_text_projections",
    "guard_sql",
    "normalize_function_name",
    "semantic_issues",
    "semantic_warnings",
]
