-- Transfert et paiement ↔ agent -1 (région -1) ; dépôt et retrait ↔ agent réel (région réelle).
select transaction_id, type, agent_id, region_agent_id
from {{ ref('fact_transaction') }}
where (type in ('transfert', 'paiement') and (agent_id <> -1 or region_agent_id <> -1))
   or (type in ('depot', 'retrait') and (agent_id = -1 or region_agent_id = -1))
