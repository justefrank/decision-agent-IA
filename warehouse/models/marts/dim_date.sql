-- Un jour par ligne, de start_date à reference_date (vars dbt). Jours fériés : raw_holidays.
with jours as (
    select d::date as date
    from generate_series(
        date '{{ var("start_date") }}', date '{{ var("reference_date") }}', interval '1 day'
    ) as d
),

feries as (
    select distinct date from {{ source('raw', 'raw_holidays') }}
)

select
    to_char(j.date, 'YYYYMMDD')::integer as date_id,
    j.date,
    extract(isodow from j.date)::smallint as jour_semaine,
    extract(week from j.date)::smallint as semaine_iso,
    extract(month from j.date)::smallint as mois,
    (array[
        'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
        'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'
    ])[extract(month from j.date)::int]::text as nom_mois,
    extract(quarter from j.date)::smallint as trimestre,
    extract(year from j.date)::smallint as annee,
    extract(isodow from j.date) in (6, 7) as est_weekend,
    (f.date is not null) as jour_ferie,
    date_trunc('month', j.date)::date as debut_mois,
    (date_trunc('month', j.date) + interval '1 month' - interval '1 day')::date as fin_mois
from jours as j
left join feries as f on f.date = j.date
