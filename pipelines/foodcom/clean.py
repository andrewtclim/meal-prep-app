"""Stage 1 of the Food.com pipeline: clean the raw recipes parquet.

Reads data/raw/recipes.parquet (the untouched Kaggle download) and will write
data/interim/recipes_clean.parquet, one row per recipe. We build this file one
block at a time and check the data after each block, so a bug shows up where
it was introduced rather than three steps later.

Run:  uv run python -m pipelines.foodcom.clean            (full clean set + report)
      uv run python -m pipelines.foodcom.clean --subset   (also write the chosen subset)
"""

import argparse
import html
import json
import math
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

# Lists whose items are matched to each other by position (see to_str_list).
POSITIONAL_COLUMNS = {"RecipeIngredientParts", "RecipeIngredientQuantities"}

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

# --- Size funnel: candidate filters for the subset that goes to the LLM and the
# database. Named constants so the choice is visible and editable in one place.
SUBSET_PATH = Path("data/interim/recipes_subset.parquet")
MAX_TOTAL_MINUTES = 90  # weeknight-friendly
MIN_INGREDIENTS = 3  # fewer is usually a drink or a one-liner
MAX_INGREDIENTS = 20  # more is a project, not a weeknight dinner
# Food.com's 300+ categories mix dish types, single ingredients ("Potato"),
# cuisines, time buckets ("< 30 Mins") and diets, and a recipe has only one, so
# an include list of "dinner" categories would miss vegetarian and cuisine-filed
# dinners. Instead we exclude the clearly-not-dinner groups and keep everything
# else, including ambiguous ones (Lunch/Snacks, Vegetable, single fruits).
# Recipes with no category are kept too.
EXCLUDED_CATEGORIES = {
    # sweets and baking
    "Dessert", "Cheesecake", "Frozen Desserts", "Ice Cream", "Pie", "Tarts", "Scones",
    "Bar Cookie", "Drop Cookies", "Chocolate Chip Cookies", "Candy", "Gelatin", "Jellies",
    "Sweet", "Desserts Fruit", "Breads", "Quick Breads", "Yeast Breads", "Sourdough Breads",
    "Bread Machine",
    # drinks
    "Beverages", "Punch Beverage", "Smoothies", "Shakes",
    # breakfast
    "Breakfast", "Brunch", "Breakfast Eggs", "Oatmeal",
    # condiments and bases
    "Sauces", "Salad Dressings", "Spreads", "Chutneys", "Stocks",
    # not food
    "Bath/Beauty", "Household Cleaner", "Homeopathy/Remedies",
}  # fmt: skip

# Half of all recipes have no rating (nobody reviewed them, not "they are bad").
# Off by default so the subset keeps them; set True to require a rating.
REQUIRE_RATING = False

# Supabase free tier. The estimate below is for data only; see estimate_row_bytes.
DB_LIMIT_MB = 500


def to_snake_case(name: str) -> str:
    """Convert a CamelCase column name to snake_case ("CookTime" -> "cook_time").

    Why: Postgres folds unquoted names to lowercase, so CamelCase columns would
    be awkward to query. Doing it mechanically here keeps the rule in one place.
    """
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def to_str_list(value, keep_blanks: bool = False) -> list[str]:
    """Turn a parquet list cell into a plain Python list of cleaned strings.

    Input: a numpy array, a list, or a missing value (None or NaN).
    Output: a list of strings with HTML entities decoded and whitespace trimmed;
    a missing value becomes an empty list.

    Why: numpy arrays behave differently from lists (truth tests, JSON, equality),
    so we convert once, here.

    keep_blanks: positional lists (ingredient parts and quantities) must keep
    blank elements, because items are matched by position and removing a blank
    would shift every later item. For all other lists, blanks are junk and are
    dropped.
    """
    # Strings are iterable too, so rule them out; None and NaN are not iterable.
    if isinstance(value, str) or not hasattr(value, "__iter__"):
        return []
    cleaned = ["" if item is None else html.unescape(str(item)).strip() for item in value]
    return cleaned if keep_blanks else [item for item in cleaned if item]


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
        keep = col in POSITIONAL_COLUMNS
        df[col] = df[col].map(lambda v, keep=keep: to_str_list(v, keep_blanks=keep))
    return df


def parse_duration_minutes(value) -> int | None:
    """Convert an ISO 8601 duration like "PT1H30M" into whole minutes (90).

    Input: a duration string, or a missing value (None / NaN).
    Output: an int, or None if the value is missing or not a duration we trust.
    Seconds round up to whole minutes ("PT30S" -> 1); "PT0S" stays 0.

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
    # Round seconds up: Python's round() sends 30s to 0 (round-half-to-even), which
    # would then read as "no time". Any positive duration is at least 1 minute.
    return hours * 60 + minutes + math.ceil(seconds / 60)


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


def count_nonblank(items: list[str]) -> int:
    """Count the non-blank strings in a list.

    Why not len(): ingredient_parts may keep blank slots so it stays aligned
    with quantities, and len() would count those blanks as ingredients.
    """
    return sum(1 for item in items if item)


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


def singularize(word: str) -> str:
    """Strip a plural ending with a few simple rules ("cookies" -> "cooky").

    The result is only ever used as a grouping key, never shown or stored, so
    it does not need to be real English, just the same for "X" and "Xs". The
    rules are deliberately small; a library like inflect would handle more
    cases but is another dependency for a key we only use once.
    """
    # "ies" and "ie" both map to "y", so cookie/cookies and berry/berries
    # each land on one key (a plain "ies" -> "y" rule would split pie/pies).
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 2 and word.endswith("ie"):
        return word[:-2] + "y"
    if len(word) <= 3:
        return word
    if word.endswith(("oes", "ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    # Keep words that end in s but are not plurals: glass, hummus, couscous, lens.
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def normalize_name(name: str, source_ref: int) -> str:
    """Build the duplicate-detection key for a recipe name.

    Lowercase, drop apostrophes, turn other punctuation into spaces, collapse
    whitespace, and singularize the last word, so "Lemonade", "lemonade!" and
    "Lemonades" share a key. A name with no letters or digits at all gets a
    unique key from its id, so empty names are never merged into one giant
    "duplicate" group.

    Known limit: a hyphen becomes a space, so "Chocolate-Chip Cookies" matches
    "Chocolate Chip Cookies" but "lemon-ade" does not match "lemonade". Joining
    hyphens would fix one and break the other; fixing both needs a dictionary.
    """
    text = re.sub(r"[\'\u2019]", "", name.lower())
    words = re.sub(r"[^\w\s]|_", " ", text).split()
    if not words:
        return f"__no_name_{source_ref}"
    words[-1] = singularize(words[-1])
    return " ".join(words)


def dedupe_by_name(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep one recipe per normalized name: the best rated, ties broken fixed.

    Output: the deduped frame, and a table of the 10 largest duplicate groups
    (key, size, example names) for a human sanity check.

    Order of preference: highest rating, then most reviews, then lowest
    source_ref. The last rule makes the result identical on every rerun.
    Missing ratings sort last, so an unrated copy never beats a rated one.
    Tradeoff: different recipes can share a name ("Banana Bread"); we accept
    that loss to keep the table small and the names unambiguous.
    """
    df = df.assign(name_key=[normalize_name(n, r) for n, r in zip(df["name"], df["source_ref"])])

    sizes = df["name_key"].value_counts()
    top = sizes.head(10).rename("size").reset_index()
    top["example_names"] = [
        list(dict.fromkeys(df.loc[df["name_key"] == key, "name"]))[:3] for key in top["name_key"]
    ]

    ranked = df.sort_values(
        ["aggregated_rating", "review_count", "source_ref"],
        ascending=[False, False, True],
        na_position="last",
    )
    deduped = ranked.drop_duplicates(subset="name_key", keep="first").drop(columns="name_key")
    return deduped.sort_values("source_ref").reset_index(drop=True), top


def add_recipe_key(df: pd.DataFrame) -> pd.DataFrame:
    """Add recipe_key: a sequential id 1..N, ordered by source_ref.

    Why a second id: source_ref is Food.com's (stable, but gappy). recipe_key
    is ours, for reading and joining within one run. It is a POSITION: if a
    stage 1 change drops or adds a recipe, the numbers shift. Never use it as a
    stored identity (saved LLM results are keyed on source_ref). Postgres assigns
    the real recipe_id in stage 3. Call after dedupe so the numbers have no holes.
    """
    df = df.sort_values("source_ref").reset_index(drop=True)
    df.insert(0, "recipe_key", range(1, len(df) + 1))
    return df


def finalize_types(df: pd.DataFrame) -> pd.DataFrame:
    """Turn the two count columns back into nullable integers.

    pandas reads review_count and recipe_servings as floats because some values
    are missing. Int64 keeps them as whole numbers with real nulls, which maps
    cleanly onto Postgres integer columns in stage 3.
    """
    for col in ["review_count", "recipe_servings"]:
        df[col] = df[col].astype("Int64")
    return df


def estimate_row_bytes(df: pd.DataFrame) -> pd.Series:
    """Roughly estimate each recipe's size in Postgres, in bytes.

    Counts UTF-8 bytes of every text value (plus ~4 bytes of header per text or
    array element), 8 bytes per numeric column, and a 24-byte row header.
    It ignores indexes and TOAST compression of long text, so treat it as a
    rough upper bound on the table data. The real number comes from measuring a
    1,000-recipe sample in stage 3.
    """
    text_cols = ["name", "description", "recipe_category", "recipe_yield"]
    list_cols = ["images", "keywords", "ingredient_parts", "quantities_raw", "instructions"]
    total = pd.Series(24, index=df.index, dtype="int64")
    for col in text_cols:
        total += df[col].map(lambda v: len(v.encode()) + 4 if isinstance(v, str) else 0)
    for col in list_cols:
        total += df[col].map(lambda items: 24 + sum(len(x.encode()) + 4 for x in items))
    numeric = df.select_dtypes("number").shape[1]
    return total + 8 * numeric


def funnel_steps() -> list[tuple[str, callable]]:
    """The subset filters, in order, as (label, mask function) pairs."""
    steps = [
        (f"total <= {MAX_TOTAL_MINUTES} min", lambda d: (d["total_minutes"] <= MAX_TOTAL_MINUTES).fillna(False)),
        (
            f"{MIN_INGREDIENTS}-{MAX_INGREDIENTS} ingredients",
            lambda d: d["ingredient_parts"].map(count_nonblank).between(MIN_INGREDIENTS, MAX_INGREDIENTS),
        ),
        ("not an excluded category", lambda d: ~d["recipe_category"].isin(EXCLUDED_CATEGORIES)),
    ]
    if REQUIRE_RATING:
        steps.append(("has a rating", lambda d: d["aggregated_rating"].notna()))
    return steps


def apply_funnel(df: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[str, int, float]]]:
    """Apply each filter in turn and record (label, rows left, estimated MB).

    Output: the fully filtered frame (the candidate subset) and the table that
    shows how much each filter cut. Each row is cumulative: it includes every
    filter above it.
    """
    row_bytes = estimate_row_bytes(df)
    table = [("all clean rows", len(df), row_bytes.sum() / 1e6)]
    for label, make_mask in funnel_steps():
        df = df[make_mask(df)]
        table.append((label, len(df), row_bytes[df.index].sum() / 1e6))
    return df, table


def jsonable(value):
    """Make one cell printable as JSON: shorten lists, turn missing into null."""
    if isinstance(value, list):
        return value[:3] + (["..."] if len(value) > 3 else [])
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None
    return value.item() if hasattr(value, "item") else value


def print_validation_report(df: pd.DataFrame, rows_in: int) -> None:
    """Print the checks we read before trusting this stage's output."""
    print(f"\n=== validation report: {rows_in:,} rows in, {len(df):,} out ===")

    nulls = (df.isna().mean() * 100).round(1)
    print("\nnull % (columns with any missing values):\n" + nulls[nulls > 0].to_string())

    print("\ntotal_minutes distribution:")
    print(df["total_minutes"].astype("float").describe(percentiles=[0.1, 0.5, 0.9, 0.99]).round(1).to_string())

    print(f"\nquantities_aligned: {df['quantities_aligned'].mean():.1%}")

    lengths = pd.DataFrame({c: df[c].map(len) for c in ["ingredient_parts", "instructions", "keywords", "images"]})
    print("\narray lengths:\n" + lengths.describe().loc[["min", "50%", "max", "mean"]].round(1).to_string())

    print("\n5 random cleaned rows (lists shortened to 3 items):")
    for _, row in df.sample(5, random_state=42).iterrows():
        print(json.dumps({k: jsonable(v) for k, v in row.items()}, ensure_ascii=False)[:900])


def main() -> None:
    """Run every block, print the funnel and report, and write the output files."""
    parser = argparse.ArgumentParser(description="Clean the Food.com recipes parquet.")
    parser.add_argument("--subset", action="store_true", help=f"also write {SUBSET_PATH} using the funnel filters")
    args = parser.parse_args()

    df = load_raw()
    rows_in = len(df)
    df = make_arrays_plain(df)
    df = trim_and_rename(df)
    df = add_minutes_columns(df)
    df, removed = drop_junk_rows(df)
    for rule, count in removed.items():
        print(f"removed {count:,} rows: {rule}")
    df = add_quantities_aligned(df)
    before_dedupe = len(df)
    df, top = dedupe_by_name(df)
    df = add_recipe_key(df)
    df = finalize_types(df)
    print(f"removed {before_dedupe - len(df):,} duplicate names; {len(df):,} recipes left")
    print("10 largest duplicate groups:")
    for row in top.itertuples():
        print(f"  {row.size:>5}  {row.name_key!r}  e.g. {row.example_names}")

    subset, table = apply_funnel(df)
    print("\n=== size funnel (cumulative; est. MB is one copy of the data, no indexes) ===")
    print(f"{'filter':<26}{'rows':>10}{'est MB':>10}")
    for label, rows, mb in table:
        print(f"{label:<26}{rows:>10,}{mb:>10,.0f}")
    print(f"Supabase free tier limit: {DB_LIMIT_MB} MB for everything (tables, indexes, embeddings)")

    print_validation_report(df, rows_in)

    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CLEAN_PATH, index=False)
    print(f"\nwrote {CLEAN_PATH} ({len(df):,} rows)")
    if args.subset:
        subset.reset_index(drop=True).to_parquet(SUBSET_PATH, index=False)
        print(f"wrote {SUBSET_PATH} ({len(subset):,} rows)")


if __name__ == "__main__":
    main()
