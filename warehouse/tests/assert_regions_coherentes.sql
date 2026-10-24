-- region_client_id et region_agent_id du fait reprennent celles des dimensions (SCD1).
select f.transaction_id
from {{ ref('fact_transaction') }} as f
inner join {{ ref('dim_client') }} as c on c.client_id = f.client_id
inner join {{ ref('dim_agent') }} as a on a.agent_id = f.agent_id
where f.region_client_id <> c.region_client_id
   or f.region_agent_id <> a.region_agent_id
