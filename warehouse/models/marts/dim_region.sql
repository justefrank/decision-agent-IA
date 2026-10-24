-- 14 régions du Sénégal + ligne -1 « Non applicable » (transactions hors agent).
select
    region_id::integer as region_id,
    region::text as region,
    pays::text as pays
from {{ source('raw', 'raw_regions') }}
union all
select -1, 'Non applicable', 'Non applicable'
