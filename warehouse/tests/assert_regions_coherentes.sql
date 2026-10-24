-- Les régions dénormalisées du fait sont recalculées depuis raw, sans passer par les dimensions
-- ni par la logique du modèle (coalesce/left join) :
--   - region_client_id = région du client de la transaction dans raw_clients ;
--   - region_agent_id  = région de l'agent dans raw_agents, ou -1 si la transaction est hors
--     agent (agent_id NULL dans raw_transactions). Un agent_id raw sans agent connu échoue
--     (il ne doit pas être masqué en -1).
-- Vérifie aussi que client_id et agent_id du fait reprennent ceux de raw_transactions.
select f.transaction_id
from {{ ref('fact_transaction') }} as f
left join {{ source('raw', 'raw_transactions') }} as t on t.transaction_id = f.transaction_id
left join {{ source('raw', 'raw_clients') }} as c on c.client_id = t.client_id
left join {{ source('raw', 'raw_agents') }} as a on a.agent_id = t.agent_id
where t.transaction_id is null
   or c.client_id is null
   or (t.agent_id is not null and a.agent_id is null)
   or f.client_id <> t.client_id
   or f.agent_id <> coalesce(t.agent_id, -1)
   or f.region_client_id is distinct from c.region_id
   or f.region_agent_id is distinct from (
       case when t.agent_id is null then -1 else a.region_id end
   )
