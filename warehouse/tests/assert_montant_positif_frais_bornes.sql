-- Montant > 0, frais >= 0 et <= montant (en plus des CHECK du contrat).
select transaction_id, montant_xof, frais_xof
from {{ ref('fact_transaction') }}
where montant_xof <= 0 or frais_xof < 0 or frais_xof > montant_xof
