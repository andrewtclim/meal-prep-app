-- Insert new Food.com recipes and update ones we loaded before. The conflict target is
-- source_ref (unique), so a rerun updates the row in place and recipe_id never changes.
-- Rows without a source_ref (user-saved recipes) can never conflict, so they are untouched.
--
-- stg_recipes calls the column `name`; public.recipes calls it recipe_name.
-- `instructions` is a jsonb list of steps in staging; recipes.instructions is text,
-- so the steps are joined with newlines, in order.
insert into public.recipes (recipe_name, source_ref, instructions, total_minutes, servings)
select
    r.name,
    r.source_ref,
    (
        select string_agg(s.step, E'\n' order by s.idx)
        from jsonb_array_elements_text(r.instructions) with ordinality as s(step, idx)
    ),
    r.total_minutes,
    r.servings
from staging.stg_recipes as r
on conflict (source_ref) do update set
    recipe_name   = excluded.recipe_name,
    instructions  = excluded.instructions,
    total_minutes = excluded.total_minutes,
    servings      = excluded.servings
