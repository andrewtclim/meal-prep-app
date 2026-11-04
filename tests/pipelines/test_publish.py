"""Tests for pipelines/foodcom/publish.py that need no database.

The SQL itself is checked by running the script against the database (--dry-run);
here we check the parts that are plain Python.
"""

import pytest

from pipelines.foodcom import publish


def test_every_listed_sql_file_exists_and_is_not_empty():
    """A typo in STEPS or CHECKS would otherwise only show up when publishing."""
    for filename in [*publish.CHECKS.values(), *publish.STEPS]:
        assert publish.read_sql(filename).strip(), filename


def test_every_sql_file_is_listed():
    """A file left out of STEPS and CHECKS would silently never run."""
    listed = {*publish.CHECKS.values(), *publish.STEPS}
    on_disk = {path.name for path in publish.SQL_DIR.glob("*.sql")}
    assert on_disk == listed


def test_steps_run_parents_before_children():
    """Foreign keys need ingredients and recipes to exist before the link rows."""
    steps = publish.STEPS
    assert steps.index("10_upsert_ingredients.sql") < steps.index("31_insert_recipe_ingredient.sql")
    assert steps.index("20_upsert_recipes.sql") < steps.index("31_insert_recipe_ingredient.sql")
    assert steps.index("20_upsert_recipes.sql") < steps.index("41_insert_recipe_cuisine.sql")


def test_each_delete_runs_right_before_its_insert():
    """A delete far from its insert is how a recipe ends up with no rows."""
    steps = publish.STEPS
    assert steps.index("31_insert_recipe_ingredient.sql") == steps.index("30_delete_recipe_ingredient.sql") + 1
    assert steps.index("41_insert_recipe_cuisine.sql") == steps.index("40_delete_recipe_cuisine.sql") + 1


def test_deletes_only_touch_food_com_recipes():
    """The delete must be limited to recipes in staging, never user-saved ones."""
    for filename in ("30_delete_recipe_ingredient.sql", "40_delete_recipe_cuisine.sql"):
        assert "staging.stg_recipes" in publish.read_sql(filename), filename


def test_format_problems_lists_only_labels_with_names():
    text = publish.format_problems({"units missing": ["can", "dash"], "cuisines missing": []})
    assert text == "units missing: can, dash"


def test_format_problems_is_empty_when_nothing_is_missing():
    assert publish.format_problems({"units missing": [], "cuisines missing": []}) == ""


def test_missing_names_error_carries_the_message():
    with pytest.raises(publish.MissingNamesError, match="swedish"):
        raise publish.MissingNamesError("cuisines missing: swedish")
