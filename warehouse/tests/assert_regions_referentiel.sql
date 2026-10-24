-- dim_region contient exactement les 14 régions de semantic/kpis.yaml + la ligne -1.
with attendu(region_id, region) as (
    values (1, 'Dakar'), (2, 'Thiès'), (3, 'Diourbel'), (4, 'Kaolack'), (5, 'Saint-Louis'),
           (6, 'Ziguinchor'), (7, 'Louga'), (8, 'Fatick'), (9, 'Kolda'), (10, 'Tambacounda'),
           (11, 'Kaffrine'), (12, 'Kédougou'), (13, 'Matam'), (14, 'Sédhiou'), (-1, 'Non applicable')
)

select coalesce(a.region_id, r.region_id) as region_id, a.region as attendu, r.region as obtenu
from attendu as a
full outer join {{ ref('dim_region') }} as r on r.region_id = a.region_id
where a.region is distinct from r.region
