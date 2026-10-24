{# on-run-end : ANALYZE des tables construites avec succès (statistiques à jour pour le planificateur
   et pour le plafond de coût EXPLAIN du serveur MCP). #}
{% macro analyze_built_tables(results) %}
  {% if execute %}
    {% for res in results %}
      {% if res.node.resource_type == 'model' and res.status == 'success'
            and res.node.config.materialized == 'table' %}
        {% do run_query('analyze ' ~ adapter.quote(res.node.schema) ~ '.' ~ adapter.quote(res.node.alias)) %}
      {% endif %}
    {% endfor %}
  {% endif %}
  select 1
{% endmacro %}
