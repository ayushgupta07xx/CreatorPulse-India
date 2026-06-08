{#
  Use the custom schema name verbatim (no target-schema prefix) so dbt models
  land in bare schemas: staging_dbt / intermediate / marts / snapshots.
  This keeps dbt-owned marts in the same `marts` schema as Alembic's
  channel_embeddings, while dbt only ever creates/drops its own dim_*/fact_*/mart_*.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
