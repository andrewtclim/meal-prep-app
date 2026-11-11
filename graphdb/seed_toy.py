"""Load the hand-made toy graph from graphdb/toy/*.csv into Neo4j.

The CSVs are shaped like the Postgres tables (ids are integers, ingredient names
are lowercase and singular). Every node carries source='toy', so the real graph
sync job can delete all of it with one query (WIPE_QUERY below) and MERGE the
real data under the same labels and keys.

Run: uv run --group agent --env-file .env python -m graphdb.seed_toy
     uv run --group agent --env-file .env python -m graphdb.seed_toy --wipe
"""

import argparse
import csv
from pathlib import Path

from neo4j import Driver

from graphdb.client import close_driver, get_driver
from graphdb.schema import apply_schema

TOY_DIR = Path(__file__).parent / "toy"

# The closed unit list from the units table (alembic bd4767ab853b, minus
# `package`, which c3a91e5d7f20 dropped).
UNITS = {
    "g", "kg", "ml", "l", "tsp", "tbsp", "cup", "fl_oz", "oz", "lb",
    "piece", "clove", "slice", "can", "bunch", "pinch", "dash", "to_taste",
}  # fmt: skip

# One query removes every toy node and, with DETACH, every edge touching them.
WIPE_QUERY = "MATCH (n {source: 'toy'}) DETACH DELETE n"

# MERGE finds a node by its unique key or creates it; SET then writes the other
# properties. Running the same statement twice therefore changes nothing.
# $rows is a parameter (never string formatting): safe from injection and the
# query plan is cached once and reused.
SEED_QUERIES = [
    """
    UNWIND $rows AS row
    MERGE (i:Ingredient {ingredient_id: row.ingredient_id})
    SET i.name = row.name, i.source = 'toy'
    """,
    """
    UNWIND $rows AS row
    MERGE (r:Recipe {recipe_id: row.recipe_id})
    SET r.name = row.name, r.source_ref = row.source_ref, r.source = 'toy'
    """,
    """
    UNWIND $rows AS row
    MERGE (p:PrepTask {prep_task_id: row.prep_task_id})
    SET p.technique = row.technique, p.form = row.form, p.source = 'toy'
    """,
    # Edges: MATCH both ends by key, MERGE the edge itself (no properties in the
    # MERGE pattern), then SET its properties. If a recipe lists the same
    # ingredient twice, the two lines collapse into one USED_IN edge.
    """
    UNWIND $rows AS row
    MATCH (i:Ingredient {ingredient_id: row.ingredient_id})
    MATCH (r:Recipe {recipe_id: row.recipe_id})
    MERGE (i)-[u:USED_IN]->(r)
    SET u.quantity = row.quantity, u.unit = row.unit, u.is_extra = row.is_extra
    """,
    """
    UNWIND $rows AS row
    MATCH (p:PrepTask {prep_task_id: row.prep_task_id})
    MATCH (i:Ingredient {ingredient_id: row.ingredient_id})
    MERGE (p)-[:APPLIES_TO]->(i)
    """,
    """
    UNWIND $rows AS row
    MATCH (r:Recipe {recipe_id: row.recipe_id})
    MATCH (p:PrepTask {prep_task_id: row.prep_task_id})
    MERGE (r)-[:REQUIRES]->(p)
    """,
    # (substitute)-[:SUBSTITUTES_FOR]->(original): "substitute can replace original".
    """
    UNWIND $rows AS row
    MATCH (s:Ingredient {ingredient_id: row.substitute_id})
    MATCH (o:Ingredient {ingredient_id: row.original_id})
    MERGE (s)-[e:SUBSTITUTES_FOR]->(o)
    SET e.weight = row.weight, e.model_version = row.model_version
    """,
]

# Which parsed table feeds which query above (APPLIES_TO reads prep_tasks again).
QUERY_TABLES = [
    "ingredients",
    "recipes",
    "prep_tasks",
    "recipe_ingredient",
    "prep_tasks",
    "recipe_prep_task",
    "substitutions",
]


def _text(value: str) -> str | None:
    """Return the string, or None for an empty CSV cell."""
    return value if value != "" else None


def _read(name: str, toy_dir: Path) -> list[dict[str, str]]:
    """Read one CSV file into a list of {column: text} rows."""
    with open(toy_dir / name, newline="") as handle:
        return list(csv.DictReader(handle))


def load_toy_data(toy_dir: Path = TOY_DIR) -> dict[str, list[dict]]:
    """Read every toy CSV and convert cells to Python types.

    Output: {table name: list of row dicts}. Ids are ints, quantity and weight
    are floats, is_extra is a bool, and empty cells become None.
    """
    return {
        "ingredients": [
            {"ingredient_id": int(r["ingredient_id"]), "name": r["name"]}
            for r in _read("ingredients.csv", toy_dir)
        ],
        "recipes": [
            {
                "recipe_id": int(r["recipe_id"]),
                "name": r["name"],
                "source_ref": int(r["source_ref"]) if r["source_ref"] else None,
            }
            for r in _read("recipes.csv", toy_dir)
        ],
        "recipe_ingredient": [
            {
                "recipe_id": int(r["recipe_id"]),
                "ingredient_id": int(r["ingredient_id"]),
                "quantity": float(r["quantity"]) if r["quantity"] else None,
                "unit": _text(r["unit"]),
                "is_extra": r["is_extra"] == "true",
            }
            for r in _read("recipe_ingredient.csv", toy_dir)
        ],
        "prep_tasks": [
            {
                "prep_task_id": int(r["prep_task_id"]),
                "ingredient_id": int(r["ingredient_id"]),
                "technique": r["technique"],
                "form": _text(r["form"]),
            }
            for r in _read("prep_tasks.csv", toy_dir)
        ],
        "recipe_prep_task": [
            {"recipe_id": int(r["recipe_id"]), "prep_task_id": int(r["prep_task_id"])}
            for r in _read("recipe_prep_task.csv", toy_dir)
        ],
        "substitutions": [
            {
                "substitute_id": int(r["substitute_id"]),
                "original_id": int(r["original_id"]),
                "weight": float(r["weight"]),
                "model_version": r["model_version"],
            }
            for r in _read("substitutions.csv", toy_dir)
        ],
    }


def validate_toy_data(data: dict[str, list[dict]]) -> None:
    """Raise ValueError if the toy data breaks a rule Neo4j Community can't enforce.

    Community has no "property must exist" constraints, so required fields,
    known units, weight range and dangling ids are checked here instead.
    """
    ingredient_ids = {r["ingredient_id"] for r in data["ingredients"]}
    recipe_ids = {r["recipe_id"] for r in data["recipes"]}
    task_ids = {r["prep_task_id"] for r in data["prep_tasks"]}
    errors = []
    if any(not r["name"] for r in data["ingredients"] + data["recipes"]):
        errors.append("every ingredient and recipe needs a name")
    if any(r["name"] != r["name"].strip().lower() for r in data["ingredients"]):
        errors.append("ingredient names must be lowercase and trimmed")
    for r in data["recipe_ingredient"]:
        if r["recipe_id"] not in recipe_ids or r["ingredient_id"] not in ingredient_ids:
            errors.append(f"USED_IN points at a missing id: {r}")
        if r["unit"] is not None and r["unit"] not in UNITS:
            errors.append(f"unit not in the closed list: {r['unit']}")
    for r in data["prep_tasks"]:
        if r["ingredient_id"] not in ingredient_ids:
            errors.append(f"PrepTask points at a missing ingredient: {r}")
    for r in data["recipe_prep_task"]:
        if r["recipe_id"] not in recipe_ids or r["prep_task_id"] not in task_ids:
            errors.append(f"REQUIRES points at a missing id: {r}")
    for r in data["substitutions"]:
        if not 0 <= r["weight"] <= 1:
            errors.append(f"weight outside 0 to 1: {r}")
        if {r["substitute_id"], r["original_id"]} - ingredient_ids:
            errors.append(f"SUBSTITUTES_FOR points at a missing ingredient: {r}")
    if errors:
        raise ValueError("Bad toy data:\n" + "\n".join(errors))


def _seed(tx, data: dict[str, list[dict]]) -> None:
    """Transaction function: run every seed query with its table's rows."""
    for query, table in zip(SEED_QUERIES, QUERY_TABLES, strict=True):
        tx.run(query, rows=data[table])


def seed_toy(driver: Driver | None = None, toy_dir: Path = TOY_DIR) -> None:
    """Apply the schema, validate the CSVs, then MERGE everything in one transaction.

    One transaction means all-or-nothing: a failure leaves the graph as it was.
    """
    driver = driver or get_driver()
    data = load_toy_data(toy_dir)
    validate_toy_data(data)
    apply_schema(driver)
    with driver.session() as session:
        session.execute_write(_seed, data)


def _wipe(tx) -> None:
    """Transaction function: delete every node tagged source='toy'."""
    tx.run(WIPE_QUERY)


def wipe_toy(driver: Driver | None = None) -> None:
    """Delete all toy nodes and their edges (what the graph sync job will do first)."""
    driver = driver or get_driver()
    with driver.session() as session:
        session.execute_write(_wipe)


def _count(tx) -> dict[str, int]:
    """Transaction function: count toy nodes per label and edges per type."""
    counts = {}
    for row in tx.run(
        "MATCH (n {source: 'toy'}) RETURN labels(n)[0] AS name, count(*) AS n"
    ):
        counts[row["name"]] = row["n"]
    for row in tx.run(
        "MATCH ({source: 'toy'})-[r]->({source: 'toy'}) "
        "RETURN type(r) AS name, count(*) AS n"
    ):
        counts[row["name"]] = row["n"]
    return counts


def count_toy(driver: Driver | None = None) -> dict[str, int]:
    """Return {label or relationship type: count} for the toy graph.

    Used to prove idempotency: counts after a second seed must equal the first.
    """
    driver = driver or get_driver()
    with driver.session() as session:
        return session.execute_read(_count)


def main() -> None:
    """Command line entry: seed (default) or --wipe, then print the toy counts."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wipe", action="store_true", help="delete the toy graph")
    args = parser.parse_args()
    if args.wipe:
        wipe_toy()
    else:
        seed_toy()
    print(count_toy())
    close_driver()


if __name__ == "__main__":
    main()
