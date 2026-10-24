-- Toute date du fait est dans dim_date et date_id correspond au jour de txn_ts à Dakar.
select f.transaction_id, f.date_id, f.txn_ts
from {{ ref('fact_transaction') }} as f
left join {{ ref('dim_date') }} as d on d.date_id = f.date_id
where d.date_id is null
   or d.date <> (f.txn_ts at time zone '{{ var("timezone") }}')::date
