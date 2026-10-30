"""Stage 2 of the Food.com pipeline: add quantities, units and cuisines with an LLM.

Reads data/interim/recipes_subset.parquet (stage 1 output). For each recipe the
model reads the name, steps and raw ingredient lists and returns one structured
record: a quantity and unit per ingredient, plus the cuisines. The dataset has
no units at all, and its quantities line up with the ingredient list in only
about 22% of recipes, so the text-reading step is unavoidable (DECISIONS #23).

Built one block at a time. This block defines WHAT we ask for and how we check
the answer: the closed vocabularies, the output schema, the prompt, and a
validator. No API call happens here, so it is free to test.
"""

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
import pandas as pd

from pipelines.foodcom.clean import SUBSET_PATH

RESULTS_PATH = Path("data/interim/augment_results.jsonl")
# Committed on purpose: the thinking comparison is small and is reviewed in the PR.
PILOT_DIR = Path("pipelines/foodcom/pilot")

# Cheapest current model; the pilot's accuracy check decides if it is good enough.
MODEL = "claude-haiku-5-5"
# USD per million tokens, from the model table cached 2026-10-06. Treated as an
# estimate: the real bill is whatever the console shows. Batch runs cost half.
PRICE_IN_PER_M = 0.10
PRICE_OUT_PER_M = 0.50
BATCH_DISCOUNT = 0.5
# Haiku 5.5 thinks by default and thinking tokens count against this cap, so it
# is generous; we only pay for tokens actually produced.
MAX_OUTPUT_TOKENS = 4096
EFFORT = "low"  # how hard the model thinks: low, medium, high (experiments in DECISIONS #26)
THINKING_OFF = {"type": "disabled"}  # pass as thinking= to skip thinking tokens entirely

PILOT_SIZE = 200
PILOT_SEED = 42
# The thinking-versus-no-thinking comparison uses 20 recipes, split by how the raw
# quantities relate to the ingredient names. A random 20 would be about 15 "more",
# 4 "equal" and 1 "fewer", too few of the rare kinds to compare modes on.
COMPARE_QUOTAS = {"equal": 7, "more": 10, "fewer": 3}
COMPARE_SEED = 2026  # not 7: that seed drew the rows we inspected while writing the prompt
WORKERS = 8  # concurrent requests; the SDK retries rate-limit errors itself

# Closed vocabularies. The model may only pick from these, so downstream code can
# match on exact strings instead of cleaning "Tbsp.", "tbsp" and "tablespoon".
# Metric and US cooking units, then counted things (a clove, a can) that have no
# metric equivalent. "to_taste" is the unit for salt, pepper and garnishes where
# no amount exists; its quantity is null.
UNITS = [
    "g", "kg", "ml", "l",
    "tsp", "tbsp", "cup", "fl_oz", "oz", "lb",
    "piece", "clove", "slice", "can", "package", "bunch", "pinch", "dash",
    "to_taste",
]  # fmt: skip

# Cuisines a weeknight-dinner app would filter on, 90 in all (DECISIONS #26).
# Multi-label: a recipe can be "mexican" and "american", or a parent and its
# member ("chinese", "cantonese"). "other" is the escape hatch so the model is
# never forced to pick a wrong cuisine just to fill the field. A few umbrella
# labels (african, middle_eastern, scandinavian, mediterranean, caribbean,
# south_american) catch countries we did not list. Near-duplicates were merged
# on purpose (scottish/welsh into british, szechuan/hunan into chinese) because
# the model cannot reliably tell them apart. Grouped by region for reading only.
CUISINES = [
    # Americas
    "american", "tex_mex", "cajun_creole", "hawaiian", "native_american",
    "pennsylvania_dutch", "canadian", "mexican", "caribbean", "cuban",
    "puerto_rican", "jamaican", "haitian", "brazilian", "peruvian", "argentine",
    "chilean", "colombian", "venezuelan", "ecuadorian", "costa_rican",
    "guatemalan", "south_american",
    # Europe
    "italian", "french", "spanish", "portuguese", "greek", "mediterranean",
    "german", "austrian", "swiss", "dutch", "belgian", "british", "irish",
    "scandinavian", "swedish", "norwegian", "danish", "finnish", "icelandic",
    "russian", "polish", "hungarian", "czech", "ukrainian", "romanian",
    "bulgarian", "serbian", "croatian", "georgian",
    # Middle East and Africa
    "middle_eastern", "israeli", "palestinian", "iraqi", "iranian", "egyptian",
    "syrian", "african", "moroccan", "tunisian", "ethiopian", "nigerian",
    "south_african",
    # Asia and Pacific
    "chinese", "cantonese", "taiwanese", "japanese", "korean", "thai",
    "vietnamese", "filipino", "indonesian", "malaysian", "singaporean",
    "cambodian", "burmese", "indian", "pakistani", "bangladeshi", "sri_lankan",
    "nepalese", "tibetan", "mongolian", "afghan", "australian", "new_zealand",
    "polynesian",
    "other",
]  # fmt: skip

# Two is enough: in the 200-recipe pilot 97 recipes used two cuisines and only 3
# used a third. Fewer slots also leaves less room for a filler second tag.
MAX_CUISINES = 2
MAX_EXTRA_INGREDIENTS = 6  # cap on ingredients the model may add beyond the source list
EXTRA_BANNED_NAMES = {"salt", "water"}  # often unlisted on purpose, so never an "extra"

# Rule-based cuisine baseline: Food.com keyword or category (lowercased) -> our
# cuisine. Only words that name a specific cuisine are mapped. "european" and
# "asian" are left out on purpose: they cover tens of thousands of recipes of
# every kind, so mapping them would add noise, not signal; "kosher" is a diet,
# not a cuisine. There is no keyword at all for italian, french, american,
# irish, mediterranean or israeli, so this table cannot produce those; only the
# LLM can.
_SAME_NAME_TAGS = (
    "mexican", "chinese", "cantonese", "indian", "pakistani", "thai", "japanese",
    "korean", "vietnamese", "filipino", "indonesian", "malaysian", "cambodian",
    "nepalese", "mongolian", "australian", "new zealand", "polynesian", "hawaiian",
    "greek", "spanish", "german", "portuguese", "swiss", "dutch", "belgian",
    "austrian", "swedish", "norwegian", "danish", "finnish", "icelandic",
    "scandinavian", "russian", "polish", "hungarian", "czech", "georgian",
    "caribbean", "cuban", "puerto rican", "brazilian", "peruvian", "chilean",
    "colombian", "venezuelan", "costa rican", "guatemalan", "south american",
    "native american", "pennsylvania dutch", "canadian", "african",
    "south african", "moroccan", "ethiopian", "nigerian", "egyptian", "iraqi",
    "palestinian",
)  # fmt: skip
CUISINE_KEYWORDS = {tag: tag.replace(" ", "_") for tag in _SAME_NAME_TAGS} | {
    "tex mex": "tex_mex",
    "southwestern u.s.": "american",
    "szechuan": "chinese", "hunan": "chinese",
    "scottish": "british", "welsh": "british",
    "cajun": "cajun_creole", "creole": "cajun_creole",
    "lebanese": "middle_eastern", "turkish": "middle_eastern",
    "southwest asia (middle east)": "middle_eastern",
    "ecuadorean": "ecuadorian",
}  # fmt: skip


def build_output_schema() -> dict:
    """Return the JSON schema the API will force every answer to match.

    One entry per ingredient slot, keyed by `position` (0-based index into the
    recipe's ingredient list). We key by position instead of echoing the name:
    it is fewer output tokens (output costs 5x input) and cannot drift from the
    source spelling. Items the source list lacks go in `extra_ingredients`
    instead, keyed by name since they have no position. Enums come from UNITS
    and CUISINES above, so the model cannot invent a unit. Length limits (one
    entry per slot, at most MAX_CUISINES cuisines, at most
    MAX_EXTRA_INGREDIENTS extras) are not expressed here; validate_result
    checks them.
    """
    return {
        "type": "object",
        "properties": {
            "ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "position": {"type": "integer"},
                        "quantity": {"type": ["number", "null"]},
                        "unit": {"type": "string", "enum": UNITS},
                    },
                    "required": ["position", "quantity", "unit"],
                    "additionalProperties": False,
                },
            },
            # Items the steps use that the source ingredient list lacks (oil, feta).
            # No position to point at, so these carry a name instead.
            "extra_ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "quantity": {"type": ["number", "null"]},
                        "unit": {"type": "string", "enum": UNITS},
                    },
                    "required": ["name", "quantity", "unit"],
                    "additionalProperties": False,
                },
            },
            "cuisines": {"type": "array", "items": {"type": "string", "enum": CUISINES}},
        },
        "required": ["ingredients", "extra_ingredients", "cuisines"],
        "additionalProperties": False,
    }


# Identical for every recipe, so it sits first in the request where prompt
# caching can reuse it. Keep recipe-specific text out of it.
SYSTEM_PROMPT = f"""You convert one recipe into structured data for a meal-prep app.

For EVERY ingredient position, return the amount the recipe uses as a quantity
(a decimal number) and a unit from this list: {", ".join(UNITS)}.

Rules:
- Return exactly one entry per ingredient position, in order, using the position
  numbers you are given. Never skip, merge or add positions.
- The raw quantity list comes from messy source data. When the user message says
  it lines up with the ingredients, use it. When it says it does not, treat it
  only as a hint and work out the amounts from the ingredient names and the
  instructions (for example "mix first 7 ingredients" tells you nothing about
  amounts, but "2 cups flour" in the steps does).
- Convert fractions to decimals (1/2 -> 0.5). If the source gives a range
  (2-3), use the midpoint.
- Use a counted unit (piece, clove, slice, can, package, bunch) for things
  bought or used as whole items, such as eggs, garlic or canned tomatoes.
- If no amount can be found and a sensible amount cannot be inferred (salt,
  pepper, garnish, "oil for frying"), use unit "to_taste" and quantity null.
  Only "to_taste" may have a null quantity.
- Scale to the whole recipe as written, not per serving.
- The ingredient list can be incomplete. If the instructions clearly use an
  ingredient that is NOT in the list (for example oil, or a cheese), add it to
  extra_ingredients with its name, quantity and unit. Rules for extras:
  * Only add what the instructions actually use. Never invent an ingredient to
    explain a leftover raw quantity; unused raw quantities are simply ignored.
  * Do not add salt or water.
  * Do not repeat an ingredient that is already in the list.
  * At most {MAX_EXTRA_INGREDIENTS} extras. Return an empty array if nothing is missing.
  * Same quantity and unit rules as above, including to_taste with null.
- cuisines: list up to {MAX_CUISINES} cuisines that best describe the dish, most
  fitting first. Pick the most specific one you are confident in. A country or
  region may be paired with its parent (chinese with cantonese), but do not list
  two overlapping labels just to fill the second slot. For a country that is
  not listed, use the closest umbrella label (african, middle_eastern,
  south_american, scandinavian, caribbean) and use "other" only if none fit.
  Do not use "american" as a default when the dish has no clear cuisine.
"""


def build_user_message(recipe: dict) -> str:
    """Format one recipe row as the user message the model reads.

    Inputs: a dict-like row from recipes_subset.parquet with name, recipe_servings,
    recipe_yield, ingredient_parts, quantities_raw, quantities_aligned and
    instructions. Output: plain text. The ingredients are numbered so the model
    can answer by position. The raw quantities are shown as a separate list, and
    the aligned flag tells the model whether it may trust them slot for slot.
    """
    parts = [str(p) for p in recipe["ingredient_parts"]]
    quantities = [str(q) for q in recipe["quantities_raw"]]
    steps = [str(s) for s in recipe["instructions"]]

    servings = recipe.get("recipe_servings")
    servings_text = "unknown" if pd.isna(servings) else str(servings)
    yield_text = recipe.get("recipe_yield")
    yield_text = "unknown" if not isinstance(yield_text, str) or not yield_text else yield_text

    if recipe["quantities_aligned"]:
        alignment = "These line up one-to-one with the ingredients."
    else:
        alignment = "These do NOT reliably line up with the ingredients; treat as hints."

    numbered = "\n".join(f"{i}: {name}" for i, name in enumerate(parts))
    return (
        f"Recipe: {recipe['name']}\n"
        f"Servings: {servings_text}\n"
        f"Yield: {yield_text}\n\n"
        f"Ingredients ({len(parts)}):\n{numbered}\n\n"
        f"Raw quantities (numbers only, no units): {quantities}\n{alignment}\n\n"
        "Instructions:\n" + "\n".join(steps)
    )


def quantity_problems(label: str, quantity, unit) -> list[str]:
    """Check one entry's quantity against its unit; `label` names it in messages.

    Shared by listed ingredients and extras so both follow the same rule: a null
    quantity goes with to_taste and only with to_taste, and amounts are positive.
    """
    problems = []
    if unit == "to_taste" and quantity is not None:
        problems.append(f"{label}: to_taste must have null quantity")
    if unit != "to_taste" and quantity is None:
        problems.append(f"{label}: null quantity needs unit to_taste")
    if quantity is not None and quantity <= 0:
        problems.append(f"{label}: quantity must be positive")
    return problems


def validate_result(result: dict, n_ingredients: int, listed_names=()) -> list[str]:
    """Check a parsed model answer against the rules the schema cannot express.

    Inputs: the answer as a dict, how many ingredient slots the recipe has, and
    the source ingredient names (to catch extras that repeat a listed item).
    Output: a list of problems; empty means the answer is usable. The schema
    guarantees types and enum values, but not "one entry per slot" or "null only
    for to_taste", and a wrong count would silently misalign ingredients with
    amounts. Problems are returned (not raised) so the caller can feed them back
    in a single retry instead of paying for a blind redo.
    """
    problems = []
    entries = result.get("ingredients", [])

    positions = [e.get("position") for e in entries]
    if positions != list(range(n_ingredients)):
        problems.append(
            f"expected positions 0..{n_ingredients - 1} once each, in order; got {positions}"
        )

    for e in entries:
        problems += quantity_problems(f"position {e.get('position')}", e.get("quantity"), e.get("unit"))

    # An extra repeats a listed ingredient if it matches exactly, or if it is the
    # listed name followed by a descriptor after a comma, bracket or dash
    # ("cheddar cheese, shredded (for topping)" vs "cheddar cheese"). A different
    # food that merely contains the word ("peanut butter" vs "butter") or is
    # shorter ("onion" vs "spring onion") is a new ingredient and is kept.
    extras = result.get("extra_ingredients", [])
    if len(extras) > MAX_EXTRA_INGREDIENTS:
        problems.append(f"at most {MAX_EXTRA_INGREDIENTS} extra_ingredients; got {len(extras)}")
    taken = {str(name).strip().lower() for name in listed_names}
    descriptor = [
        re.compile(rf"{re.escape(str(n).strip().lower())}\s*[,(\-\u2013:;/]")
        for n in listed_names
        if str(n).strip()
    ]
    for e in extras:
        name = str(e.get("name", "")).strip().lower()
        if not name:
            problems.append("extra_ingredients: name must not be empty")
        elif name in EXTRA_BANNED_NAMES:
            problems.append(f"extra '{name}': do not add salt or water")
        elif name in taken or any(rx.match(name) for rx in descriptor):
            problems.append(f"extra '{name}': already in the ingredient list or listed twice")
        taken.add(name)
        problems += quantity_problems(f"extra '{name}'", e.get("quantity"), e.get("unit"))

    cuisines = result.get("cuisines", [])
    if not 1 <= len(cuisines) <= MAX_CUISINES:
        problems.append(f"expected 1 to {MAX_CUISINES} cuisines; got {len(cuisines)}")
    if len(set(cuisines)) != len(cuisines):
        problems.append("duplicate cuisines")

    return problems


def baseline_cuisines(keywords, category) -> list[str]:
    """Guess a recipe's cuisines from its Food.com keywords and category, no LLM.

    Inputs: the recipe's keyword list and its single recipe_category value.
    Output: up to MAX_CUISINES cuisines in CUISINES, in first-seen order, or an
    empty list when no keyword names a cuisine (about 3 in 4 recipes). Free and
    deterministic, so it serves two jobs: a floor the LLM must beat, and a set of
    rough labels to sanity-check the LLM against. The labels are biased, though:
    they exist only for recipes whose uploader tagged a cuisine.
    """
    found = []
    for term in [*keywords, category]:
        cuisine = CUISINE_KEYWORDS.get(str(term).strip().lower())
        if cuisine and cuisine not in found:
            found.append(cuisine)
    return found[:MAX_CUISINES]


def build_request_params(
    recipe: dict,
    problems: list[str] | None = None,
    *,
    effort: str = EFFORT,
    thinking: dict | None = None,
    max_tokens: int = MAX_OUTPUT_TOKENS,
) -> dict:
    """Build the keyword arguments for one Messages API call about one recipe.

    Inputs: a recipe row as a dict, optionally the problems found in a previous
    answer, and the three dials we can turn: `effort`, `thinking` (None keeps the
    model's default; THINKING_OFF disables it) and `max_tokens`. Defaults match
    the production setting, so only experiments pass them. Output: a dict ready
    for `client.messages.create(**params)`.
    One builder feeds both the pilot (direct calls) and the later Batches run, so
    the two cannot drift apart. On a retry the problems are appended to the same
    single user message instead of replaying the model's earlier answer as a
    second turn: it is simpler and avoids resending its thinking blocks.
    """
    text = build_user_message(recipe)
    if problems:
        text += "\n\nYour previous answer was rejected for these reasons. Fix them:\n"
        text += "\n".join(f"- {p}" for p in problems)
    params = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": text}],
        # Low effort: this is extraction, not hard reasoning, and thinking is billed
        # as output. The format key is what forces the answer into our schema.
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": build_output_schema()},
        },
    }
    if thinking is not None:
        params["thinking"] = thinking
    return params


def parse_answer(message) -> dict:
    """Pull the JSON answer out of an API response.

    Raises ValueError (JSONDecodeError is one) if the model stopped early, for
    example on the token cap, or returned no text. The schema guarantees valid
    JSON only for a finished answer, so a cut-off one must be treated as failed.
    """
    if message.stop_reason != "end_turn":
        raise ValueError(f"model stopped early: {message.stop_reason}")
    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise ValueError("response had no text block")
    return json.loads(text)


def estimate_cost(input_tokens: int, output_tokens: int, batch: bool = False) -> float:
    """Return the estimated USD cost of the given token counts at the listed prices."""
    cost = (input_tokens * PRICE_IN_PER_M + output_tokens * PRICE_OUT_PER_M) / 1_000_000
    return cost * BATCH_DISCOUNT if batch else cost


def augment_recipe(client, recipe: dict, **request_options) -> dict:
    """Ask the model about one recipe, validate, and retry once if it fails.

    Inputs: an API client, a recipe dict, and optional request dials passed
    straight to `build_request_params` (effort, thinking, max_tokens). Output: one result record (the line we
    store): source_ref (Food.com's id, the key results are matched on), recipe_key
    (our position number, kept for reading only), status "ok" or "failed", the
    answer, any remaining problems,
    attempts, and token counts summed over both attempts so cost is never
    under-reported. Two attempts is the cap: a second failure usually means a
    recipe the model cannot handle, and a third paid try rarely fixes it.
    """
    n = len(recipe["ingredient_parts"])
    problems, answer = None, None
    tokens_in = tokens_out = tokens_thinking = 0
    for attempt in (1, 2):
        params = build_request_params(recipe, problems, **request_options)
        message = client.messages.create(**params)
        tokens_in += message.usage.input_tokens
        tokens_out += message.usage.output_tokens
        # Thinking tokens are already inside output_tokens; the detail field may be
        # absent (older responses, test doubles), so read it defensively.
        details = getattr(message.usage, "output_tokens_details", None)
        tokens_thinking += getattr(details, "thinking_tokens", 0) or 0
        try:
            answer = parse_answer(message)
            problems = validate_result(answer, n, recipe["ingredient_parts"])
        except ValueError as error:
            answer, problems = None, [str(error)]
        if not problems:
            break
    return {
        # source_ref identifies the recipe across reruns. recipe_key is a position
        # number from clean.py and shifts if stage 1 drops or adds a recipe, so a
        # saved result must never be matched on it.
        "source_ref": int(recipe["source_ref"]),
        "recipe_key": int(recipe["recipe_key"]),
        "status": "failed" if problems else "ok",
        "attempts": attempt,
        "result": answer,
        "problems": problems or [],
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "thinking_tokens": tokens_thinking,
        "mode": "nothinking" if request_options.get("thinking") == THINKING_OFF else "thinking",
        "model": MODEL,
    }


def load_done_keys(path: Path) -> set[str]:
    """Return the source_refs already stored with status "ok" (empty if no file).

    This is what makes a rerun safe: those recipes were already paid for, so they
    are skipped. Keyed on Food.com's source_ref, which does not change when stage 1
    is edited, unlike the position-based recipe_key. Failed records are not counted as done, so a rerun retries them.
    """
    if not path.exists():
        return set()
    with path.open() as f:
        records = (json.loads(line) for line in f if line.strip())
        return {r["source_ref"] for r in records if r["status"] == "ok"}


def append_record(path: Path, record: dict) -> None:
    """Append one record as a JSON line and flush it to disk immediately.

    Append-only with a flush per record means a crash loses at most the call in
    flight, never earlier paid results. This file is the only copy of paid output
    (DECISIONS #24), so back it up somewhere other than the laptop.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()


def print_report(records: list[dict], total_recipes: int) -> None:
    """Print how the run went and what the full run would cost at this rate.

    The projection scales the measured per-recipe tokens to the whole subset, in
    both direct and Batches pricing, so the decision to go bigger rests on a
    measurement from our own recipes and not on a guess.
    """
    n = len(records)
    ok = sum(r["status"] == "ok" for r in records)
    retried = sum(r["attempts"] > 1 for r in records)
    tokens_in = sum(r["input_tokens"] for r in records)
    tokens_out = sum(r["output_tokens"] for r in records)
    print(f"\nrecipes: {n}  ok: {ok}  failed: {n - ok}  needed a retry: {retried}")
    print(f"tokens per recipe: {tokens_in / n:.0f} in, {tokens_out / n:.0f} out")
    print(f"cost of this run: ${estimate_cost(tokens_in, tokens_out):.4f}")
    scale = total_recipes / n
    full_in, full_out = tokens_in * scale, tokens_out * scale
    print(f"projected full run ({total_recipes:,} recipes):")
    print(f"  direct calls: ${estimate_cost(full_in, full_out):,.2f}")
    print(f"  Batches API : ${estimate_cost(full_in, full_out, batch=True):,.2f}")


def quantity_group(n_ingredients: int, n_quantities: int) -> str:
    """Name how a recipe's raw quantities compare with its ingredient names.

    Returns "equal", "more" (extra quantities with no name) or "fewer". This is the
    split behind the stratified sample, because the model's job is easiest when
    the lists line up and hardest when they do not.
    """
    if n_quantities == n_ingredients:
        return "equal"
    return "more" if n_quantities > n_ingredients else "fewer"


def stratified_sample(df: pd.DataFrame, quotas: dict[str, int], seed: int) -> pd.DataFrame:
    """Pick a fixed number of recipes from each quantity group, reproducibly.

    Inputs: the recipes, how many to take per group (see COMPARE_QUOTAS), and a
    seed. Output: the chosen rows, ordered group by group. The same seed gives the
    same rows, which is what lets both modes of the comparison see identical
    recipes. Raises ValueError if a group has fewer recipes than its quota, so a
    short sample never passes silently.
    """
    groups = pd.Series(
        [
            quantity_group(len(parts), len(quantities))
            for parts, quantities in zip(df["ingredient_parts"], df["quantities_raw"])
        ],
        index=df.index,
    )
    chosen = []
    for group, quota in quotas.items():
        members = df[groups == group]
        if len(members) < quota:
            raise ValueError(f"group '{group}' has {len(members)} recipes, need {quota}")
        chosen.append(members.sample(n=quota, random_state=seed))
    return pd.concat(chosen)


def run_recipes(
    client, recipes: list[dict], results_path: Path, workers: int, **request_options
) -> list[dict]:
    """Run the model on these recipes, skipping any already stored in results_path.

    Inputs: an API client, the recipe dicts, the file to append to, a worker count,
    and request dials passed to `augment_recipe` (effort, thinking, max_tokens).
    Output: the new records. The finished keys are removed after the list is
    chosen, so the same recipes always mean the same work and a rerun only pays for
    the gap. Workers call the API concurrently, but only this thread writes the
    file, so lines cannot interleave. A failed API call is reported and left
    unwritten, so the next run retries it.
    """
    done = load_done_keys(results_path)
    todo = [r for r in recipes if int(r["source_ref"]) not in done]
    print(f"recipes {len(recipes)}, already done {len(recipes) - len(todo)}, to run {len(todo)}")

    records = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(augment_recipe, client, r, **request_options): r for r in todo}
        for future in as_completed(futures):
            try:
                record = future.result()
            except anthropic.APIError as error:
                print(f"API error on source_ref {futures[future]['source_ref']}: {error}")
                continue
            append_record(results_path, record)
            records.append(record)
            if len(records) % 25 == 0:
                print(f"  {len(records)}/{len(todo)} done")
    return records


def run_pilot(client, df: pd.DataFrame, n: int, seed: int, workers: int) -> list[dict]:
    """Run the model on a fixed random sample of n recipes (the 200-recipe pilot).

    The sample is drawn with a fixed seed, so the same seed means the same recipes.
    """
    sample = df.sample(n=min(n, len(df)), random_state=seed)
    recipes = [row.to_dict() for _, row in sample.iterrows()]
    return run_recipes(client, recipes, RESULTS_PATH, workers)


def stage1_snapshot(row: dict) -> dict:
    """Turn one stage 1 row into plain JSON types, keeping only what a reviewer needs.

    Inputs: a recipe row (lists may be numpy arrays, numbers may be missing).
    Output: a dict of Python lists, strings and numbers, with missing values as
    None. This is what gets committed next to the pilot results, so the notebook can
    show the source recipe without the 212,846-row parquet file.
    """

    def plain(value):
        if isinstance(value, (list, tuple)) or hasattr(value, "tolist"):
            return [str(item) for item in list(value)]
        return None if pd.isna(value) else value

    keys = [
        "recipe_key", "source_ref", "name", "recipe_category", "keywords",
        "ingredient_parts", "quantities_raw", "quantities_aligned",
        "recipe_servings", "recipe_yield", "instructions",
    ]  # fmt: skip
    snapshot = {key: plain(row[key]) for key in keys}
    snapshot["quantities_aligned"] = bool(row["quantities_aligned"])
    snapshot["group"] = quantity_group(len(row["ingredient_parts"]), len(row["quantities_raw"]))
    return snapshot


def run_compare(client, df: pd.DataFrame, mode: str, workers: int) -> list[dict]:
    """Run the 20-recipe stratified sample in one mode: "thinking" or "nothinking".

    Both modes draw the same recipes (fixed seed, fixed quotas) and differ only in
    the `thinking` dial, so a gap in cost or answers comes from thinking and not
    from the recipes. Each mode has its own results file because resume is keyed
    by source_ref alone and would otherwise mix them. The stage 1 rows are saved
    once for the review notebook.
    """
    sample = stratified_sample(df, COMPARE_QUOTAS, COMPARE_SEED)
    recipes = [row.to_dict() for _, row in sample.iterrows()]
    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    (PILOT_DIR / "stage1_rows.json").write_text(
        json.dumps([stage1_snapshot(r) for r in recipes], indent=2, ensure_ascii=False) + "\n"
    )
    options = {"thinking": THINKING_OFF} if mode == "nothinking" else {}
    return run_recipes(client, recipes, PILOT_DIR / f"results_{mode}.jsonl", workers, **options)


def main() -> None:
    """Command line entry point. Only the pilots exist so far (no full run yet)."""
    parser = argparse.ArgumentParser(description="Stage 2: add units and cuisines with an LLM.")
    parser.add_argument("--pilot", action="store_true", help="run the fixed-seed pilot sample")
    parser.add_argument("--limit", type=int, default=PILOT_SIZE, help="recipes to run (default 200)")
    parser.add_argument(
        "--compare",
        choices=["thinking", "nothinking"],
        help="run the stratified 20-recipe comparison sample in one mode",
    )
    args = parser.parse_args()
    if not args.pilot and not args.compare:
        parser.error("only --pilot and --compare are built so far; the full run is not")

    df = pd.read_parquet(SUBSET_PATH)
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    if args.compare:
        records = run_compare(client, df, args.compare, WORKERS)
    else:
        records = run_pilot(client, df, args.limit, PILOT_SEED, WORKERS)
    if records:
        print_report(records, total_recipes=len(df))


if __name__ == "__main__":
    main()
