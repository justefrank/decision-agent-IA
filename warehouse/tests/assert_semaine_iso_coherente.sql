-- (annee_iso, semaine_iso) correspond à l'année et à la semaine ISO 8601 de la date
-- (to_char IYYY / IW) : garantit qu'un regroupement par semaine ne mélange pas deux années.
select date_id, date, annee_iso, semaine_iso
from {{ ref('dim_date') }}
where annee_iso <> to_char(date, 'IYYY')::smallint
   or semaine_iso <> to_char(date, 'IW')::smallint
