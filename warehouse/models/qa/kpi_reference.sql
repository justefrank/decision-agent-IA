{#
  Les 6 KPI de semantic/kpis.yaml, sur une période :
    - vars kpi_debut / kpi_fin (dates incluses) si fournies ;
    - sinon les 30 derniers jours se terminant à reference_date : ]fin - 30 j, fin].
  Chaque ligne « <fragment> AS <métrique> » reprend MOT POUR MOT le champ `sql` de kpis.yaml
  (vérifié par packages/data_gen/tests/test_kpi_sync.py) ; les tests unitaires dbt
  (kpi_reference.yml) figent les valeurs attendues sur un petit jeu fixe.
  Vue dans le schéma raw : invisible pour agent_ro.
#}
{%- set fin = var('kpi_fin', var('reference_date')) -%}
{%- set debut = var('kpi_debut', none) -%}
select
    COUNT(*) FILTER (WHERE f.statut = 'reussie') AS volume_transactions,
    COALESCE(SUM(f.montant_xof) FILTER (WHERE f.statut = 'reussie'), 0) AS valeur_transferee,
    COALESCE(SUM(f.frais_xof) FILTER (WHERE f.statut = 'reussie'), 0) AS revenus_frais,
    COUNT(DISTINCT f.client_id) FILTER (WHERE f.statut = 'reussie') AS clients_actifs,
    COUNT(DISTINCT f.agent_id) FILTER (WHERE f.statut = 'reussie' AND f.agent_id <> -1) AS agents_actifs,
    COUNT(*) FILTER (WHERE f.statut = 'echouee')::numeric / NULLIF(COUNT(*), 0) AS taux_echec
from {{ ref('fact_transaction') }} as f
inner join {{ ref('dim_date') }} as d on d.date_id = f.date_id
where d.date <= date '{{ fin }}'
{%- if debut %}
  and d.date >= date '{{ debut }}'
{%- else %}
  and d.date > date '{{ fin }}' - 30
{%- endif %}
