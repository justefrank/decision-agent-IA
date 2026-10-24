{{ config(severity='warn') }}
-- Avertissement (non bloquant) : profil des données synthétiques (SYSTEM_DESIGN §3).
-- Dakar : annonce 35-40 % (poids générateur 0,370). Borne tolérée 0,33-0,42, soit ± 2 points
-- autour de l'annonce : la part par transaction dépend de peu de clients très actifs et varie
-- à petite échelle (mesuré 40,65 % à SCALE=0.05, 38,6 % à SCALE=1.0). Au-delà de ± 2 points,
-- le profil s'écarte réellement de l'annonce.
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
   or part_dakar not between 0.33 and 0.42
