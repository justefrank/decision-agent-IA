# Secrets Docker (non versionnés)

`make secrets` crée ici un fichier par secret, aléatoire (hexadécimal, sans caractère à échapper
dans un DSN), sauf `anthropic_api_key.txt`, à remplir à la main. Liste :

| Fichier | Utilisé par |
|---|---|
| `postgres_password.txt` | superutilisateur postgres (init seulement) |
| `dbt_owner_password.txt` | générateur et dbt (`raw`, `analytics`) |
| `app_owner_password.txt` | migrations Alembic (propriétaire du schéma `app`) |
| `app_rw_password.txt` | API (DML limité sur `app`) |
| `agent_ro_password.txt` | sous-processus MCP uniquement (lecture de `analytics`) |
| `keycloak_db_password.txt` | Keycloak (base `keycloak`) |
| `keycloak_admin_password.txt` | administrateur temporaire du realm master |
| `anthropic_api_key.txt` | API Claude |
| `log_pseudonym_key.txt` | clé HMAC de pseudonymisation du `sub` dans les journaux |

Les mots de passe des rôles Postgres ne sont lus qu'à la **création** du volume `pgdata`.
