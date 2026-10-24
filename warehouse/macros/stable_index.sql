{#
  Post-hook : index au nom stable sur une table recréée par dbt.
  Au moment du post-hook, l'ancienne table (renommée en __dbt_backup, supprimée juste après)
  porte encore l'index du même nom : on le renomme d'abord pour libérer le nom.
#}
{% macro stable_index(name, columns, reussie_only=false) -%}
  alter index if exists {{ this.schema }}.{{ name }} rename to {{ name }}__old;
  create index {{ name }} on {{ this }} ({{ columns }}){% if reussie_only %} where statut = 'reussie'{% endif %}
{%- endmacro %}
