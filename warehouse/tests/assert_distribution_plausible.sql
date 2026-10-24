{{ config(severity='warn') }}
-- Avertissement (non bloquant) : profil des données synthétiques (SYSTEM_DESIGN §3).
with s as (
    select
        avg((statut = 'echouee')::int) as taux_echec,
        avg((agent_id = -1)::int) as part_hors_agent,
        avg((region_client_id = 1)::int) as part_dakar
    from {{ ref('fact_transaction') }}
)

select * from s
where taux_echec not between 0.05 and 0.10
   or part_hors_agent not between 0.10 and 0.15
   or part_dakar not between 0.35 and 0.42
