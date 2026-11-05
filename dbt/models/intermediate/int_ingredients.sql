-- One row per distinct ingredient name across all recipes. This is the set of rows
-- the load into public.ingredients upserts (unique on ingredient_name).
select distinct
    ingredient_name
from {{ ref('int_recipe_ingredients') }}
