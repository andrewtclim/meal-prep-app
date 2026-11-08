{#
  Overrides dbt's built-in macro of the same name.

  By default dbt builds a custom schema as "<target schema>_<custom>", so
  `+schema: intermediate` would land in `staging_intermediate`. Here a model
  with a custom schema goes in exactly that schema; a model without one goes
  in the target schema from profiles.yml (`staging`).
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
