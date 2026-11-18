-- Write the ingredient lines. `order by` source_ref, line_no makes Postgres hand out
-- recipe_ingredient_id in the author's order, since line_no itself is not stored.
-- Inner joins on recipe and ingredient (both exist after steps 10 and 20); left join
-- on unit because quantity and unit may be null ("to_taste" has a unit but no quantity).
insert into public.recipe_ingredient (recipe_id, ingredient_id, quantity, unit_id, is_extra)
select
    r.recipe_id,
    i.ingredient_id,
    ri.quantity,
    u.unit_id,
    ri.is_extra
from intermediate.int_recipe_ingredients as ri
join public.recipes as r on r.source_ref = ri.source_ref
join public.ingredients as i on i.ingredient_name = ri.ingredient_name
left join public.units as u on u.unit_name = ri.unit
order by ri.source_ref, ri.line_no
