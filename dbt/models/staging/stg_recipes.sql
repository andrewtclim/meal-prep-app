-- Staging view over raw.foodcom_prepared: one row per Food.com recipe.
-- Only renames columns and pulls the cuisine and the two lists out of the `answer` jsonb.
-- No unpacking into rows and no name cleaning; that happens in later models.
select
    source_ref,
    recipe_name as name,
    recipe_category,
    instructions,
    servings,
    total_minutes,
    ingredient_parts,
    schema_version,
    answer ->> 'cuisine' as cuisine,
    answer -> 'ingredients' as ingredients_json,
    answer -> 'extra_ingredients' as extras_json
from {{ source('foodcom', 'foodcom_prepared') }}

--source comes from the sources.yml file.
