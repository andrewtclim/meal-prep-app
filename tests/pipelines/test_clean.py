import numpy as np
import pandas as pd

from pipelines.foodcom.clean import (
    add_minutes_columns,
    add_quantities_aligned,
    add_recipe_key,
    dedupe_by_name,
    drop_junk_rows,
    has_content,
    make_arrays_plain,
    normalize_name,
    parse_duration_minutes,
    singularize,
    to_snake_case,
    to_str_list,
    trim_and_rename,
)


def test_snake_case():
    assert to_snake_case("CookTime") == "cook_time"
    assert to_snake_case("RecipeIngredientParts") == "recipe_ingredient_parts"
    assert to_snake_case("Name") == "name"


def test_to_str_list_handles_numpy_list_and_missing():
    assert to_str_list(np.array(["a", "b"], dtype=object)) == ["a", "b"]
    assert to_str_list(["a"]) == ["a"]
    assert to_str_list(None) == []
    assert to_str_list(float("nan")) == []


def test_to_str_list_unescapes_trims_and_keeps_blanks():
    # Blanks stay: dropping one would shift every later item out of position.
    assert to_str_list(["  Mac &amp; Cheese ", "", None]) == ["Mac & Cheese", "", ""]


def test_trim_and_rename_and_arrays():
    raw = pd.DataFrame({
        "RecipeId": [38.0], "Name": ["x"], "AuthorId": [1], "AuthorName": ["a"],
        "DatePublished": [pd.Timestamp("2020-01-01")], "Images": [None], "Keywords": [["k"]],
        "RecipeIngredientParts": [np.array(["salt"], dtype=object)],
        "RecipeIngredientQuantities": [np.array(["1⁄4"], dtype=object)],
        "RecipeInstructions": [["mix"]],
    })
    out = trim_and_rename(make_arrays_plain(raw))
    assert list(out.columns) == [
        "source_ref", "name", "images", "keywords",
        "ingredient_parts", "quantities_raw", "instructions",
    ]
    assert out.loc[0, "source_ref"] == 38 and out["source_ref"].dtype == "int64"
    assert out.loc[0, "images"] == [] and out.loc[0, "quantities_raw"] == ["1⁄4"]


def test_parse_duration_minutes():
    assert parse_duration_minutes("PT1H30M") == 90
    assert parse_duration_minutes("PT24H") == 1440
    assert parse_duration_minutes("PT45M") == 45
    assert parse_duration_minutes("PT0S") == 0


def test_parse_duration_minutes_returns_none_for_bad_input():
    # Negative parts, empty durations, day-based durations, text and missing values.
    for bad in ["PT-30M", "PT", "P1D", "garbage", "", None, float("nan")]:
        assert parse_duration_minutes(bad) is None


def test_add_minutes_columns():
    df = pd.DataFrame({
        "cook_time": [None, "PT30M", "PT0S"],
        "prep_time": ["PT0S", "PT15M", "PT-1M"],
        "total_time": ["PT0S", "PT45M", "PT25H"],
    })
    out = add_minutes_columns(df)
    assert list(out.columns) == ["cook_minutes", "prep_minutes", "total_minutes", "time_suspect"]
    assert out["total_minutes"].isna().tolist() == [True, False, False]  # PT0S total -> missing
    assert out["prep_minutes"].tolist()[:2] == [0, 15]  # prep zero is kept
    assert pd.isna(out["prep_minutes"][2]) and pd.isna(out["cook_minutes"][0])
    assert out["time_suspect"].tolist() == [False, False, True]


def test_has_content():
    assert has_content(["a"]) and has_content(["", "a"])
    assert not has_content([]) and not has_content(["", ""])


def test_drop_junk_rows_counts_each_rule_once():
    df = pd.DataFrame({
        "ingredient_parts": [["salt"], [], [], ["egg"], ["milk"]],
        "instructions": [["mix"], ["mix"], [], [""], ["stir"]],
    })
    out, removed = drop_junk_rows(df)
    # Row 2 breaks both rules but is counted under the first only.
    assert removed == {"no ingredient parts": 2, "no instructions": 1}
    assert out["ingredient_parts"].tolist() == [["salt"], ["milk"]]
    assert out.index.tolist() == [0, 1]


def test_add_quantities_aligned():
    df = pd.DataFrame({
        "ingredient_parts": [["a", "b"], ["a"]],
        "quantities_raw": [["1", "2"], ["1", "2", "3"]],
    })
    assert add_quantities_aligned(df)["quantities_aligned"].tolist() == [True, False]


def test_singularize():
    assert singularize("lemonades") == "lemonade"
    assert singularize("cookies") == "cooky"
    assert singularize("potatoes") == "potato"
    assert singularize("sandwiches") == "sandwich"
    # Not plurals: must be left alone.
    assert singularize("hummus") == "hummus" and singularize("glass") == "glass"
    # Singular and plural must meet on one key, whatever the key looks like.
    for single, plural in [("pie", "pies"), ("cookie", "cookies"), ("berry", "berries"), ("cake", "cakes")]:
        assert singularize(single) == singularize(plural)


def test_normalize_name_groups_variants():
    keys = {normalize_name(n, 1) for n in ["Lemonade", "lemonade!", " LEMONADES ", "Lemon-ade"[:0] + "lemonade"]}
    assert keys == {"lemonade"}
    assert normalize_name("Grandma's Cookies", 1) == normalize_name("grandmas cooky", 2)


def test_normalize_name_never_merges_empty_names():
    assert normalize_name("!!!", 7) != normalize_name("???", 8)


def test_dedupe_keeps_best_rated_then_most_reviewed_then_lowest_ref():
    df = pd.DataFrame({
        "source_ref": [5, 3, 9, 2, 4],
        "name": ["Pie", "pie!", "Pies", "Soup", "Soup"],
        "aggregated_rating": [4.0, 4.5, 4.5, None, None],
        "review_count": [10, 1, 7, None, None],
    })
    out, top = dedupe_by_name(df)
    # Pie group: 3 and 9 tie on rating, 9 has more reviews. Soup group: all tied, lowest ref wins.
    assert out["source_ref"].tolist() == [2, 9]
    assert top.loc[0, "size"] == 3


def test_add_recipe_key_is_sequential_by_source_ref():
    out = add_recipe_key(pd.DataFrame({"source_ref": [30, 10, 20]}))
    assert out["source_ref"].tolist() == [10, 20, 30]
    assert out["recipe_key"].tolist() == [1, 2, 3]
