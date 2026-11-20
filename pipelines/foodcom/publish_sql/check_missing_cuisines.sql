-- Check (writes nothing): cuisine names used by recipes that are not in public.cuisines.
-- Any row returned stops the publish before it writes. The cuisines table is seeded
-- by a later Alembic revision, so until that exists this check fails on purpose.
select distinct rc.cuisine as missing
from intermediate.int_recipe_cuisines as rc
left join public.cuisines as c on c.cuisine_name = rc.cuisine
where c.cuisine_id is null
order by 1
