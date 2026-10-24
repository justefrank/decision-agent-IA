"""Les fragments SQL des KPI figés par les tests unitaires dbt doivent rester identiques à
`semantic/kpis.yaml` : modifier une définition sans mettre à jour le test dbt échoue ici."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_modele_kpi_reprend_kpis_yaml():
    kpis = yaml.safe_load((ROOT / "semantic" / "kpis.yaml").read_text(encoding="utf-8"))["metrics"]
    sql = (ROOT / "warehouse" / "models" / "qa" / "kpi_reference.sql").read_text(encoding="utf-8")
    trouves = dict(re.findall(r"^\s*(.+?)\s+AS\s+(\w+),?\s*$", sql, flags=re.MULTILINE)[::1])
    par_nom = {v: k for k, v in trouves.items()}
    assert set(kpis) <= set(par_nom), "un KPI de kpis.yaml manque dans kpi_reference.sql"
    for name, metric in kpis.items():
        assert par_nom[name].strip() == metric["sql"].strip(), name
