-- One row per (recipe, cuisine): the LLM's cuisine list unpacked into rows.
-- Cuisine names are passed through as the model wrote them; matching them to
-- public.cuisines happens in the load into public.
select
    r.source_ref,
    c.cuisine
from {{ ref('stg_recipes') }} as r
cross join lateral jsonb_array_elements_text(r.cuisines_json) as c(cuisine)
