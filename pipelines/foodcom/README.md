# Food.com pipeline

Turns the raw Food.com recipes file into a clean set we can load. Three stages. This file covers stages 1 and 2.

| Stage | Script | Status |
|---|---|---|
| 1. Clean and filter | `clean.py` | Done |
| 2. Add units, cuisines and prep tasks with an LLM | `augment.py` | Code done through schema version 4 (prep tasks, in review), pilots run, thinking chosen; the full run waits for the budget talk and the prep-task review |
| 3. Load into Postgres with dbt | `load.py` and `dbt/` | In review (PRs #20, #21, #22) |

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

## Stage 2: add units, cuisines and prep tasks with an LLM

The dataset has no ingredient units, and its quantities line up with the ingredient list in only about 22% of recipes. So for each recipe a Claude model reads the name, steps and raw lists and returns an amount and a unit for every ingredient, plus the cuisines (DECISIONS #23, #26).

Run it (this calls the paid API; it loads the key from `.env`):
`uv run --env-file .env --group pipelines python -m pipelines.foodcom.augment --pilot --limit 3`
Without `--limit` it runs the 200-recipe pilot. Reads `data/interim/recipes_subset.parquet`, appends to `data/interim/augment_results.jsonl`. Rerunning skips recipes already saved at the current `SCHEMA_VERSION` (matched on Food.com's `source_ref`); records from an older version are redone, so stale pilot results are never silently kept. `--compare thinking` or `--compare nothinking` runs the stratified 20-recipe comparison below. Only these two exist; the full run is not built.

### How a recipe is processed
1. `build_user_message` turns the recipe row into numbered text.
2. `build_request_params` adds the rules (`SYSTEM_PROMPT`) and the answer shape (`build_output_schema`).
3. The model answers in that shape (schema version 4): `{ingredients: [{position, quantity, unit, state}], extra_ingredients: [{name, quantity, unit, state}], cuisine, prep_tasks: [{ingredient, technique, cut_size, with, make_ahead, source_step, stated}]}`.
4. `validate_result` checks what the schema cannot (one entry per ingredient, null quantity only for "to taste", and for extras: at most 6, no salt or water, no repeat of a listed name). For prep tasks, `prep_task_problems` checks that positions exist (extras count), a marinade has `with` and nothing else does, a size only goes on a cut, `source_step` is a real step, no repeated (ingredient, technique), implied tasks use only mince, dice or chop with no size, and at most 12 tasks.
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
- **Units (18):** g, kg, ml, l, tsp, tbsp, cup, fl_oz, oz, lb, piece, clove, slice, can, bunch, pinch, dash, to_taste. `package` was removed (its size varies by product, so "1 package" and "1 lb" of the same noodles disagreed); the prompt says to give a weight for packaged goods. The other loose units (can, bunch, pinch, dash, piece) are still under review.
- **Cuisines (90, exactly 1 per recipe):** Food.com's own cuisine tags plus the ones it lacks (italian, french, american, british, irish, mediterranean...), grouped by region in `CUISINES`. Merged on purpose: scottish and welsh into british, szechuan and hunan into chinese, lebanese and turkish into middle_eastern. The model names one cuisine; the parent comes from a small table in code (`CUISINE_PARENT`, `cuisine_path`: cantonese gives chinese), so it costs no tokens. Umbrella labels (african, middle_eastern, scandinavian, south_american...) catch countries we did not list, and `other` is the last resort (DECISIONS #26 amendment). The earlier 20-cuisine run in the sections below used the old list.
- **Prep techniques (12):** dice, mince, chop, slice, julienne, grate, shred, peel, trim, marinate, rub, brine. **Cut sizes (6, or null):** fine, small, medium, large, thin, thick. **State:** raw or cooked in the finished dish. Closed for the same reason as units: the graph matches tasks across recipes on exact strings (DECISIONS #30).
- **Near-neighbour risk:** labels that cover almost the same food (british and irish, italian and mediterranean) can make the model inconsistent. This is not measured yet; the repeatability run and the hand check will show which pairs to merge.

### The cuisine baseline
`baseline_cuisine` maps Food.com's own keyword and category tags to our cuisines, with no model. With the 90-cuisine list it labels 42,758 of the 212,846 recipes (20.1%; it was 33,945, 15.9%, with 20 cuisines) and returns nothing for the other 79.9%. It cannot say italian, french, american (except via one tag), british, irish or mediterranean for most recipes, because no tag in the data names them. `canadian` (3,103) and `australian` (2,250) rank high and may be where-posted tags, not food styles, so do not trust it on those two. It is the floor the model must beat, and a rough check of the model on the recipes it covers.

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
**Decision (2026-11-02): use thinking.** Paul picked thinking from his notebook review (no-thinking was wrong by a large amount on Salmon Basil Rolls, Lemon Cucumbers and Fava Beans), and Andrew agrees. The two files this comparison was judged on are version-2 results, kept as the evidence behind that decision: `results_thinking_v2.jsonl` and `results_nothinking.jsonl`. (Running `--compare` under a newer version appends to the file for that mode, so the thinking file was renamed first; see the version-3 run below and the file list under the version-4 pilot.) Open `pilot/thinking_vs_no_thinking.ipynb` (any kernel, only needs pandas; makes no API calls), give a verdict per recipe, and save your `review.csv` as `review_<name>.csv`.

- **Sample:** 20 recipes, stratified by how raw quantities compare with ingredient names: 7 `equal`, 10 `more`, 3 `fewer` (fixed seed 2026, chosen so none were recipes we looked at while writing the prompt). Both modes got the same 20; only the `thinking` setting differs (`effort` low in both).
- **Run it:** `python -m pipelines.foodcom.augment --compare thinking` (or `nothinking`). Files land in `pipelines/foodcom/pilot/`: `stage1_rows.json`, `results_thinking.jsonl` (now the version-4 run; the version-3 run is kept as `results_thinking_v3.jsonl`) and `results_thinking_v2.jsonl` (the v2 evidence), `results_nothinking.jsonl` (v2), plus the notebook and `review.csv`.

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

### Version-3 run of the same 20 recipes (2026-11-05)
After the PR #18 review changes (one cuisine, `package` removed, `schema_version` 3) we reran the same 20 recipes in thinking mode so the stage 3 loader and dbt models have version-3 data to test against: `uv run --env-file .env --group pipelines python -m pipelines.foodcom.augment --compare thinking`, writing a fresh `pilot/results_thinking.jsonl` (the v2 thinking file was renamed first). That file is now `results_thinking_v3.jsonl`.
- 20 of 20 valid on the first try, no retries. Cost $0.0146 (about $0.00073 per recipe, close to version 2). Every record has `schema_version` 3 and one `cuisine` string.
- Paul's `load.py --dry-run` (PR #20) reads all 20 records and builds 20 rows.
- Both runs are thinking mode (same model, same 20 recipes); only the rules changed between them. 34 of 170 ingredient entries differ in unit or quantity (20%). Two identical thinking runs differed on about a third of entries in an earlier 5-recipe test, so 20% is within run-to-run noise and shows no clear shift from the new rules.
- The first cuisine changed on 4 of 20 recipes and the new answers are reasonable, not blocking. Two are worth a mention: Cherokee Casserole (keyword `Native American`) became `american` although `native_american` is available and more specific, and Lemon Cucumbers (no cuisine signal) became `american` although the prompt says not to default to it. It is 20 recipes, one run each, so it may be noise. A prompt change would mean a new `SCHEMA_VERSION`, so it is only noted for the team meeting.

### Prep tasks (schema version 4, 2026-11-15)
Each recipe's answer now lists the prep the steps need, so the app can prep a shared ingredient once for several recipes (DECISIONS #6, #30). A toy recipe, Soy-Ginger Chicken Bowls (8 ingredients and 1 extra, sesame oil, at position 8):

| ingredient | technique | cut_size | with | make_ahead | source_step | stated |
|---|---|---|---|---|---|---|
| yellow onion | dice | small ("finely") | none | true | 1 | true |
| garlic | mince | null | none | true | 2 | true |
| chicken thighs | marinate | null | ginger, garlic, sesame oil, soy sauce | true | 2 | true |
| roma tomatoes | dice | null | none | false | 4 | true |

- **Not tasks:** searing (cooking), slicing the cooked chicken, and scallions that no step cuts.
- **`ingredient` and `with` are positions.** Listed ingredients are 0..n-1 and extras are numbered after them, so a marinade can use an extra.
- **`stated`:** true when a step names the technique, false when a step only uses the ingredient in a way that needs it cut ("saute onion and garlic"). Implied tasks use a default (garlic mince, onion and firm vegetables dice, herbs chop), never carry a size, and are never given to meat, fish, eggs, dairy, canned food, pasta, rice or liquids.
- **`source_step`** is the step that states the task, evidence for review and not a prep order. `make_ahead` is the model's judgment.
- **Later (not built):** dbt builds the Neo4j `form` as the `cut_size`, or the sorted input names joined with ` + `, or an empty string. `load.py` accepts only version 3, so it skips version-4 records until a follow-up.

**Pilot (the same 20 recipes, thinking mode):**

| | v3 | v4 strict (stated only) | v4 (stated + implied) |
|---|---|---|---|
| Valid on first try / retries | 20 / 0 | 20 / 0 | 20 / 0 |
| Tokens in / out per recipe | 2,810 / 894 | 4,078 / 1,183 | 4,460 / 1,506 |
| Cost for the 20 | $0.0146 | $0.0200 | $0.0240 |
| Full run, direct / Batches | ~$155 / ~$77 | ~$213 / ~$106 | ~$255 / ~$128 |
| Recipes with a task / tasks | n/a | 4 / 5 | 18 / 50 (9 stated, 41 implied) |

- **Why two runs:** with stated tasks only, 16 of 20 recipes came back empty. Food.com steps are terse and rarely say to chop an onion. Mostly that is the data, but not all of it: the model skipped "sprinkle grated cheese" in Better Tater Tot Casserole even though that is a stated task. Allowing implied tasks gave 7 groups shared by 2 or more recipes (onion dice in 8 of 20), but 82% of tasks are judgments, so the hand review decides how far to trust them.
- **`garlic` and `garlic cloves` do not match** (4 and 3 recipes), because ingredient names are not normalized yet.
- **Review it:** `cd pipelines/foodcom/pilot`, open `prep_tasks_v4.ipynb` in any kernel with pandas (no API key, no API calls), read the recipe cards, fill the verdict cells, set `REVIEWER` and run the last cell to save `review_prep_<name>.csv`.
- **Files:** `results_thinking.jsonl` (version 4), `results_thinking_v4_strict.jsonl` (the stated-only run), `results_thinking_v3.jsonl` (version 3), `results_thinking_v2.jsonl` and `results_nothinking.jsonl` (the version-2 comparison).
- **Open:** pure mixing steps ("mix into pico") are left out, and `cut` is not a technique (DECISIONS #30).

### Not done yet
- The 30-recipe review file for a hand check of accuracy, and the hand review of the prep tasks (`prep_tasks_v4.ipynb`).
- The mode to use is decided (thinking, 2026-11-02). Still open (low priority): whether the two small cuisine differences above are worth a prompt change.
- Answers on messy recipes are noisy: three identical runs on 5 recipes differed in about a third of ingredient entries, and cuisines flipped on 4 of 5 recipes. The hand check has to say which answers are right (DECISIONS #26, CONCEPTS "Request dials").
- The full run through the Batches API, which waits on a budget agreement.
- Backing up `augment_results.jsonl` somewhere other than the laptop.

### Checks
- 88 tests cover the schema, prompt, validator (including extras and prep tasks), cuisine baseline, retry and resume. They use a fake client, so no test calls the API.
