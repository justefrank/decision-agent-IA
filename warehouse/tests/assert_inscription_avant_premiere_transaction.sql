-- date_inscription <= date de la première transaction du client.
with premiere as (
    select f.client_id, min(d.date) as premiere_date
    from {{ ref('fact_transaction') }} as f
    inner join {{ ref('dim_date') }} as d on d.date_id = f.date_id
    group by f.client_id
)

select c.client_id, c.date_inscription, p.premiere_date
from {{ ref('dim_client') }} as c
inner join premiere as p on p.client_id = c.client_id
where c.date_inscription > p.premiere_date
