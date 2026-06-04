{% macro normalise_liin(field) %}
    REGEXP_REPLACE(TRIM({{ field }}), '([^ ])-([^ ])', '\1 - \2', 'g')
{% endmacro %}