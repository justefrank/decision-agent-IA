"""Jeu de sécurité du garde SQL : payloads nommés (refusés) et requêtes légitimes (acceptées)."""

from __future__ import annotations

import pytest
from decision_core.semantic import load_semantic
from decision_sql_guard import guard_sql

SEM = load_semantic()
ROW_LIMIT = 1000
F = "analytics.fact_transaction f"

# (nom, SQL) : chaque payload doit être refusé avec error_class = guard_blocked.
PAYLOADS: list[tuple[str, str]] = [
    ("cte_modifiante_delete", f"WITH x AS (DELETE FROM {F} RETURNING *) SELECT * FROM x"),
    (
        "cte_modifiante_update",
        "WITH x AS (UPDATE analytics.dim_agent SET nom = 'a' RETURNING *) SELECT * FROM x",
    ),
    (
        "cte_modifiante_insert",
        "WITH x AS (INSERT INTO analytics.dim_region VALUES (99,'x','y') RETURNING *) SELECT * FROM x",
    ),
    ("multi_instructions_drop", "SELECT 1 FROM analytics.dim_date; DROP TABLE analytics.dim_date"),
    ("multi_instructions_select", "SELECT 1 FROM analytics.dim_date; SELECT 2 FROM analytics.dim_date"),
    ("pg_read_file", "SELECT pg_read_file('/etc/passwd') FROM analytics.dim_date"),
    ("pg_read_file_guillemets", "SELECT \"pg_read_file\"('/etc/passwd') FROM analytics.dim_date"),
    ("pg_read_file_commentaire_inline", "SELECT pg_read_file/**/('/etc/passwd') FROM analytics.dim_date"),
    (
        "pg_read_file_prefixe_pg_catalog",
        "SELECT pg_catalog.pg_read_file('/etc/passwd') FROM analytics.dim_date",
    ),
    ("pg_read_file_casse_mixte", "SELECT Pg_ReAd_FiLe('/etc/passwd') FROM analytics.dim_date"),
    ("pg_read_file_prefixe_cite", 'SELECT "pg_catalog"."pg_read_file"(\'/x\') FROM analytics.dim_date'),
    ("pg_ls_dir", "SELECT pg_ls_dir('.') FROM analytics.dim_date"),
    ("pg_sleep", "SELECT pg_sleep(30) FROM analytics.dim_date"),
    ("pg_sleep_sous_requete", "SELECT * FROM analytics.dim_date WHERE date_id = (SELECT pg_sleep(5))"),
    ("dblink", "SELECT dblink('host=evil', 'select 1') FROM analytics.dim_date"),
    ("set_config", "SELECT set_config('statement_timeout', '0', false) FROM analytics.dim_date"),
    ("current_setting", "SELECT current_setting('data_directory') FROM analytics.dim_date"),
    ("txid_current", "SELECT txid_current() FROM analytics.dim_date"),
    ("lo_import", "SELECT lo_import('/etc/passwd') FROM analytics.dim_date"),
    ("lo_export", "SELECT lo_export(1, '/tmp/x') FROM analytics.dim_date"),
    ("version", "SELECT version() FROM analytics.dim_date"),
    ("copy_to_fichier", "COPY analytics.dim_agent TO '/tmp/agents.csv'"),
    ("copy_programme", "COPY (SELECT 1) TO PROGRAM 'id'"),
    ("set_search_path", "SET search_path = public"),
    ("set_role", "SET ROLE postgres"),
    ("pg_catalog_table", "SELECT * FROM pg_catalog.pg_authid"),
    ("pg_catalog_non_qualifiee", "SELECT * FROM pg_shadow"),
    ("information_schema", "SELECT table_name FROM information_schema.tables"),
    ("schema_public", "SELECT * FROM public.secrets"),
    ("schema_app", "SELECT * FROM app.query_log"),
    ("schema_raw", "SELECT * FROM raw.transactions"),
    ("table_inconnue_analytics", "SELECT * FROM analytics.secret_table"),
    ("sous_requete_from_pg_catalog", "SELECT * FROM (SELECT rolname FROM pg_catalog.pg_roles) s"),
    ("sous_requete_where_pg_catalog", f"SELECT 1 FROM {F} WHERE f.client_id IN (SELECT oid FROM pg_class)"),
    ("cte_vers_pg_catalog", "WITH r AS (SELECT * FROM pg_catalog.pg_user) SELECT * FROM r"),
    ("union_pg_catalog", "SELECT region FROM analytics.dim_region UNION SELECT usename FROM pg_user"),
    ("autre_base", "SELECT * FROM keycloak.public.user_entity"),
    ("select_into", "SELECT * INTO analytics.copie FROM analytics.dim_agent"),
    ("for_update", "SELECT * FROM analytics.dim_agent FOR UPDATE"),
    ("for_share", "SELECT * FROM analytics.dim_agent FOR SHARE"),
    ("generate_series_geante", "SELECT * FROM generate_series(1, 1000000000)"),
    ("generate_series_select", "SELECT generate_series(1, 100000000) FROM analytics.dim_date"),
    ("cross_join", "SELECT COUNT(*) FROM analytics.fact_transaction CROSS JOIN analytics.dim_client"),
    ("produit_cartesien_virgule", "SELECT COUNT(*) FROM analytics.fact_transaction, analytics.dim_client"),
    (
        "jointure_on_true",
        "SELECT COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_client c ON TRUE",
    ),
    ("natural_join", "SELECT COUNT(*) FROM analytics.fact_transaction NATURAL JOIN analytics.dim_client"),
    ("chaine_e_echappee", "SELECT E'\\'' FROM analytics.dim_date"),
    ("chaine_dollar", "SELECT $$pg_sleep$$ FROM analytics.dim_date"),
    ("chaine_dollar_etiquetee", "SELECT $tag$x$tag$ FROM analytics.dim_date"),
    ("unicode_identifiant", 'SELECT U&"\\0070g_sleep"(1) FROM analytics.dim_date'),
    ("unicode_chaine", "SELECT U&'\\0041' FROM analytics.dim_date"),
    ("antislash_chaine", "SELECT * FROM analytics.dim_region WHERE region = 'a\\' OR 1=1 --'"),
    ("cte_recursive", "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT * FROM r"),
    ("lateral", "SELECT * FROM analytics.dim_agent a, LATERAL (SELECT 1) x"),
    ("tablesample", "SELECT * FROM analytics.fact_transaction TABLESAMPLE SYSTEM (10)"),
    ("cast_regclass", "SELECT 'pg_authid'::regclass FROM analytics.dim_date"),
    ("query_to_xml", "SELECT query_to_xml('select 1', true, true, '') FROM analytics.dim_date"),
    ("current_user", "SELECT current_user FROM analytics.dim_date"),
    ("date_systeme", "SELECT COUNT(*) FROM analytics.dim_date WHERE date = current_date"),
    ("now", "SELECT COUNT(*) FROM analytics.dim_date WHERE date < now()"),
    ("insert", "INSERT INTO analytics.dim_region VALUES (1, 'x', 'y')"),
    ("delete", "DELETE FROM analytics.fact_transaction"),
    ("drop", "DROP TABLE analytics.fact_transaction"),
    ("parametre_positionnel", "SELECT * FROM analytics.dim_region WHERE region_id = $1"),
    ("sans_table", "SELECT 1"),
    ("vide", "   "),
    (
        "trop_long",
        "SELECT region FROM analytics.dim_region WHERE region IN (" + ",".join(["'Dakar'"] * 900) + ")",
    ),
    ("trop_imbrique", "SELECT " + "(" * 60 + "1" + ")" * 60 + " FROM analytics.dim_date"),
    ("caractere_nul", "SELECT 1 FROM analytics.dim_date\x00; DROP TABLE x"),
    ("fonction_anonyme_inconnue", "SELECT md5(nom) FROM analytics.dim_agent"),
    # F1 : mots-clés niladiques lus comme colonnes par sqlglot (Postgres renvoie l'identité du rôle).
    ("niladiques_user_role", "SELECT user, current_role, system_user FROM analytics.dim_region"),
    ("niladique_user", "SELECT user FROM analytics.dim_region"),
    (
        "niladique_current_role_where",
        "SELECT region FROM analytics.dim_region WHERE current_role = 'agent_ro'",
    ),
    ("niladique_system_user", "SELECT system_user FROM analytics.dim_region"),
    ("niladique_session_user", "SELECT session_user FROM analytics.dim_region"),
    ("niladique_current_catalog", "SELECT current_catalog FROM analytics.dim_region"),
    ("niladique_current_schema", "SELECT current_schema FROM analytics.dim_region"),
    ("fonction_current_schema", "SELECT current_schema() FROM analytics.dim_region"),
    ("fonction_current_database", "SELECT current_database() FROM analytics.dim_region"),
    ("fonction_user", "SELECT user() FROM analytics.dim_region"),
    ("niladique_casse_mixte", "SELECT Current_Role AS r FROM analytics.dim_region"),
    ("niladique_order_by", "SELECT region FROM analytics.dim_region ORDER BY user"),
    ("niladique_localtimestamp", "SELECT localtimestamp FROM analytics.dim_region"),
    # F3 : condition de jointure non conjonctive ou sans égalité entre la table jointe et une autre.
    (
        "jointure_or_true",
        f"SELECT COUNT(*) FROM {F} JOIN analytics.dim_client c ON f.client_id = f.client_id OR true",
    ),
    (
        "jointure_cle_or_true",
        f"SELECT COUNT(*) FROM {F} JOIN analytics.dim_client c ON (c.client_id = f.client_id OR 1 = 1)",
    ),
    (
        "jointure_meme_alias",
        f"SELECT COUNT(*) FROM {F} JOIN analytics.dim_client c ON f.client_id = f.client_id",
    ),
    (
        "jointure_true_and_meme_alias",
        f"SELECT COUNT(*) FROM {F} JOIN analytics.dim_client c ON TRUE AND c.client_id = c.client_id",
    ),
    (
        "jointure_sans_table_jointe",
        f"SELECT COUNT(*) FROM {F} JOIN analytics.dim_client c ON c.client_id = f.client_id "
        "JOIN analytics.dim_date d ON c.client_id = f.client_id",
    ),
    (
        "jointure_colonnes_non_qualifiees",
        f"SELECT COUNT(*) FROM {F} JOIN analytics.dim_date d ON date_id = date_id",
    ),
]


@pytest.mark.parametrize(("name", "sql"), PAYLOADS, ids=[p[0] for p in PAYLOADS])
def test_payload_refuse(name: str, sql: str) -> None:
    result = guard_sql(sql, SEM, row_limit=ROW_LIMIT)
    assert not result.ok, f"{name} aurait dû être refusé : {result.sql}"
    assert result.sql is None
    assert result.error is not None and result.error.error_class == "guard_blocked"
    assert result.error.message


def test_nombre_de_payloads() -> None:
    assert len(PAYLOADS) >= 30


def test_limit_enorme_ecrase() -> None:
    r = guard_sql("SELECT region FROM analytics.dim_region LIMIT 100000000", SEM, row_limit=ROW_LIMIT)
    assert r.ok and r.sql is not None
    assert r.sql.endswith("LIMIT 1001")


def test_limit_absent_impose() -> None:
    r = guard_sql("SELECT region FROM analytics.dim_region", SEM, row_limit=ROW_LIMIT)
    assert r.ok and r.sql is not None and r.sql.endswith("LIMIT 1001")


def test_limit_petit_conserve() -> None:
    r = guard_sql("SELECT region FROM analytics.dim_region ORDER BY region LIMIT 5", SEM, row_limit=ROW_LIMIT)
    assert r.ok and r.sql is not None and r.sql.endswith("LIMIT 5")


def test_limit_expression_remplace() -> None:
    r = guard_sql("SELECT region FROM analytics.dim_region LIMIT (SELECT 10000000)", SEM, row_limit=ROW_LIMIT)
    # La sous-requête ne lit aucune table, mais le LIMIT est remplacé par une constante.
    assert r.ok and r.sql is not None and r.sql.endswith("LIMIT 1001")


def test_fonction_message_actionnable() -> None:
    r = guard_sql("SELECT * FROM generate_series(1, 10)", SEM, row_limit=ROW_LIMIT)
    assert r.error is not None and "dim_date" in (r.error.hint or "")


LEGIT: list[tuple[str, str]] = [
    (
        "etoile_region_agent",
        "SELECT r.region, SUM(f.montant_xof) FILTER (WHERE f.statut = 'reussie') AS valeur "
        "FROM analytics.fact_transaction f JOIN analytics.dim_region r ON r.region_id = f.region_agent_id "
        "JOIN analytics.dim_date d ON d.date_id = f.date_id "
        "WHERE d.date BETWEEN '2026-03-01' AND '2026-03-31' GROUP BY r.region ORDER BY valeur DESC",
    ),
    (
        "cte_et_classement",
        "WITH par_agent AS (SELECT f.agent_id, COUNT(*) AS n FROM analytics.fact_transaction f "
        "WHERE f.statut = 'reussie' AND f.agent_id <> -1 GROUP BY f.agent_id) "
        "SELECT a.nom, p.n, RANK() OVER (ORDER BY p.n DESC) AS rang FROM par_agent p "
        "JOIN analytics.dim_agent a ON a.agent_id = p.agent_id ORDER BY rang LIMIT 10",
    ),
    (
        "date_trunc_mois",
        "SELECT date_trunc('month', d.date)::date AS mois, COUNT(*) FILTER (WHERE f.statut = "
        "'echouee')::numeric "
        "/ NULLIF(COUNT(*), 0) AS taux FROM analytics.fact_transaction f JOIN analytics.dim_date d "
        "ON d.date_id = f.date_id GROUP BY 1 ORDER BY 1",
    ),
    (
        "extract_annee",
        "SELECT EXTRACT(YEAR FROM d.date) AS annee, ROUND(AVG(f.montant_xof), 0) FROM "
        "analytics.fact_transaction f "
        "JOIN analytics.dim_date d ON d.date_id = f.date_id WHERE f.statut = 'reussie' GROUP BY 1",
    ),
    (
        "case_coalesce_greatest",
        "SELECT CASE WHEN c.segment = 'entreprise' THEN 'pro' ELSE 'autre' END AS g, "
        "COALESCE(SUM(f.frais_xof), 0), GREATEST(MAX(f.montant_xof), 0), LEAST(MIN(f.montant_xof), 1) "
        "FROM analytics.fact_transaction f JOIN analytics.dim_client c USING (client_id) "
        "WHERE f.statut = 'reussie' GROUP BY 1",
    ),
    ("table_non_qualifiee_resolue", "SELECT COUNT(*) FROM fact_transaction WHERE statut = 'reussie'"),
    (
        "sous_requete_from",
        "SELECT AVG(n) FROM (SELECT f.client_id, COUNT(*) AS n FROM analytics.fact_transaction f "
        "WHERE f.statut = 'reussie' GROUP BY f.client_id) t",
    ),
    (
        "left_join_lower_upper",
        "SELECT UPPER(r.region), LOWER(a.statut_agent), COUNT(a.agent_id) FROM analytics.dim_agent a "
        "LEFT JOIN analytics.dim_region r ON r.region_id = a.region_agent_id GROUP BY 1, 2",
    ),
    (
        "percentile_mediane",
        "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.montant_xof) FROM analytics.fact_transaction f "
        "WHERE f.statut = 'reussie' AND f.date_id BETWEEN 20260301 AND 20260331",
    ),
    (
        "interval_et_abs",
        "SELECT ABS(SUM(f.montant_xof)) FROM analytics.fact_transaction f WHERE f.statut = 'reussie' "
        "AND f.txn_ts >= CAST('2026-03-01' AS timestamptz) AND f.txn_ts < CAST('2026-03-01' AS date) "
        "+ INTERVAL '1 month'",
    ),
    (
        "in_liste_et_like",
        "SELECT COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_region r "
        "ON r.region_id = f.region_client_id WHERE r.region IN ('Dakar', 'Thiès') AND r.region LIKE 'D%' "
        "AND f.statut = 'reussie'",
    ),
    (
        "union_all",
        "SELECT 'reussie' AS s, COUNT(*) FROM analytics.fact_transaction WHERE statut = 'reussie' "
        "UNION ALL SELECT 'echouee', COUNT(*) FROM analytics.fact_transaction WHERE statut = 'echouee'",
    ),
    (
        "casse_mixte_et_guillemets",
        'SeLeCt COUNT(*) FrOm "analytics"."fact_transaction" WHERE statut = \'reussie\'',
    ),
    (
        "row_number_partition",
        "SELECT * FROM (SELECT r.region, f.agent_id, ROW_NUMBER() OVER (PARTITION BY r.region ORDER BY "
        "COUNT(*) DESC) AS rn FROM analytics.fact_transaction f JOIN analytics.dim_region r "
        "ON r.region_id = f.region_agent_id WHERE f.agent_id <> -1 GROUP BY r.region, f.agent_id) t "
        "WHERE rn <= 3",
    ),
    (
        "jointure_conjonctive_or_imbrique",
        "SELECT COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_client c "
        "ON c.client_id = f.client_id AND (c.segment = 'entreprise' OR c.segment = 'commercant') "
        "WHERE f.statut = 'reussie'",
    ),
    (
        "jointure_table_non_aliasee",
        "SELECT COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_client "
        "ON dim_client.client_id = f.client_id WHERE f.statut = 'reussie'",
    ),
    (
        "colonne_qualifiee_nommee_user_autorisee",
        'SELECT r."user" FROM (SELECT region AS "user" FROM analytics.dim_region) r',
    ),
]


@pytest.mark.parametrize(("name", "sql"), LEGIT, ids=[p[0] for p in LEGIT])
def test_requete_legitime_acceptee(name: str, sql: str) -> None:
    result = guard_sql(sql, SEM, row_limit=ROW_LIMIT)
    assert result.ok, f"{name} refusé : {result.error}"
    assert result.sql is not None and "LIMIT" in result.sql
    assert result.tables and all(t.startswith("analytics.") for t in result.tables)
    # Idempotence : le SQL réécrit repasse le garde à l'identique.
    again = guard_sql(result.sql, SEM, row_limit=ROW_LIMIT)
    assert again.ok and again.sql == result.sql


def test_table_resolue_est_qualifiee() -> None:
    r = guard_sql("SELECT COUNT(*) FROM fact_transaction", SEM, row_limit=10)
    assert r.ok and r.sql is not None and "analytics.fact_transaction" in r.sql
    assert r.tables == ["analytics.fact_transaction"]


def test_placeholders_refuses_sauf_compilateur() -> None:
    sql = "SELECT COUNT(*) FROM analytics.fact_transaction f WHERE f.date_id BETWEEN %(s)s AND %(e)s"
    assert not guard_sql(sql, SEM, row_limit=10).ok
    r = guard_sql(sql, SEM, row_limit=10, allow_placeholders=True)
    assert r.ok and r.sql is not None and "%(s)s" in r.sql
