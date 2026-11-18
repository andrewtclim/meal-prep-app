-- Same idea as step 30, for the cuisine links of the Food.com recipes in this batch.
delete from public.recipe_cuisine as rc
using public.recipes as r
where rc.recipe_id = r.recipe_id
  and r.source_ref in (select source_ref from staging.stg_recipes)
