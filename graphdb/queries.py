"""The graph's questions as plain Python functions (DATA_MODEL.md, Main queries).

This is the only module that contains Cypher. Callers pass plain ids and get
plain dataclasses back, so the agent never imports neo4j and can be tested
with a fake that has the same three functions.

Every query takes its inputs as $parameters. The values travel separately from
the query text, so they can never be read as Cypher (injection), and Neo4j
caches the query plan once and reuses it for any values.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from neo4j import Driver

from graphdb.client import get_driver

# (substitute)-[:SUBSTITUTES_FOR]->(missing): walk the edges INTO the missing
# ingredient (DECISIONS #28), best weight first. The name tie-break keeps the
# order the same on every run.
FIND_SUBSTITUTES = """
MATCH (s:Ingredient)-[e:SUBSTITUTES_FOR]->(:Ingredient {ingredient_id: $ingredient_id})
WHERE NOT s.ingredient_id IN $exclude_ids
RETURN s.ingredient_id AS ingredient_id, s.name AS name,
       e.weight AS weight, e.model_version AS model_version
ORDER BY weight DESC, name ASC
LIMIT $limit
"""

# Fan-in: start from the pantry ingredients, follow USED_IN to the recipes that
# use any of them, then list each recipe's full ingredient set and keep the
# ones with few enough missing. Starting from the pantry means recipes that
# share nothing with it are never looked at.
RECIPES_MAKEABLE_FROM = """
MATCH (p:Ingredient)-[:USED_IN]->(r:Recipe)
WHERE p.ingredient_id IN $pantry_ids
WITH DISTINCT r
MATCH (i:Ingredient)-[:USED_IN]->(r)
WITH r, collect(i) AS needed
WITH r, [x IN needed WHERE NOT x.ingredient_id IN $pantry_ids] AS missing
WHERE size(missing) <= $max_missing
RETURN r.recipe_id AS recipe_id, r.name AS name,
       [m IN missing | m.ingredient_id] AS missing_ids,
       [m IN missing | m.name] AS missing_names
ORDER BY size(missing), name
"""

# A PrepTask is shared when 2 or more of the chosen recipes REQUIRE it.
SHARED_PREP_TASKS = """
MATCH (r:Recipe)-[:REQUIRES]->(p:PrepTask)
WHERE r.recipe_id IN $recipe_ids
WITH p, collect(r.recipe_id) AS recipe_ids
WHERE size(recipe_ids) >= 2
MATCH (p)-[:APPLIES_TO]->(i:Ingredient)
RETURN p.prep_task_id AS prep_task_id, p.technique AS technique, p.form AS form,
       i.ingredient_id AS ingredient_id, i.name AS ingredient_name, recipe_ids
ORDER BY size(recipe_ids) DESC, prep_task_id
"""


@dataclass(frozen=True)
class Substitute:
    """One ingredient that can replace the missing one, and how well."""

    ingredient_id: int
    name: str
    weight: float
    model_version: str


@dataclass(frozen=True)
class MakeableRecipe:
    """A recipe the pantry (nearly) covers, with what is still missing."""

    recipe_id: int
    name: str
    missing_ids: tuple[int, ...]
    missing_names: tuple[str, ...]


@dataclass(frozen=True)
class SharedPrepTask:
    """A prep step that two or more of the chosen recipes need."""

    prep_task_id: int
    technique: str
    form: str | None
    ingredient_id: int
    ingredient_name: str
    recipe_ids: tuple[int, ...]


def _read(driver: Driver, query: str, **params) -> list[dict]:
    """Run a read query in a managed transaction and return rows as dicts.

    Rows are turned into dicts inside the transaction function: the driver's
    result stream closes when the transaction ends.
    """
    with driver.session() as session:
        return session.execute_read(
            lambda tx: [record.data() for record in tx.run(query, params)]
        )


def find_substitutes(
    ingredient_id: int,
    exclude_ids: Iterable[int] = (),
    limit: int = 5,
    driver: Driver | None = None,
) -> list[Substitute]:
    """Return up to `limit` ingredients that can replace `ingredient_id`, best first.

    exclude_ids drops candidates (for example allergens). Filtering by what the
    user actually has is the agent's job, done in Python on this list.
    """
    rows = _read(
        driver or get_driver(),
        FIND_SUBSTITUTES,
        ingredient_id=ingredient_id,
        exclude_ids=list(exclude_ids),
        limit=limit,
    )
    return [Substitute(**row) for row in rows]


def recipes_makeable_from(
    pantry_ids: Iterable[int],
    max_missing: int = 0,
    driver: Driver | None = None,
) -> list[MakeableRecipe]:
    """Return recipes with at most `max_missing` ingredients not in the pantry.

    Fewest missing first. A recipe that shares no ingredient with the pantry is
    never returned, even if max_missing is large.
    """
    rows = _read(
        driver or get_driver(),
        RECIPES_MAKEABLE_FROM,
        pantry_ids=list(pantry_ids),
        max_missing=max_missing,
    )
    return [
        MakeableRecipe(
            recipe_id=row["recipe_id"],
            name=row["name"],
            missing_ids=tuple(row["missing_ids"]),
            missing_names=tuple(row["missing_names"]),
        )
        for row in rows
    ]


def shared_prep_tasks(
    recipe_ids: Iterable[int], driver: Driver | None = None
) -> list[SharedPrepTask]:
    """Return prep tasks needed by 2 or more of `recipe_ids`, most shared first."""
    rows = _read(
        driver or get_driver(), SHARED_PREP_TASKS, recipe_ids=list(recipe_ids)
    )
    return [
        SharedPrepTask(
            prep_task_id=row["prep_task_id"],
            technique=row["technique"],
            form=row["form"],
            ingredient_id=row["ingredient_id"],
            ingredient_name=row["ingredient_name"],
            recipe_ids=tuple(sorted(row["recipe_ids"])),
        )
        for row in rows
    ]
