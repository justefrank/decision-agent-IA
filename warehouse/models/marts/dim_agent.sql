-- Points de service + ligne -1 « Hors agent » (transferts et paiements).
-- Pour -1, ville, date_activation et statut_agent sont NULL (non applicable) : la ligne
-- n'entre donc jamais dans un décompte d'agents ouverts ou fermés.
select
    agent_id::integer as agent_id,
    nom::text as nom,
    ville::text as ville,
    region_id::integer as region_agent_id,
    date_activation::date as date_activation,
    statut::text as statut_agent
from {{ source('raw', 'raw_agents') }}
union all
select -1, 'Hors agent', null, -1, null, null
