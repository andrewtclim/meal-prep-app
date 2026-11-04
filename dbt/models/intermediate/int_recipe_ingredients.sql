-- One row per ingredient line of each recipe.
--
-- Two sources of rows:
--   1. listed ingredients: the names are in ingredient_parts (a jsonb list of
--      strings) and the LLM answer gives quantity and unit for each by `position`
--      (0-based). We join the two lists on that position.
--   2. extra ingredients: ingredients the LLM found in the instructions but not
--      in the list. They carry their own name, so no join is needed.
--
-- `line_no` is a 0-based order within a recipe, unique per source_ref: listed
-- ingredients keep their position, extras continue after them.
-- Names are passed through as written; cleaning them is a separate, later step.

with names as (
    select
        r.source_ref,
        (n.idx - 1) as position,                    -- ordinality counts from 1, the LLM from 0
        n.name,
        jsonb_array_length(r.ingredient_parts) as listed_count,
        r.ingredients_json
    from {{ ref('stg_recipes') }} as r
    cross join lateral jsonb_array_elements_text(r.ingredient_parts)
        with ordinality as n(name, idx)
),

listed as (
    select
        n.source_ref,
        n.position as line_no,
        n.name,
        (q.item ->> 'quantity')::numeric as quantity,
        q.item ->> 'unit' as unit,
        false as is_extra
    from names as n
    left join lateral (
        -- find the LLM entry whose position matches this name's position
        select item
        from jsonb_array_elements(n.ingredients_json) as item
        where (item ->> 'position')::int = n.position
        limit 1
    ) as q on true
),

extras as (
    select
        r.source_ref,
        jsonb_array_length(r.ingredient_parts) + (e.idx - 1) as line_no,
        e.item ->> 'name' as name,
        (e.item ->> 'quantity')::numeric as quantity,
        e.item ->> 'unit' as unit,
        true as is_extra
    from {{ ref('stg_recipes') }} as r
    cross join lateral jsonb_array_elements(r.extras_json)
        with ordinality as e(item, idx)
)

select * from listed
union all
select * from extras
