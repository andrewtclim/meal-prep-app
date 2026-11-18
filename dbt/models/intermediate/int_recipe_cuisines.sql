-- One row per (recipe, cuisine). Since answer schema version 3 the model gives one
-- cuisine per recipe; its parent (cantonese -> chinese) is added here from the
-- cuisine_parent seed, the same way augment.py's cuisine_path does it. So a recipe
-- has 1 row, or 2 when its cuisine has a parent. Matching names to public.cuisines
-- happens in the load into public.
select
    source_ref,
    cuisine
from {{ ref('stg_recipes') }}

union all

select
    r.source_ref,
    p.parent as cuisine
from {{ ref('stg_recipes') }} as r
inner join {{ ref('cuisine_parent') }} as p
    on p.cuisine = r.cuisine
