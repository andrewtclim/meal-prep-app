"""Stage 3a of the Food.com pipeline: copy prepared recipes into Postgres.

Reads the cleaned recipes (stage 1) and the LLM answers (stage 2), joins them on
`source_ref`, and replaces the contents of `raw.foodcom_prepared`. dbt builds the
clean tables from that table (DECISIONS #14, #15, #24).

Run it:
    uv run --env-file .env python -m pipelines.foodcom.load --pilot --dry-run
    uv run --env-file .env python -m pipelines.foodcom.load --pilot
    uv run --env-file .env python -m pipelines.foodcom.load

Why a full replace: nothing points at the raw table, so replacing it is harmless,
and a bulk load is faster than checking every row for a conflict. The final write
into the public tables is different: other tables reference those ids, so that
step is an upsert.
"""

import argparse
import json
import os
from collections import Counter
from pathlib import Path

import pandas as pd
import psycopg

RECIPES_PATH = Path("data/interim/recipes_subset.parquet")
RESULTS_PATH = Path("data/interim/augment_results.jsonl")
PILOT_RESULTS_PATH = Path("pipelines/foodcom/pilot/results_thinking.jsonl")

TABLE = "raw.foodcom_prepared"

# Answer shapes this loader understands, as augment.py's SCHEMA_VERSION values. A
# record stamped with any other version (or none) is skipped, so an old-shape answer
# can never load as if it were current. Change this only together with the checks
# below and the dbt model that reads the answer (DECISIONS #26, #27).
KNOWN_SCHEMA_VERSIONS = (3,)

# Keys the model's answer must have. A missing one means the output shape changed
# (it has changed between schema versions), so we stop and say so instead of loading
# half-empty rows. `ingredients` and `extra_ingredients` are lists, `cuisine` a string.
REQUIRED_LIST_KEYS = ("ingredients", "extra_ingredients")
REQUIRED_STRING_KEYS = ("cuisine",)

# Column name -> Postgres type. `answer` is the model's answer kept whole as
# jsonb so dbt unpacks it and a change in its shape does not break the load.
CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    source_ref        bigint PRIMARY KEY,
    recipe_name       text NOT NULL,
    recipe_category   text,
    keywords          jsonb,
    ingredient_parts  jsonb NOT NULL,
    quantities_raw    jsonb,
    instructions      jsonb,
    servings          integer,
    total_minutes     integer,
    answer            jsonb NOT NULL,
    schema_version    integer NOT NULL,
    model             text,
    loaded_at         timestamptz NOT NULL DEFAULT now()
)
"""

COLUMNS = (
    "source_ref", "recipe_name", "recipe_category", "keywords", "ingredient_parts",
    "quantities_raw", "instructions", "servings", "total_minutes", "answer",
    "schema_version", "model",
)  # fmt: skip


def to_list(value) -> list:
    """Return a plain Python list for a numpy array, list, or missing value.

    pandas gives list columns back as numpy arrays, which json cannot write.
    A missing value becomes an empty list.
    """
    if value is None:
        return []
    return [str(item) for item in value]


def to_int(value) -> int | None:
    """Return a plain int, or None when the value is missing (pandas NA or NaN)."""
    return None if pd.isna(value) else int(value)


def validate_answer(answer: dict | None) -> list[str]:
    """Return the problems with one model answer, or an empty list if it is fine.

    Only checks that the keys we load exist and have the right type. Whether the
    values are correct is augment.py's validator and the dbt tests' job.
    """
    if not isinstance(answer, dict):
        return ["answer is missing"]
    problems = [
        f"missing key '{key}'"
        for key in REQUIRED_LIST_KEYS + REQUIRED_STRING_KEYS
        if key not in answer
    ]
    for key in REQUIRED_LIST_KEYS:
        if key in answer and not isinstance(answer[key], list):
            problems.append(f"'{key}' is not a list")
    for key in REQUIRED_STRING_KEYS:
        if key in answer and not isinstance(answer[key], str):
            problems.append(f"'{key}' is not a string")
    return problems


def read_results(path: Path) -> tuple[dict[int, dict], Counter]:
    """Read the LLM results file and return the usable records keyed by source_ref.

    Output: (records, skipped) where `skipped` counts records left out and why. A
    record is skipped when its status is not "ok", its `schema_version` is not in
    `KNOWN_SCHEMA_VERSIONS`, it has no source_ref, or its answer fails `validate_answer`. If a source_ref appears twice (a rerun), the
    last good record wins. The file is append-only, so later lines are newer.
    """
    records: dict[int, dict] = {}
    skipped: Counter = Counter()
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("status") != "ok":
                skipped["status not ok"] += 1
            elif record.get("schema_version") not in KNOWN_SCHEMA_VERSIONS:
                skipped["unknown schema_version"] += 1
            elif record.get("source_ref") is None:
                skipped["no source_ref"] += 1
            elif validate_answer(record.get("result")):
                skipped["bad answer shape"] += 1
            else:
                records[int(record["source_ref"])] = record
    return records, skipped


def build_rows(recipes: pd.DataFrame, results: dict[int, dict]) -> tuple[list[tuple], Counter]:
    """Join recipes to results on source_ref and return one tuple per recipe.

    Inputs: the cleaned recipes and the usable results. Output: (rows, stats). Rows
    follow `COLUMNS`, with list columns and the answer already turned into JSON text
    for the jsonb columns. Only recipes that have a usable result are loaded, so the
    results file decides what lands in the database. `stats` counts results whose
    recipe is not in the cleaned file, which means stage 1 and stage 2 are out of step.
    """
    stats: Counter = Counter()
    wanted = recipes[recipes["source_ref"].isin(results)]
    stats["results without a recipe"] = len(results) - len(wanted)
    rows = []
    for recipe in wanted.itertuples(index=False):
        record = results[int(recipe.source_ref)]
        rows.append((
            int(recipe.source_ref),
            recipe.name,
            None if pd.isna(recipe.recipe_category) else recipe.recipe_category,
            json.dumps(to_list(recipe.keywords)),
            json.dumps(to_list(recipe.ingredient_parts)),
            json.dumps(to_list(recipe.quantities_raw)),
            json.dumps(to_list(recipe.instructions)),
            to_int(recipe.recipe_servings),
            to_int(recipe.total_minutes),
            json.dumps(record["result"]),
            int(record["schema_version"]),
            record.get("model"),
        ))
    return rows, stats


def replace_table(conn: psycopg.Connection, rows: list[tuple]) -> None:
    """Replace everything in the raw table with `rows`, in one transaction.

    If anything fails, the transaction rolls back and the old data stays. The table
    is created if it does not exist. If its columns ever change, drop it by hand
    first: TRUNCATE keeps the old shape, and dropping would also fail while dbt
    views depend on it.
    """
    with conn.transaction():
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(f"TRUNCATE {TABLE}")
        with conn.cursor() as cur, cur.copy(f"COPY {TABLE} ({', '.join(COLUMNS)}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)


def print_report(n_results: int, skipped: Counter, stats: Counter, n_rows: int) -> None:
    """Print how many records were read, skipped, and loaded, so nothing is silent."""
    print(f"usable results read: {n_results}")
    for reason, count in skipped.items():
        print(f"  skipped, {reason}: {count}")
    for reason, count in stats.items():
        if count:
            print(f"  {reason}: {count}")
    print(f"rows to load into {TABLE}: {n_rows}")


def main() -> None:
    """Command line entry point: build the rows, report, and load unless --dry-run."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pilot", action="store_true", help="read the committed 20-recipe pilot results")
    parser.add_argument("--recipes", type=Path, default=RECIPES_PATH)
    parser.add_argument("--results", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="build and report, do not touch the database")
    args = parser.parse_args()

    results_path = args.results or (PILOT_RESULTS_PATH if args.pilot else RESULTS_PATH)
    results, skipped = read_results(results_path)
    recipes = pd.read_parquet(args.recipes)
    rows, stats = build_rows(recipes, results)
    print_report(len(results), skipped, stats, len(rows))
    if args.dry_run:
        print("dry run: database not touched")
        return
    if not rows:
        raise SystemExit("nothing to load; refusing to empty the table")

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        replace_table(conn, rows)
    print(f"loaded {len(rows)} rows into {TABLE}")


if __name__ == "__main__":
    main()
