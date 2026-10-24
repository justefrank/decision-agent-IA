"""Fixtures communes (aucune clé API, aucun Postgres)."""

from __future__ import annotations

from datetime import date

import pytest
from decision_core.semantic import load_semantic
from decision_core.settings import Settings


@pytest.fixture(scope="session")
def semantic():
    return load_semantic()


@pytest.fixture
def settings():
    return Settings(
        reference_date=date(2026, 9, 30),
        llm_model="claude-sonnet-5-5",
        llm_effort="medium",
        anthropic_api_key=None,
    )
