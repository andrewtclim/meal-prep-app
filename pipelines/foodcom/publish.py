"""Stage 3, last step: publish the dbt results into the app tables in `public`.

dbt builds and tests the views in `staging` and `intermediate`. This script then
writes them into `public` (ingredients, recipes, recipe_ingredient, recipe_cuisine)
with the SQL files in publish_sql/, all inside ONE transaction: if any step fails,
nothing is written and `public` stays as it was (DECISIONS #27).

Run `dbt build` first, then:
    uv run --env-file .env python -m pipelines.foodcom.publish --dry-run
    uv run --env-file .env python -m pipelines.foodcom.publish

--dry-run does every step and then rolls the transaction back, so you see the row
counts without changing anything.
"""

import argparse
import os
from pathlib import Path

import psycopg

SQL_DIR = Path(__file__).parent / "publish_sql"

# Checks write nothing. Each returns the names that have no match in the lookup
# table; any row means "stop before writing". Label -> SQL file.
CHECKS = {
    "units missing from public.units": "check_missing_units.sql",
    "cuisines missing from public.cuisines": "check_missing_cuisines.sql",
}

# Write steps, in an order the foreign keys require: parents before the rows that
# point at them. recipe_ingredient and recipe_cuisine are cleared and rewritten per
# recipe; ingredients and recipes are upserted so their ids never change.
STEPS = [
    "10_upsert_ingredients.sql",
    "20_upsert_recipes.sql",
    "30_delete_recipe_ingredient.sql",
    "31_insert_recipe_ingredient.sql",
    "40_delete_recipe_cuisine.sql",
    "41_insert_recipe_cuisine.sql",
]


class MissingNamesError(Exception):
    """A unit or cuisine name has no row in its lookup table, so nothing was written."""


def read_sql(filename: str) -> str:
    """Return the text of one SQL file in publish_sql/."""
    return (SQL_DIR / filename).read_text()


def format_problems(problems: dict[str, list[str]]) -> str:
    """Turn {label: [names]} into a readable message, skipping labels with no names.

    Pure on purpose so it can be tested without a database.
    """
    lines = [
        f"{label}: {', '.join(names)}" for label, names in problems.items() if names
    ]
    return "\n".join(lines)


def find_missing_names(conn: psycopg.Connection) -> dict[str, list[str]]:
    """Run every check and return {label: [missing names]} (empty lists are kept)."""
    return {
        label: [row[0] for row in conn.execute(read_sql(filename)).fetchall()]
        for label, filename in CHECKS.items()
    }


def publish(conn: psycopg.Connection, dry_run: bool = False) -> list[tuple[str, int]]:
    """Run the checks, then every write step, in one transaction.

    Input: an open connection. With dry_run the transaction is rolled back at the end.
    Output: (step file, rows affected) per step, so nothing is silent.
    Raises MissingNamesError, before any write, if a unit or cuisine has no match.
    Any other error also rolls everything back: the exception leaves the
    `with conn.transaction()` block, and psycopg sends ROLLBACK.
    """
    counts = []
    with conn.transaction():
        problems = format_problems(find_missing_names(conn))
        if problems:
            raise MissingNamesError(problems)
        for filename in STEPS:
            counts.append((filename, conn.execute(read_sql(filename)).rowcount))
        if dry_run:
            raise psycopg.Rollback()  # rolls back and leaves the block quietly
    return counts


def main() -> None:
    """Command line entry point: publish, or with --dry-run show what would change."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run every step, print the row counts, then roll back",
    )
    args = parser.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        try:
            counts = publish(conn, dry_run=args.dry_run)
        except MissingNamesError as error:
            raise SystemExit(f"nothing written. Fix these first:\n{error}") from None

    for filename, rows in counts:
        print(f"  {filename}: {rows} rows")
    print("dry run: rolled back, nothing written" if args.dry_run else "published")


if __name__ == "__main__":
    main()
