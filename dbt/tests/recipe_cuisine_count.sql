-- Singular test: returns the recipes that break the cuisine rule, so zero rows = pass.
-- The rule comes from validate_result in pipelines/foodcom/augment.py: each recipe
-- has 1 to MAX_CUISINES (2) cuisines, no duplicates. An empty list produces no rows
-- in int_recipe_cuisines, so a plain not_null test cannot catch it; the left join
-- from stg_recipes can. If MAX_CUISINES changes in augment.py, change the 2 here.
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
