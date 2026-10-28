import json

from pipelines.foodcom.augment import (
    CUISINE_KEYWORDS,
    CUISINES,
    MAX_CUISINES,
    SYSTEM_PROMPT,
    UNITS,
    baseline_cuisines,
    build_output_schema,
    build_user_message,
    validate_result,
)


def make_recipe(**overrides):
    recipe = {
        "name": "Egg Salad",
        "recipe_servings": 6,
        "recipe_yield": "6 sandwiches",
        "ingredient_parts": ["eggs", "mayonnaise", "salt"],
        "quantities_raw": ["8", "1⁄2", ""],
        "quantities_aligned": True,
        "instructions": ["Mix everything.", "Serve."],
    }
    return recipe | overrides


def make_result(**overrides):
    result = {
        "ingredients": [
            {"position": 0, "quantity": 8, "unit": "piece"},
            {"position": 1, "quantity": 0.5, "unit": "cup"},
            {"position": 2, "quantity": None, "unit": "to_taste"},
        ],
        "cuisines": ["american"],
    }
    return result | overrides


def test_vocabularies_have_no_duplicates():
    assert len(set(UNITS)) == len(UNITS)
    assert len(set(CUISINES)) == len(CUISINES)
    assert "to_taste" in UNITS and "other" in CUISINES


def test_schema_enums_match_vocabularies_and_serialize():
    schema = build_output_schema()
    item = schema["properties"]["ingredients"]["items"]["properties"]
    assert item["unit"]["enum"] == UNITS
    assert schema["properties"]["cuisines"]["items"]["enum"] == CUISINES
    json.dumps(schema)  # the API needs plain JSON


def test_system_prompt_lists_every_unit():
    assert all(unit in SYSTEM_PROMPT for unit in UNITS)


def test_user_message_numbers_ingredients_and_states_alignment():
    message = build_user_message(make_recipe())
    assert "0: eggs" in message and "2: salt" in message
    assert "line up one-to-one" in message
    assert "Mix everything." in message


def test_user_message_warns_when_misaligned():
    message = build_user_message(make_recipe(quantities_aligned=False))
    assert "do NOT reliably line up" in message


def test_user_message_handles_missing_servings_and_yield():
    message = build_user_message(make_recipe(recipe_servings=float("nan"), recipe_yield=None))
    assert "Servings: unknown" in message and "Yield: unknown" in message


def test_valid_result_has_no_problems():
    assert validate_result(make_result(), 3) == []


def test_wrong_ingredient_count_is_caught():
    result = make_result()
    result["ingredients"].pop()
    assert any("positions" in p for p in validate_result(result, 3))


def test_out_of_order_positions_are_caught():
    result = make_result()
    result["ingredients"].reverse()
    assert validate_result(result, 3)


def test_null_quantity_rules():
    result = make_result()
    result["ingredients"][0] = {"position": 0, "quantity": None, "unit": "piece"}
    result["ingredients"][2] = {"position": 2, "quantity": 1, "unit": "to_taste"}
    problems = validate_result(result, 3)
    assert len(problems) == 2


def test_nonpositive_quantity_is_caught():
    result = make_result()
    result["ingredients"][1]["quantity"] = 0
    assert validate_result(result, 3)


def test_cuisine_count_and_duplicates():
    assert validate_result(make_result(cuisines=[]), 3)
    too_many = ["american", "italian", "mexican", "greek"]
    assert len(too_many) > MAX_CUISINES
    assert validate_result(make_result(cuisines=too_many), 3)
    assert validate_result(make_result(cuisines=["italian", "italian"]), 3)


def test_keyword_table_only_uses_allowed_cuisines():
    assert set(CUISINE_KEYWORDS.values()) <= set(CUISINES)


def test_baseline_maps_keywords_and_category():
    assert baseline_cuisines(["Weeknight", "Thai", "Easy"], "Asian") == ["thai"]
    assert baseline_cuisines([], "Mexican") == ["mexican"]


def test_baseline_dedupes_and_merges_synonyms():
    # cajun and creole share one cuisine; keyword and category can repeat it
    assert baseline_cuisines(["Cajun", "Creole"], "Cajun") == ["cajun_creole"]


def test_baseline_ignores_coarse_words_and_missing_values():
    assert baseline_cuisines(["European", "Asian"], "European") == []
    assert baseline_cuisines(["Easy"], None) == []


def test_baseline_caps_at_max_cuisines():
    keywords = ["Mexican", "Thai", "Greek", "Korean"]
    assert baseline_cuisines(keywords, None) == ["mexican", "thai", "greek"]
