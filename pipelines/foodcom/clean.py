"""Stage 1 of the Food.com pipeline: clean the raw recipes parquet.

Reads data/raw/recipes.parquet (the untouched Kaggle download) and will write
data/interim/recipes_clean.parquet, one row per recipe. We build this file one
block at a time and check the data after each block, so a bug shows up where
it was introduced rather than three steps later.

Run:  uv run python -m pipelines.foodcom.clean
"""

import html
import json
import re
from pathlib import Path

import pandas as pd

RAW_PATH = Path("data/raw/recipes.parquet")
CLEAN_PATH = Path("data/interim/recipes_clean.parquet")

# People columns and a publish date: not needed by the app, and author names
# are personal data we have no reason to carry around.
DROP_COLUMNS = ["AuthorId", "AuthorName", "DatePublished"]

# Columns stored as lists of strings. Parquet hands them back as numpy arrays.
ARRAY_COLUMNS = [
    "Images",
    "Keywords",
    "RecipeIngredientParts",
    "RecipeIngredientQuantities",
    "RecipeInstructions",
]

# Applied after the mechanical snake_case conversion. We choose these names
# now so later stages (and the Postgres tables) don't have to rename again.
RENAMES = {
    "recipe_id": "source_ref",  # Food.com's own id, stable across reloads
    "recipe_ingredient_parts": "ingredient_parts",
    "recipe_ingredient_quantities": "quantities_raw",  # unparsed strings; stage 2 produces numbers
    "recipe_instructions": "instructions",
}


def to_snake_case(name: str) -> str:
    """Convert a CamelCase column name to snake_case ("CookTime" -> "cook_time").

    Why: Postgres folds unquoted names to lowercase, so CamelCase columns would
    be awkward to query. Doing it mechanically here keeps the rule in one place.
    """
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def to_str_list(value) -> list[str]:
    """Turn a parquet list cell into a plain Python list of cleaned strings.

    Input: a numpy array, a list, or a missing value (None or NaN).
    Output: a list of strings with HTML entities decoded and whitespace trimmed;
    a missing value becomes an empty list.

    Why: numpy arrays behave differently from lists (truth tests, JSON, equality),
    so we convert once, here. We do NOT drop blank elements: ingredient parts and
    quantities are matched by position, and removing a blank would shift every
    later item and break that matching.
    """
    # Strings are iterable too, so rule them out; None and NaN are not iterable.
    if isinstance(value, str) or not hasattr(value, "__iter__"):
        return []
    return ["" if item is None else html.unescape(str(item)).strip() for item in value]


def load_raw(path: Path = RAW_PATH) -> pd.DataFrame:
    """Read the raw parquet into a DataFrame (all 522k rows, original columns)."""
    return pd.read_parquet(path)


def trim_and_rename(df: pd.DataFrame) -> pd.DataFrame:
    """Drop unwanted columns, make the id an integer, and rename to snake_case.

    Why the id cast: the file stores RecipeId as a float (38.0). We want integers
    so ids compare and join exactly. astype raises on missing values, which is
    what we want: an id-less recipe is a data problem we should see, not hide.
    """
    df = df.drop(columns=DROP_COLUMNS)
    df["RecipeId"] = df["RecipeId"].astype("int64")
    return df.rename(columns=lambda c: RENAMES.get(to_snake_case(c), to_snake_case(c)))


def make_arrays_plain(df: pd.DataFrame) -> pd.DataFrame:
    """Convert every array column to a plain list of cleaned strings.

    Runs on the original CamelCase names, so call it before trim_and_rename.
    """
    for col in ARRAY_COLUMNS:
        df[col] = df[col].map(to_str_list)
    return df


def main() -> None:
    """Run the blocks written so far and print a quick look at the result."""
    df = load_raw()
    print(f"loaded: {len(df):,} rows, {df.shape[1]} columns")

    df = make_arrays_plain(df)
    df = trim_and_rename(df)
    print(f"after block 1: {len(df):,} rows, {df.shape[1]} columns\n")
    print(df.dtypes.to_string())

    print("\nfirst row:")
    row = df.iloc[0].to_dict()
    print(json.dumps({k: (v if not isinstance(v, list) else v[:3]) for k, v in row.items()},
                     indent=2, default=str)[:1800])


if __name__ == "__main__":
    main()
