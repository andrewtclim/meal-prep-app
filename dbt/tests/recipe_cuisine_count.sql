-- Singular test: returns the recipes that break the cuisine rule, so zero rows = pass.
-- Since schema version 3 each recipe has one cuisine, plus its parent when it has one,
-- so 1 or 2 rows in int_recipe_cuisines, never a repeat. A recipe with no row would
-- vanish from int_recipe_cuisines, so the left join from stg_recipes is what catches it.
select
    r.source_ref,
    count(c.cuisine) as n_cuisines,
    count(distinct c.cuisine) as n_distinct
from {{ ref('stg_recipes') }} as r
left join {{ ref('int_recipe_cuisines') }} as c
    on c.source_ref = r.source_ref
group by r.source_ref
having count(c.cuisine) not between 1 and 2
    or count(c.cuisine) <> count(distinct c.cuisine)
