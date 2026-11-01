import json

import numpy as np
import pandas as pd

from pipelines.foodcom.load import (
    COLUMNS,
    build_rows,
    read_results,
    to_int,
    to_list,
    validate_answer,
)

GOOD_ANSWER = {"ingredients": [], "extra_ingredients": [], "cuisines": ["american"]}


def write_results(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def record(source_ref, status="ok", answer=GOOD_ANSWER, **extra):
    return {"source_ref": source_ref, "status": status, "result": answer, "model": "m", **extra}


def make_recipes(refs):
    return pd.DataFrame({
        "source_ref": refs,
        "name": [f"recipe {r}" for r in refs],
        "recipe_category": ["Chicken"] * len(refs),
        "keywords": [np.array(["Easy"])] * len(refs),
        "ingredient_parts": [np.array(["onion", "salt"])] * len(refs),
        "quantities_raw": [np.array(["1", ""])] * len(refs),
        "instructions": [np.array(["Chop.", "Cook."])] * len(refs),
        "recipe_servings": pd.array([4] * len(refs), dtype="Int64"),
        "total_minutes": pd.array([30] * len(refs), dtype="Int64"),
    })


def test_to_list_and_to_int_handle_missing_values():
    assert to_list(np.array(["a", "b"])) == ["a", "b"]
    assert to_list(None) == []
    assert to_int(pd.NA) is None
    assert to_int(float("nan")) is None
    assert to_int(np.int64(7)) == 7


def test_validate_answer_flags_missing_keys_and_wrong_types():
    assert validate_answer(GOOD_ANSWER) == []
    assert validate_answer(None) == ["answer is missing"]
    assert "missing key 'extra_ingredients'" in validate_answer({"ingredients": [], "cuisines": []})
    assert validate_answer({**GOOD_ANSWER, "cuisines": "american"}) == ["'cuisines' is not a list"]


def test_read_results_skips_bad_records_and_counts_why(tmp_path):
    path = tmp_path / "r.jsonl"
    write_results(path, [
        record(1),
        record(2, status="failed"),
        record(3, answer={"ingredients": []}),
        {"status": "ok", "result": GOOD_ANSWER},  # old record with no source_ref
    ])
    records, skipped = read_results(path)
    assert list(records) == [1]
    assert skipped == {"status not ok": 1, "bad answer shape": 1, "no source_ref": 1}


def test_read_results_last_good_record_wins(tmp_path):
    path = tmp_path / "r.jsonl"
    write_results(path, [record(1, model_note="old"), record(1, model_note="new")])
    records, _ = read_results(path)
    assert records[1]["model_note"] == "new"


def test_build_rows_loads_only_recipes_with_results_and_counts_orphans():
    recipes = make_recipes([1, 2, 3])
    results = {1: record(1), 3: record(3), 99: record(99)}
    rows, stats = build_rows(recipes, results)
    assert [r[0] for r in rows] == [1, 3]
    assert stats["results without a recipe"] == 1


def test_build_rows_matches_columns_and_writes_json_text():
    rows, _ = build_rows(make_recipes([1]), {1: record(1)})
    row = dict(zip(COLUMNS, rows[0], strict=True))
    assert len(rows[0]) == len(COLUMNS)
    assert json.loads(row["ingredient_parts"]) == ["onion", "salt"]
    assert json.loads(row["answer"]) == GOOD_ANSWER
    assert row["servings"] == 4 and row["total_minutes"] == 30 and row["model"] == "m"


def test_build_rows_keeps_missing_numbers_as_none():
    recipes = make_recipes([1])
    recipes["recipe_servings"] = pd.array([pd.NA], dtype="Int64")
    rows, _ = build_rows(recipes, {1: record(1)})
    assert dict(zip(COLUMNS, rows[0], strict=True))["servings"] is None
