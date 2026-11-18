-- Link recipes to cuisines by id. Names were checked first, so the join drops nothing.
insert into public.recipe_cuisine (recipe_id, cuisine_id)
select r.recipe_id, c.cuisine_id
from intermediate.int_recipe_cuisines as rc
join public.recipes as r on r.source_ref = rc.source_ref
join public.cuisines as c on c.cuisine_name = rc.cuisine
