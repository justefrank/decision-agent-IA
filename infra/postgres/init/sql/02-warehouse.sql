-- Schémas de la base warehouse et droits par défaut.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

CREATE SCHEMA raw AUTHORIZATION dbt_owner;
CREATE SCHEMA analytics AUTHORIZATION dbt_owner;
CREATE SCHEMA app AUTHORIZATION app_owner;
REVOKE ALL ON SCHEMA raw, analytics, app FROM PUBLIC;

-- agent_ro : lecture de analytics uniquement, y compris des tables recréées par dbt run.
GRANT USAGE ON SCHEMA analytics TO agent_ro_base;
ALTER DEFAULT PRIVILEGES FOR ROLE dbt_owner IN SCHEMA analytics
  GRANT SELECT ON TABLES TO agent_ro_base;

-- app_rw : usage du schéma app ; les droits par table sont posés par migration (app_owner).
GRANT USAGE ON SCHEMA app TO app_rw;

-- Aucune extension dblink / file_fdw / adminpack.
