-- Réconciliation raw ↔ fact : comptes et sommes par type et statut identiques.
with r as (
    select type, statut, count(*) as n, sum(montant) as montant, sum(frais) as frais
    from {{ source('raw', 'raw_transactions') }}
    group by type, statut
),

f as (
    select type, statut, count(*) as n, sum(montant_xof) as montant, sum(frais_xof) as frais
    from {{ ref('fact_transaction') }}
    group by type, statut
)

select
    coalesce(r.type, f.type) as type,
    coalesce(r.statut, f.statut) as statut,
    r.n as n_raw, f.n as n_fact,
    r.montant as montant_raw, f.montant as montant_fact,
    r.frais as frais_raw, f.frais as frais_fact
from r
full outer join f on f.type = r.type and f.statut = r.statut
where r.n is distinct from f.n
   or r.montant is distinct from f.montant
   or r.frais is distinct from f.frais
