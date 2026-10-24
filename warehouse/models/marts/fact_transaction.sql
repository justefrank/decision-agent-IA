{{
  config(
    post_hook=[
      "{{ stable_index('ix_fact_transaction_date_id', 'date_id') }}",
      "{{ stable_index('ix_fact_transaction_client_id', 'client_id') }}",
      "{{ stable_index('ix_fact_transaction_agent_id', 'agent_id') }}",
      "{{ stable_index('ix_fact_transaction_date_id_reussie', 'date_id', reussie_only=true) }}",
    ]
  )
}}
-- Grain : une transaction. agent_id NOT NULL : -1 = « Hors agent » (transferts, paiements).
-- date_id = jour de txn_ts à l'heure de Dakar (UTC+0, sans heure d'été).
select
    t.transaction_id::bigint as transaction_id,
    t.client_id::integer as client_id,
    coalesce(t.agent_id, -1)::integer as agent_id,
    c.region_id::integer as region_client_id,
    coalesce(a.region_id, -1)::integer as region_agent_id,
    to_char((t.txn_ts at time zone '{{ var("timezone") }}')::date, 'YYYYMMDD')::integer as date_id,
    t.txn_ts::timestamptz as txn_ts,
    t.type::text as type,
    t.montant::numeric(14, 0) as montant_xof,
    t.frais::numeric(12, 0) as frais_xof,
    t.statut::text as statut
from {{ source('raw', 'raw_transactions') }} as t
inner join {{ source('raw', 'raw_clients') }} as c on c.client_id = t.client_id
left join {{ source('raw', 'raw_agents') }} as a on a.agent_id = t.agent_id
