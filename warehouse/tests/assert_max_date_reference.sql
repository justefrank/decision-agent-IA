-- max(date) <= REFERENCE_DATE (var dbt reference_date), pour le fait et pour dim_date.
select 'fact_transaction' as source, max(d.date) as max_date
from {{ ref('fact_transaction') }} as f
inner join {{ ref('dim_date') }} as d on d.date_id = f.date_id
having max(d.date) > date '{{ var("reference_date") }}'
union all
select 'dim_date', max(date)
from {{ ref('dim_date') }}
having max(date) > date '{{ var("reference_date") }}'
