-- Clear the ingredient lines of the Food.com recipes in this batch, so step 31 can
-- write the current set. Safe because nothing references recipe_ingredient, and it
-- also removes lines the LLM no longer returns. Limited to recipes whose source_ref
-- is in staging, so user-saved recipes (source_ref is null) are never touched.
delete from public.recipe_ingredient as ri
using public.recipes as r
where ri.recipe_id = r.recipe_id
  and r.source_ref in (select source_ref from staging.stg_recipes)
