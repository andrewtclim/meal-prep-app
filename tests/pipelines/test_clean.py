import numpy as np
import pandas as pd

from pipelines.foodcom.clean import (
    make_arrays_plain,
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
