# Food.com pipeline

Turns the raw Food.com recipes file into a clean set we can load. Three stages. This file covers stages 1 and 2.

| Stage | Script | Status |
|---|---|---|
| 1. Clean and filter | `clean.py` | Done |
| 2. Add units and cuisines with an LLM | `augment.py` | In progress: code and a 3-recipe test done, pilot of 200 next |
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
| Ingredients | 3 to 20 ingredients (blank slots are not counted) | 338,888 |
| Category | Leave out desserts, breads, drinks, breakfast, sauces, spreads and non-food | **212,846** |
| Rating | Not required (half of all recipes have none) | 212,846 |

- The 90-minute cutoff is a judgment call, not derived from data. At 60 minutes we would keep 180,740 recipes, at 120 we would keep 222,269, so the count flattens above 90 (DECISIONS #25).
- We chose to leave categories out, not to pick dinner categories, so vegetarian and cuisine-labeled dinners stay in.
- The rules are named constants at the top of `clean.py`, so changing one and rerunning takes about 11 seconds.
- We estimate about 310 MB of data for the 212,846 recipes. That is over the free database limit once we add indexes and a second copy (DECISIONS #25).

### Checks
- 21 tests cover the helpers (times, names, dedupe, filters).
- Each run prints a report: rows in and out, missing values per column, the 10 biggest duplicate groups, and 5 sample rows.

## Stage 2: add units and cuisines with an LLM

The dataset has no ingredient units, and its quantities line up with the ingredient list in only about 22% of recipes. So for each recipe a Claude model reads the name, steps and raw lists and returns an amount and a unit for every ingredient, plus the cuisines (DECISIONS #23, #26).

Run it (this calls the paid API; it loads the key from `.env`):
`uv run --env-file .env --group pipelines python -m pipelines.foodcom.augment --pilot --limit 3`
Without `--limit` it runs the 200-recipe pilot. Reads `data/interim/recipes_subset.parquet`, appends to `data/interim/augment_results.jsonl`. Rerunning skips recipes already saved. Only `--pilot` exists; the full run is not built.

### How a recipe is processed
1. `build_user_message` turns the recipe row into numbered text.
2. `build_request_params` adds the rules (`SYSTEM_PROMPT`) and the answer shape (`build_output_schema`).
3. The model answers in that shape: `{ingredients: [{position, quantity, unit}], cuisines: [...]}`.
4. `validate_result` checks what the schema cannot (one entry per ingredient, null quantity only for "to taste", 1 to 3 cuisines).
5. On a problem, one retry names the problems. Then the result line is saved.

### The fixed lists
- **Units (19):** g, kg, ml, l, tsp, tbsp, cup, fl_oz, oz, lb, piece, clove, slice, can, package, bunch, pinch, dash, to_taste.
- **Cuisines (20):** american, italian, mexican, chinese, indian, thai, japanese, korean, vietnamese, greek, mediterranean, middle_eastern, french, spanish, german, british_irish, caribbean, african, cajun_creole, other.

### The cuisine baseline
`baseline_cuisines` maps Food.com's own keyword and category tags to our cuisines, with no model. It labels 33,945 of the 212,846 recipes (15.9%) and returns nothing for the other 84.1%. It cannot say italian, french, mediterranean or british_irish for most recipes, because no tag in the data names them. It is the floor the model must beat, and a rough check of the model on the recipes it covers.

### 3-recipe test (2026-10-27)
Three recipes (seed 42, so the same ones every time), all valid on the first try:

| Recipe | Ingredients | Cuisines | Tokens in / out | Attempts |
|---|---|---|---|---|
| Blue Ribbon Kielbasa | 5 | other, american | 1,450 / 504 | 1 |
| Gorgonzola Pear Crostini | 9 | italian, american | 1,531 / 635 | 1 |
| Chicken Breast With Grand Marinier Sauce | 13 | french, american | 1,719 / 966 | 1 |

Only the chicken recipe has raw quantities that do not line up with its ingredients, so it shows the model doing real work:

| # | Ingredient | Raw quantity | Model: amount |
|---|---|---|---|
| 0 | boneless skinless chicken breasts | 8 | 8 piece |
| 1 | salt | 1 | to taste |
| 2 | sugar | 1 | 1 tsp |
| 3 | white pepper | 1⁄2 | to taste |
| 4 | garlic powder | 1 | 1 tsp |
| 5 | ginger powder | 1 | 1 tsp |
| 6 | flour | 1 | 1 cup |
| 7 | sweet butter | (blank) | 2 tbsp |
| 8 | orange, zest of | 1⁄4 | 1 piece |
| 9 | onion | 1 | 1 piece |
| 10 | fresh ginger | 1⁄2 | 0.5 piece |
| 11 | lemongrass | 2 | 2 piece |
| 12 | Grand Marnier | 1 | 0.25 cup |

What this showed:
- The API accepted the schema, including the nullable `quantity`.
- Where the raw quantity was blank (sweet butter) or clearly shifted (Grand Marnier `1` became `0.25 cup`), the model took the amount from the steps.
- We looked at the answers by eye and they read as sensible. A few are debatable (ginger as `0.5 piece`, Polish sausage as `other`). **Accuracy has not been measured**; that is the job of the 30-recipe hand check after the pilot.
- Cost was about 1,570 input and 700 output tokens per recipe, roughly twice our estimate. Projected to 212,846 recipes that is about $54 through the Batches API or $108 with direct calls (Haiku 5.5 prices from the model table cached 2026-10-06). From 3 recipes this is a rough figure. We suspect thinking tokens explain the high output count but have not confirmed it.

### Not done yet
- The 200-recipe pilot, and the 30-recipe review file for a hand check.
- Whether turning thinking off cuts the cost without hurting accuracy.
- The full run through the Batches API, which waits on a budget agreement.
- Backing up `augment_results.jsonl` somewhere other than the laptop.

### Checks
- 26 tests cover the schema, prompt, validator, cuisine baseline, retry and resume. They use a fake client, so no test calls the API.
