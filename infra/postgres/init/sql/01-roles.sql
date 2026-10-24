-- Rôles (S9) : chacun ne reçoit que le minimum.
CREATE ROLE dbt_owner LOGIN PASSWORD :'dbt_pw';
CREATE ROLE app_owner LOGIN PASSWORD :'owner_pw';      -- migrations, propriétaire du schéma app
CREATE ROLE app_rw LOGIN PASSWORD :'app_pw';           -- API : DML limité, posé par migration
CREATE ROLE agent_ro_base NOLOGIN;
CREATE ROLE agent_ro LOGIN PASSWORD :'agent_pw' IN ROLE agent_ro_base CONNECTION LIMIT 8;
CREATE ROLE keycloak LOGIN PASSWORD :'kc_pw';

CREATE DATABASE warehouse OWNER postgres;
CREATE DATABASE keycloak OWNER keycloak;
REVOKE ALL ON DATABASE warehouse FROM PUBLIC;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
GRANT CONNECT ON DATABASE warehouse TO dbt_owner, app_owner, app_rw, agent_ro_base;

-- Durcissement de agent_ro (SYSTEM_DESIGN §3). La transaction BEGIN READ ONLY côté MCP s'y ajoute.
ALTER ROLE agent_ro SET search_path = analytics;
ALTER ROLE agent_ro SET default_transaction_read_only = on;
ALTER ROLE agent_ro SET statement_timeout = '10s';
ALTER ROLE agent_ro SET idle_in_transaction_session_timeout = '15s';
ALTER ROLE agent_ro SET lock_timeout = '2s';
ALTER ROLE agent_ro SET work_mem = '16MB';
ALTER ROLE agent_ro SET temp_file_limit = '64MB';
