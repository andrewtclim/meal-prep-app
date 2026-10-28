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

import pandas as pd

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

# Cuisines a weeknight-dinner app would filter on. Multi-label: a recipe can be
# both "mexican" and "american". "other" is the escape hatch so the model is never
# forced to pick a wrong cuisine just to fill the field.
CUISINES = [
    "american", "italian", "mexican", "chinese", "indian", "thai", "japanese",
    "korean", "vietnamese", "greek", "mediterranean", "middle_eastern",
    "french", "spanish", "german", "british_irish", "caribbean", "african",
    "cajun_creole", "other",
]  # fmt: skip

MAX_CUISINES = 3

# Rule-based cuisine baseline: Food.com keyword or category (lowercased) -> our
# cuisine. Only words that name a specific cuisine are mapped. "european" and
# "asian" are left out on purpose: they cover tens of thousands of recipes of
# every kind, so mapping them would add noise, not signal. There is no keyword
# at all for italian, french, american, irish or mediterranean, so this table
# cannot produce those; only the LLM can.
CUISINE_KEYWORDS = {
    "mexican": "mexican", "tex mex": "mexican",
    "southwestern u.s.": "american",
    "chinese": "chinese",
    "indian": "indian", "pakistani": "indian",
    "thai": "thai",
    "japanese": "japanese",
    "korean": "korean",
    "vietnamese": "vietnamese",
    "filipino": "other", "indonesian": "other", "south american": "other",
    "greek": "greek",
    "spanish": "spanish",
    "german": "german",
    "scottish": "british_irish",
    "caribbean": "caribbean",
    "cajun": "cajun_creole", "creole": "cajun_creole",
    "african": "african", "south african": "african",
    "moroccan": "african", "ethiopian": "african",
    "lebanese": "middle_eastern", "turkish": "middle_eastern",
    "southwest asia (middle east)": "middle_eastern",
}  # fmt: skip


def build_output_schema() -> dict:
    """Return the JSON schema the API will force every answer to match.

    One entry per ingredient slot, keyed by `position` (0-based index into the
    recipe's ingredient list). We key by position instead of echoing the name:
    it is fewer output tokens (output costs 5x input) and cannot drift from the
    source spelling. Enums come from UNITS and CUISINES above, so the model
    cannot invent a unit. Length limits (one entry per slot, at most
    MAX_CUISINES cuisines) are not expressed here; validate_result checks them.
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
            "cuisines": {"type": "array", "items": {"type": "string", "enum": CUISINES}},
        },
        "required": ["ingredients", "cuisines"],
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
- cuisines: list up to {MAX_CUISINES} cuisines that best describe the dish, most
  fitting first. Use "other" only if none fit.
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


def validate_result(result: dict, n_ingredients: int) -> list[str]:
    """Check a parsed model answer against the rules the schema cannot express.

    Inputs: the answer as a dict, and how many ingredient slots the recipe has.
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
        quantity, unit = e.get("quantity"), e.get("unit")
        if unit == "to_taste" and quantity is not None:
            problems.append(f"position {e.get('position')}: to_taste must have null quantity")
        if unit != "to_taste" and quantity is None:
            problems.append(f"position {e.get('position')}: null quantity needs unit to_taste")
        if quantity is not None and quantity <= 0:
            problems.append(f"position {e.get('position')}: quantity must be positive")

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
