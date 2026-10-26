"""Stage 1 of the Food.com pipeline: clean the raw recipes parquet.

Reads data/raw/recipes.parquet (the untouched Kaggle download) and will write
data/interim/recipes_clean.parquet, one row per recipe. We build this file one
block at a time and check the data after each block, so a bug shows up where
it was introduced rather than three steps later.

Run:  uv run python -m pipelines.foodcom.clean
"""

import html
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

# ISO 8601 duration columns (after snake_case) -> integer-minute columns.
TIME_COLUMNS = {
    "cook_time": "cook_minutes",
    "prep_time": "prep_minutes",
    "total_time": "total_minutes",
}

# Totals longer than this are usually marinating, proofing or freezing, not
# active cooking. We flag them instead of dropping them (the recipe is fine).
SUSPECT_TOTAL_MINUTES = 24 * 60

# Only the shapes that occur in this dataset: PT<h>H<m>M<s>S with any part
# optional. Day-based durations (P1D) and negative parts never match, so they
# come back as missing rather than as a wrong number.
DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


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


def parse_duration_minutes(value) -> int | None:
    """Convert an ISO 8601 duration like "PT1H30M" into whole minutes (90).

    Input: a duration string, or a missing value (None / NaN).
    Output: an int, or None if the value is missing or not a duration we trust.

    Why None and not 0: a missing time and a zero time mean different things,
    and a 0 would quietly pass any "under 90 minutes" filter later.
    """
    if not isinstance(value, str):
        return None
    match = DURATION_RE.match(value.strip())
    # "PT" alone matches the pattern but has no parts, so it is not a duration.
    if match is None or not any(match.groups()):
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 60 + minutes + round(seconds / 60)


def add_minutes_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add cook/prep/total minutes and a time_suspect flag; drop the ISO strings.

    Minutes use pandas' nullable Int64 so a missing time stays missing instead
    of turning the whole column into floats. A total of 0 minutes is set to
    missing: Food.com writes "PT0S" when no time was entered (2,129 rows), and
    no recipe takes zero minutes. Prep and cook zeros are kept, since "no prep"
    is plausible. Source strings are dropped because data/raw still has them.
    """
    for source, target in TIME_COLUMNS.items():
        df[target] = df[source].map(parse_duration_minutes).astype("Int64")
    df["total_minutes"] = df["total_minutes"].mask(df["total_minutes"] == 0)
    df["time_suspect"] = (df["total_minutes"] > SUSPECT_TOTAL_MINUTES).fillna(False)
    return df.drop(columns=list(TIME_COLUMNS))


def has_content(items: list[str]) -> bool:
    """True if the list has at least one non-blank string.

    Why not just len(items) > 0: a list of blanks (one recipe's instructions)
    is as useless as an empty list, and len() would let it through.
    """
    return any(item != "" for item in items)


def drop_junk_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Remove recipes we cannot use: no ingredients, or no instructions.

    Output: the filtered frame, and how many rows each rule removed. Rules run
    in order and each count is measured on what the previous rule left, so a
    recipe missing both is counted once, under the first rule.

    Why drop them: stage 2 reads the instructions to work out units, and a
    recipe with no ingredients has nothing to plan with.
    """
    rules = {
        "no ingredient parts": ~df["ingredient_parts"].map(has_content),
        "no instructions": ~df["instructions"].map(has_content),
    }
    removed = {}
    for name, is_junk in rules.items():
        is_junk = is_junk.loc[df.index]  # df shrinks after each rule
        removed[name] = int(is_junk.sum())
        df = df[~is_junk]
    return df.reset_index(drop=True), removed


def add_quantities_aligned(df: pd.DataFrame) -> pd.DataFrame:
    """Add quantities_aligned: True when parts and quantities have equal length.

    We do not drop misaligned rows: only about 22% line up (the audit found the
    same), so dropping them would discard most of the dataset. Equal length is a
    necessary condition for matching by position, not proof; stage 2 does the
    real pairing. The flag lets us measure that stage against a known-good group.
    """
    df["quantities_aligned"] = df["ingredient_parts"].map(len) == df["quantities_raw"].map(len)
    return df


def main() -> None:
    """Run the blocks written so far and print a quick look at the result."""
    df = load_raw()
    print(f"loaded: {len(df):,} rows, {df.shape[1]} columns")

    df = make_arrays_plain(df)
    df = trim_and_rename(df)
    print(f"after block 1: {len(df):,} rows, {df.shape[1]} columns")

    df = add_minutes_columns(df)
    print(f"after block 2: {len(df):,} rows, {df.shape[1]} columns\n")
    minutes = ["cook_minutes", "prep_minutes", "total_minutes"]
    print("missing values:\n" + df[minutes].isna().sum().to_string())
    print("\nminutes summary:\n" + df[minutes].describe(percentiles=[0.5, 0.9, 0.99]).round(1).to_string())
    print(f"\ntime_suspect (total > 24h): {int(df['time_suspect'].sum()):,} rows")
    print("\nsample:\n" + df[["name", *minutes, "time_suspect"]].head(5).to_string())

    df, removed = drop_junk_rows(df)
    df = add_quantities_aligned(df)
    print(f"\nafter block 3: {len(df):,} rows, {df.shape[1]} columns")
    for rule, count in removed.items():
        print(f"  removed {count:,} rows: {rule}")
    print(f"  quantities_aligned: {df['quantities_aligned'].mean():.1%} of kept rows")

if __name__ == "__main__":
    main()
