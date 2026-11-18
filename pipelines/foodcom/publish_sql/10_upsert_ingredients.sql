-- Add ingredients we have not seen. DO NOTHING (not DO UPDATE): the table has only
-- the name, so an existing row has nothing to update, and it keeps its ingredient_id.
insert into public.ingredients (ingredient_name)
select ingredient_name
from intermediate.int_ingredients
on conflict (ingredient_name) do nothing
