import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import pipelines.foodcom.augment as augment_module
from pipelines.foodcom.augment import (
    CUISINE_KEYWORDS,
    CUISINES,
    MAX_CUISINES,
    MAX_EXTRA_INGREDIENTS,
    MODEL,
    SYSTEM_PROMPT,
    THINKING_OFF,
    UNITS,
    append_record,
    augment_recipe,
    baseline_cuisines,
    build_output_schema,
    build_request_params,
    build_user_message,
    estimate_cost,
    load_done_keys,
    parse_answer,
    quantity_group,
    run_compare,
    run_recipes,
    stage1_snapshot,
    stratified_sample,
    validate_result,
)


def make_recipe(**overrides):
    recipe = {
        "source_ref": 9001,
        "recipe_key": 1,
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
        "extra_ingredients": [],
        "cuisines": ["american"],
    }
    return result | overrides


def make_extra(**overrides):
    extra = {"name": "olive oil", "quantity": 2, "unit": "tbsp"}
    return extra | overrides


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


LISTED = ["eggs", "mayonnaise", "salt"]  # the names behind make_recipe()


def test_schema_requires_extra_ingredients():
    schema = build_output_schema()
    assert "extra_ingredients" in schema["required"]
    item = schema["properties"]["extra_ingredients"]["items"]["properties"]
    assert item["unit"]["enum"] == UNITS and set(item) == {"name", "quantity", "unit"}


def test_system_prompt_states_the_extra_ingredient_rules():
    assert str(MAX_EXTRA_INGREDIENTS) in SYSTEM_PROMPT and "extra_ingredients" in SYSTEM_PROMPT


def test_valid_extras_have_no_problems():
    extras = [make_extra(), make_extra(name="cooking spray", quantity=None, unit="to_taste")]
    assert validate_result(make_result(extra_ingredients=extras), 3, LISTED) == []


def test_empty_extras_are_fine():
    assert validate_result(make_result(extra_ingredients=[]), 3, LISTED) == []


def test_too_many_extras_is_caught():
    extras = [make_extra(name=f"item {i}") for i in range(MAX_EXTRA_INGREDIENTS + 1)]
    assert any("at most" in p for p in validate_result(make_result(extra_ingredients=extras), 3, LISTED))


def test_extra_repeating_a_listed_name_is_caught_ignoring_case():
    result = make_result(extra_ingredients=[make_extra(name="Eggs")])
    assert any("already" in p for p in validate_result(result, 3, LISTED))


def test_extra_that_contains_a_listed_name_is_caught():
    # the corn bake case: "cheddar cheese, shredded (for topping)" next to "cheddar cheese"
    result = make_result(extra_ingredients=[make_extra(name="Eggs, beaten (for brushing)")])
    assert any("already" in p for p in validate_result(result, 3, LISTED))


def test_different_foods_that_share_a_word_are_not_flagged():
    # a new ingredient must be kept even if its name overlaps a listed one
    cases = [("onion", "spring onion"), ("buttermilk", "butter"), ("peanut butter", "butter")]
    for extra, listed in cases:
        result = make_result(extra_ingredients=[make_extra(name=extra)])
        assert validate_result(result, 3, [listed, "x", "y"]) == [], (extra, listed)


def test_listed_name_plus_a_descriptor_is_flagged():
    for extra in ["butter, melted", "butter (for greasing)", "butter - softened"]:
        result = make_result(extra_ingredients=[make_extra(name=extra)])
        assert any("already" in p for p in validate_result(result, 3, ["butter", "x", "y"])), extra


def test_two_identical_extras_are_caught():
    result = make_result(extra_ingredients=[make_extra(), make_extra()])
    assert any("twice" in p for p in validate_result(result, 3, LISTED))


def test_salt_and_water_are_not_allowed_as_extras():
    for name in ("salt", "Water"):
        result = make_result(extra_ingredients=[make_extra(name=name)])
        assert any("salt or water" in p for p in validate_result(result, 3, []))


def test_extra_follows_the_same_quantity_rules():
    bad = [make_extra(quantity=None), make_extra(name="feta", quantity=1, unit="to_taste")]
    assert len(validate_result(make_result(extra_ingredients=bad), 3, LISTED)) == 2


def test_extra_needs_a_name():
    result = make_result(extra_ingredients=[make_extra(name="  ")])
    assert any("name" in p for p in validate_result(result, 3, LISTED))


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
    assert baseline_cuisines(keywords, None) == ["mexican", "thai"]


def test_baseline_maps_merged_and_renamed_tags():
    # tags we deliberately fold into a broader label, or spell differently
    assert baseline_cuisines(["Scottish"], None) == ["british"]
    assert baseline_cuisines(["Szechuan"], "Hunan") == ["chinese"]
    assert baseline_cuisines(["Tex Mex"], None) == ["tex_mex"]
    assert baseline_cuisines(["Ecuadorean"], None) == ["ecuadorian"]


def test_baseline_keeps_same_name_tags_with_underscores():
    assert baseline_cuisines(["Puerto Rican"], None) == ["puerto_rican"]
    assert baseline_cuisines([], "South African") == ["south_african"]


def test_cuisine_list_is_wide_and_has_the_cuisines_food_com_lacks():
    assert 85 <= len(CUISINES) <= 100
    assert {"italian", "french", "american", "british", "irish", "filipino"} <= set(CUISINES)


# --- Block 3: request, retry, resume (no network: a fake client stands in) ---


class FakeClient:
    """Stands in for anthropic.Anthropic; replays canned answers and records requests."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    def create(self, **params):
        self.requests.append(params)
        reply = self.replies.pop(0)
        if isinstance(reply, SimpleNamespace):
            return reply
        return fake_message(json.dumps(reply))


def fake_message(text, stop_reason="end_turn", tokens_in=100, tokens_out=50):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
    )


def test_request_params_carry_schema_effort_and_system_prompt():
    params = build_request_params(make_recipe())
    assert params["model"] == MODEL and params["system"] == SYSTEM_PROMPT
    assert params["output_config"]["effort"] == "low"
    assert params["output_config"]["format"]["schema"] == build_output_schema()


def test_request_params_default_dials_match_production():
    params = build_request_params(make_recipe())
    assert params["max_tokens"] == 4096 and "thinking" not in params


def test_request_params_accept_dials_for_experiments():
    params = build_request_params(
        make_recipe(), effort="high", thinking=THINKING_OFF, max_tokens=300
    )
    assert params["output_config"]["effort"] == "high"
    assert params["thinking"] == {"type": "disabled"} and params["max_tokens"] == 300


def test_request_params_append_problems_on_retry():
    params = build_request_params(make_recipe(), problems=["wrong count"])
    assert "wrong count" in params["messages"][0]["content"]
    assert len(params["messages"]) == 1


def test_parse_answer_rejects_early_stop_and_bad_json():
    with pytest.raises(ValueError, match="stopped early"):
        parse_answer(fake_message("{}", stop_reason="max_tokens"))
    with pytest.raises(ValueError):
        parse_answer(fake_message("not json"))


def test_estimate_cost_and_batch_discount():
    assert estimate_cost(1_000_000, 0) == pytest.approx(0.10)
    assert estimate_cost(0, 1_000_000) == pytest.approx(0.50)
    assert estimate_cost(1_000_000, 1_000_000, batch=True) == pytest.approx(0.30)


def test_augment_recipe_ok_first_try():
    client = FakeClient([make_result()])
    record = augment_recipe(client, make_recipe())
    assert record["status"] == "ok" and record["attempts"] == 1
    assert record["source_ref"] == 9001 and record["recipe_key"] == 1 and len(client.requests) == 1


def test_augment_recipe_passes_dials_through_and_records_mode():
    client = FakeClient([make_result()])
    record = augment_recipe(client, make_recipe(), thinking=THINKING_OFF)
    assert client.requests[0]["thinking"] == {"type": "disabled"}
    assert record["mode"] == "nothinking" and record["thinking_tokens"] == 0


def test_augment_recipe_sums_thinking_tokens_across_attempts():
    def with_thinking(text, thinking):
        msg = fake_message(text)
        msg.usage.output_tokens_details = SimpleNamespace(thinking_tokens=thinking)
        return msg

    bad = with_thinking(json.dumps(make_result(cuisines=[])), 30)
    good = with_thinking(json.dumps(make_result()), 20)
    record = augment_recipe(FakeClient([bad, good]), make_recipe())
    assert record["thinking_tokens"] == 50 and record["mode"] == "thinking"


def test_augment_recipe_retries_once_with_problems_and_sums_tokens():
    bad = make_result()
    bad["ingredients"].pop()
    client = FakeClient([bad, make_result()])
    record = augment_recipe(client, make_recipe())
    assert record["status"] == "ok" and record["attempts"] == 2
    assert record["input_tokens"] == 200 and record["output_tokens"] == 100
    assert "positions" in client.requests[1]["messages"][0]["content"]


def test_augment_recipe_retries_when_an_extra_repeats_a_listed_name():
    bad = make_result(extra_ingredients=[make_extra(name="eggs")])
    client = FakeClient([bad, make_result()])
    record = augment_recipe(client, make_recipe())
    assert record["status"] == "ok" and record["attempts"] == 2
    assert "already" in client.requests[1]["messages"][0]["content"]


def test_augment_recipe_fails_after_two_bad_answers():
    bad = make_result(cuisines=[])
    client = FakeClient([bad, bad])
    record = augment_recipe(client, make_recipe())
    assert record["status"] == "failed" and record["attempts"] == 2
    assert record["problems"] and len(client.requests) == 2


def test_augment_recipe_treats_cut_off_answer_as_a_problem():
    cut = fake_message("{", stop_reason="max_tokens")
    client = FakeClient([cut, make_result()])
    record = augment_recipe(client, make_recipe())
    assert record["status"] == "ok" and record["attempts"] == 2


def test_resume_skips_ok_but_not_failed(tmp_path):
    path = tmp_path / "out.jsonl"
    assert load_done_keys(path) == set()
    append_record(path, {"source_ref": 1, "status": "ok"})
    append_record(path, {"source_ref": 2, "status": "failed"})
    assert load_done_keys(path) == {1}


# --- stratified sample for the thinking comparison ---


def make_frame(n_equal=10, n_more=10, n_fewer=10):
    """Recipes whose quantity count is the same as, above, or below the name count."""
    rows = []
    for kind, count, extra in (("equal", n_equal, 0), ("more", n_more, 2), ("fewer", n_fewer, -1)):
        for i in range(count):
            parts = ["a", "b", "c"]
            rows.append(
                {
                    "kind": kind,
                    "recipe_key": len(rows) + 1,
                    "source_ref": 5000 + 7 * len(rows),
                    "ingredient_parts": parts,
                    "quantities_raw": ["1"] * (len(parts) + extra),
                }
            )
    return pd.DataFrame(rows)


def test_quantity_group_names_the_three_cases():
    assert quantity_group(4, 4) == "equal"
    assert quantity_group(4, 5) == "more"
    assert quantity_group(4, 3) == "fewer"


def test_stratified_sample_takes_the_quota_from_each_group():
    sample = stratified_sample(make_frame(), {"equal": 7, "more": 10, "fewer": 3}, seed=1)
    kinds = sample["kind"].value_counts().to_dict()
    assert kinds == {"equal": 7, "more": 10, "fewer": 3}
    assert sample["source_ref"].is_unique


def test_stratified_sample_is_reproducible_and_seed_dependent():
    quotas = {"equal": 3, "more": 3, "fewer": 3}
    a = stratified_sample(make_frame(), quotas, seed=5)["source_ref"].tolist()
    assert a == stratified_sample(make_frame(), quotas, seed=5)["source_ref"].tolist()
    assert a != stratified_sample(make_frame(), quotas, seed=6)["source_ref"].tolist()


def test_stratified_sample_raises_when_a_group_is_too_small():
    with pytest.raises(ValueError, match="fewer"):
        stratified_sample(make_frame(n_fewer=2), {"equal": 1, "more": 1, "fewer": 3}, seed=1)


# --- compare run: runner, snapshot, separate files per mode ---


def full_frame():
    """make_frame plus the other stage 1 columns, using numpy arrays like parquet gives."""
    df = make_frame(n_equal=2, n_more=2, n_fewer=2)
    df["name"] = [f"Recipe {k}" for k in df["source_ref"]]
    df["recipe_category"] = "Main"
    df["keywords"] = [np.array(["Easy", "Thai"])] * len(df)
    df["ingredient_parts"] = [np.array(p) for p in df["ingredient_parts"]]
    df["quantities_raw"] = [np.array(q) for q in df["quantities_raw"]]
    df["quantities_aligned"] = [len(p) == len(q) for p, q in zip(df["ingredient_parts"], df["quantities_raw"])]
    df["recipe_servings"] = [4.0, float("nan")] * 3
    df["recipe_yield"] = "4 servings"
    df["instructions"] = [np.array(["Mix.", "Serve."])] * len(df)
    return df


def test_run_recipes_writes_records_and_skips_done_ones(tmp_path):
    path = tmp_path / "out.jsonl"
    recipes = [make_recipe(source_ref=1), make_recipe(source_ref=2)]
    first = FakeClient([make_result(), make_result()])
    assert len(run_recipes(first, recipes, path, workers=1)) == 2
    second = FakeClient([])  # an API call here would raise, so none may happen
    assert run_recipes(second, recipes, path, workers=1) == []
    assert load_done_keys(path) == {1, 2}


def test_run_recipes_passes_dials_to_every_request(tmp_path):
    client = FakeClient([make_result()])
    run_recipes(client, [make_recipe()], tmp_path / "o.jsonl", 1, thinking=THINKING_OFF)
    assert client.requests[0]["thinking"] == {"type": "disabled"}


def test_stage1_snapshot_is_plain_json_with_missing_as_none():
    row = full_frame().iloc[1].to_dict()  # servings is NaN here
    snapshot = stage1_snapshot(row)
    assert snapshot["recipe_servings"] is None
    assert snapshot["keywords"] == ["Easy", "Thai"] and snapshot["group"] == "equal"
    json.dumps(snapshot)  # numpy types would raise here


def test_compare_modes_use_same_recipes_and_separate_files(tmp_path, monkeypatch):
    monkeypatch.setattr(augment_module, "PILOT_DIR", tmp_path)
    monkeypatch.setattr(augment_module, "COMPARE_QUOTAS", {"equal": 1, "more": 1, "fewer": 1})
    df = full_frame()
    thinking = FakeClient([make_result()] * 3)
    plain = FakeClient([make_result()] * 3)
    run_compare(thinking, df, "thinking", workers=1)
    run_compare(plain, df, "nothinking", workers=1)

    def keys(name):
        return {json.loads(line)["source_ref"] for line in (tmp_path / name).read_text().splitlines()}

    assert keys("results_thinking.jsonl") == keys("results_nothinking.jsonl") and len(keys("results_thinking.jsonl")) == 3
    assert all("thinking" not in r for r in thinking.requests)
    assert all(r["thinking"] == {"type": "disabled"} for r in plain.requests)
    assert len(json.loads((tmp_path / "stage1_rows.json").read_text())) == 3


def test_resume_uses_source_ref_not_the_position_number(tmp_path):
    """A shifted recipe_key (stage 1 changed) must not make a rerun skip the wrong recipe."""
    path = tmp_path / "out.jsonl"
    run_recipes(FakeClient([make_result()]), [make_recipe(source_ref=111, recipe_key=5)], path, 1)
    shifted = make_recipe(source_ref=222, recipe_key=5)  # same position number, different recipe
    client = FakeClient([make_result()])
    assert len(run_recipes(client, [shifted], path, 1)) == 1  # not skipped
    assert load_done_keys(path) == {111, 222}
