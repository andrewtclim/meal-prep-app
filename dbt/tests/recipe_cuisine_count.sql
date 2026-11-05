-- Singular test: returns the recipes that break the cuisine rule, so zero rows = pass.
-- The rule comes from validate_result in pipelines/foodcom/augment.py: since schema
-- version 3 each recipe has exactly one cuisine. A recipe with no cuisine row would
-- vanish from int_recipe_cuisines, so the left join from stg_recipes is what catches it.
-- If augment.py ever allows more than one cuisine again, change the 1 here.
select
    r.source_ref,
    count(c.cuisine) as n_cuisines
from {{ ref('stg_recipes') }} as r
left join {{ ref('int_recipe_cuisines') }} as c
    on c.source_ref = r.source_ref
group by r.source_ref
having count(c.cuisine) <> 1
