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
- We added our own `recipe_key`, numbered 1 to N after dedupe. It is a position, so it can shift if stage 1 changes. Never store results against it; stage 2 keys on Food.com's `source_ref`.
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
Without `--limit` it runs the 200-recipe pilot. Reads `data/interim/recipes_subset.parquet`, appends to `data/interim/augment_results.jsonl`. Rerunning skips recipes already saved (matched on Food.com's `source_ref`). `--compare thinking` or `--compare nothinking` runs the stratified 20-recipe comparison below. Only these two exist; the full run is not built.

### How a recipe is processed
1. `build_user_message` turns the recipe row into numbered text.
2. `build_request_params` adds the rules (`SYSTEM_PROMPT`) and the answer shape (`build_output_schema`).
3. The model answers in that shape: `{ingredients: [{position, quantity, unit}], extra_ingredients: [{name, quantity, unit}], cuisines: [...]}`.
4. `validate_result` checks what the schema cannot (one entry per ingredient, null quantity only for "to taste", 1 to 2 cuisines, and for extras: at most 6, no salt or water, no repeat of a listed name).
5. On a problem, one retry names the problems. Then the result line is saved.

### The ingredient list is not complete (2026-10-29)
We first treated `ingredient_parts` as the full list. It is not: 75% of recipes have more quantities than names, and the steps use items the list lacks. Example, Joe's Saute Onions:

| Field | Value |
|---|---|
| `ingredient_parts` (4) | olive oil, salt, butter, sugar |
| `quantities_raw` (5) | `1 -3` and four blanks |
| Steps | "Slice off the root and top ends of the onions, peel the onions..." |

So the model also returns `extra_ingredients` for items the steps clearly use that the list lacks (here: onions). Leftover quantities with no matching item are dropped. A rough keyword count puts the gap about 21 points above the noise floor in the "more quantities" group; it is an estimate, not a measured miss rate (DECISIONS #26 amendment). The 200-recipe pilot below ran on the old schema.

A 5-recipe test on the new schema ($0.0035) passed validation on the first try and found every missing item we had spotted by eye (onions, feta, oil, taco seasoning, squid and others). Accuracy is not measured; the 20-recipe pilot hand check does that.

### The fixed lists
- **Units (19):** g, kg, ml, l, tsp, tbsp, cup, fl_oz, oz, lb, piece, clove, slice, can, package, bunch, pinch, dash, to_taste.
- **Cuisines (90, at most 2 per recipe):** Food.com's own cuisine tags plus the ones it lacks (italian, french, american, british, irish, mediterranean...), grouped by region in `CUISINES`. Merged on purpose: scottish and welsh into british, szechuan and hunan into chinese, lebanese and turkish into middle_eastern. A region may pair with its parent (chinese, cantonese). Umbrella labels (african, middle_eastern, scandinavian, south_american...) catch countries we did not list, and `other` is the last resort (DECISIONS #26 amendment). The earlier 20-cuisine run in the sections below used the old list.
- **Near-neighbour risk:** labels that cover almost the same food (british and irish, italian and mediterranean) can make the model inconsistent. This is not measured yet; the repeatability run and the hand check will show which pairs to merge.

### The cuisine baseline
`baseline_cuisines` maps Food.com's own keyword and category tags to our cuisines, with no model. With the 90-cuisine list it labels 42,758 of the 212,846 recipes (20.1%; it was 33,945, 15.9%, with 20 cuisines) and returns nothing for the other 79.9%. It cannot say italian, french, american (except via one tag), british, irish or mediterranean for most recipes, because no tag in the data names them. `canadian` (3,103) and `australian` (2,250) rank high and may be where-posted tags, not food styles, so do not trust it on those two. It is the floor the model must beat, and a rough check of the model on the recipes it covers.

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
- Cost was about 1,570 input and 700 output tokens per recipe, roughly twice our estimate. Projected to 212,846 recipes that is about $54 through the Batches API or $108 with direct calls (Haiku 5.5 prices from the model table cached 2026-10-06). From 3 recipes this was a rough figure; the 200-recipe pilot below replaces it. The high output count is thinking tokens (a raw response reported 589 thinking tokens of 910 output tokens).

### 200-recipe pilot (2026-10-28)
The same fixed-seed sample, 200 recipes (3 already saved, 197 new):
- All 200 passed validation on the first try, with no retries. The 197 new calls cost $0.0998.
- Tokens per recipe: 1,595 in and 694 out on average. The JSON answer itself is only about 136 tokens, so roughly 80% of the output is thinking.
- Projected for 212,846 recipes (Haiku 5.5 prices from the model table cached 2026-10-06): **$108 with direct calls (range $104 to $112) and $54 through the Batches API (range $52 to $56)**. The range reflects sampling noise only, not a price change.
- Where the raw quantity lined up with the ingredient list, the model kept it every time (402 rows). Ranges such as `2 -4` became the midpoint.
- The model tagged `american` on 156 of 200 recipes, often as a second cuisine. This may be a filler tag and needs a look.

### Thinking vs no thinking: 20 recipes (2026-10-30)
**Needs review by both of us before we choose how to run the 212,846 recipes.** Open `pilot/thinking_vs_no_thinking.ipynb` (any kernel, only needs pandas; makes no API calls), give a verdict per recipe, and save your `review.csv` as `review_<name>.csv`.

- **Sample:** 20 recipes, stratified by how raw quantities compare with ingredient names: 7 `equal`, 10 `more`, 3 `fewer` (fixed seed 2026, chosen so none were recipes we looked at while writing the prompt). Both modes got the same 20; only the `thinking` setting differs (`effort` low in both).
- **Run it:** `python -m pipelines.foodcom.augment --compare thinking` (or `nothinking`). Files land in `pipelines/foodcom/pilot/`: `stage1_rows.json`, `results_thinking.jsonl`, `results_nothinking.jsonl`, plus the notebook and `review.csv`.

| | Thinking | No thinking |
|---|---|---|
| Valid answers | 20 of 20 | 20 of 20 |
| Needed a retry | 0 | 2 (cause not recorded) |
| Output tokens per recipe | 932 (672 thinking) | 288 |
| Cost per recipe, reweighted to the real 21/75/4% mix | $0.00075 | $0.00044 |
| Full run, direct / Batches (rough, from 20 recipes) | ~$160 / ~$80 | ~$93 / ~$46 |

- Turning thinking off saves about 42%, but we do not know yet whether the answers are as good. The modes give a different amount or unit on 49 of 170 ingredient entries (29%) and a different cuisine set on 9 of 20 recipes. For scale, two identical thinking runs differed on about a third of entries in a 5-recipe test, so a difference alone does not mean one mode is worse.
- The base cost rose from the earlier $108 direct / $54 batch estimate to about $160 / $80 with thinking: the 90-cuisine list and the extras rules add about 677 input tokens per call, and the answers are longer.
- One recipe (Cheesy Scalloped Corn Bake) shows a limit of both modes: the dish is about corn, corn is not in the ingredient list, and the steps say "mix all ingredients", so neither mode can recover it or know the amounts. We have not decided whether to flag such recipes as possibly incomplete.

### Not done yet
- The 30-recipe review file for a hand check of accuracy.
- Which mode to use: the cost side is measured (above); the accuracy side waits on our two reviews of the 20-recipe notebook.
- Answers on messy recipes are noisy: three identical runs on 5 recipes differed in about a third of ingredient entries, and cuisines flipped on 4 of 5 recipes. The hand check has to say which answers are right (DECISIONS #26, CONCEPTS "Request dials").
- The full run through the Batches API, which waits on a budget agreement.
- Backing up `augment_results.jsonl` somewhere other than the laptop.

### Checks
- 56 tests cover the schema, prompt, validator (including extras), cuisine baseline, retry and resume. They use a fake client, so no test calls the API.
