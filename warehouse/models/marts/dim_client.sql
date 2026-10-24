-- SCD1 : une ligne par client, région et segment courants.
select
    client_id::integer as client_id,
    date_inscription::date as date_inscription,
    region_id::integer as region_client_id,
    segment::text as segment
from {{ source('raw', 'raw_clients') }}
