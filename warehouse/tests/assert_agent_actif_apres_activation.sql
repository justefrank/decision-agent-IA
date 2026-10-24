-- Aucune transaction d'un point de service avant sa date d'activation.
select f.transaction_id, f.agent_id, a.date_activation, d.date
from {{ ref('fact_transaction') }} as f
inner join {{ ref('dim_agent') }} as a on a.agent_id = f.agent_id
inner join {{ ref('dim_date') }} as d on d.date_id = f.date_id
where f.agent_id <> -1 and d.date < a.date_activation
