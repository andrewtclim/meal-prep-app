# Food.com pipeline

Turns the raw Food.com recipes file into a clean set we can load. Three stages. This file covers stage 1.

| Stage | Script | Status |
|---|---|---|
| 1. Clean and filter | `clean.py` | Done |
| 2. Add units and cuisines with an LLM | `augment.py` | Next |
| 3. Load into Postgres with dbt | `load.py` and `dbt/` | Later |

## Stage 1: clean

Run it: `uv run python -m pipelines.foodcom.clean --subset`
Reads `data/raw/recipes.parquet`. Writes `data/interim/recipes_clean.parquet` (all cleaned recipes) and, with `--subset`, `recipes_subset.parquet` (the ones we keep).

### Cleaning the columns
- We loaded 522,517 recipes.
- We dropped `AuthorId`, `AuthorName` and `DatePublished`.
- We renamed every column from CamelCase to snake_case (`CookTime` became `cook_time`). Food.com's id became `source_ref`.
- We turned the recipe id from a decimal (`38.0`) into a whole number (`38`).
- We turned the list columns (ingredients, quantities, keywords, images, instructions) from numpy arrays into plain Python lists. We decoded HTML like `&amp;` and trimmed spaces.
- We kept blank entries only in ingredient parts and quantities, because those two lists are matched by position. Every other list had its blanks removed.
- We turned the times from `"PT1H30M"` into `90` minutes. Times we could not read, and negative times, became missing.
- A total time of `"PT0S"` became missing, because no recipe takes zero minutes.
- We added `time_suspect`, which is true when the total time is over 24 hours.
- We removed 2,219 recipes with no ingredients and 2 with no instructions.
- We added `quantities_aligned`, which is true when a recipe has as many quantities as ingredients. Only about 22% do, so we kept the rest. Stage 2 pairs them up.
- We removed 91,877 duplicate recipe names (`"Lemonade"` and `"lemonades!"` count as the same name). We kept the best-rated copy, then the most-reviewed, then the lowest `source_ref`, so every rerun picks the same one. That left 428,419 recipes.
- We added our own `recipe_key`, numbered 1 to N.
- We turned `review_count` and `recipe_servings` into whole numbers that can be missing.

### Choosing which recipes to keep
Each filter applies after the one above it.

| Filter | Rule | Recipes left |
|---|---|---|
| Start | All cleaned recipes | 428,419 |
| Time | Total time of 90 minutes or less | 362,209 |
| Ingredients | 3 to 20 ingredients | 338,888 |
| Category | Leave out desserts, breads, drinks, breakfast, sauces, spreads and non-food | **212,846** |
| Rating | Not required (half of all recipes have none) | 212,846 |

- We chose to leave categories out, not to pick dinner categories, so vegetarian and cuisine-labeled dinners stay in.
- The rules are named constants at the top of `clean.py`, so changing one and rerunning takes about 11 seconds.
- We estimate about 310 MB of data for the 212,846 recipes. That is over the free database limit once we add indexes and a second copy (DECISIONS #25).

### Checks
- 21 tests cover the helpers (times, names, dedupe, filters).
- Each run prints a report: rows in and out, missing values per column, the 10 biggest duplicate groups, and 5 sample rows.
