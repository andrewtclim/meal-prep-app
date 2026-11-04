-- Check (writes nothing): unit names used by recipes that are not in public.units.
-- Any row returned stops the publish before it writes, because a missing unit
-- would otherwise silently become a NULL unit_id.
select distinct ri.unit as missing
from intermediate.int_recipe_ingredients as ri
left join public.units as u on u.unit_name = ri.unit
where ri.unit is not null
  and u.unit_id is null
order by 1
