-- One row per (recipe, cuisine). Since answer schema version 3 the model gives one
-- cuisine per recipe, so this is one row per recipe. The parent cuisine (cantonese ->
-- chinese) is not in the answer; augment.py adds it from CUISINE_PARENT, and it is
-- not copied into dbt yet. Cuisine names are passed through as the model wrote them;
-- matching them to public.cuisines happens in the load into public.
select
    source_ref,
    cuisine
from {{ ref('stg_recipes') }}
