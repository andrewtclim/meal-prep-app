"""Integration tests for graphdb.queries on the toy graph (need a running Neo4j).

Ids come from graphdb/toy/*.csv: onion 1, shallot 2, scallion 3, chive 4,
garlic 5, soy sauce 7, tamari 8, parsley 25, shio koji 34, leek 36.
"""

import pytest

from graphdb.client import close_driver, get_driver
from graphdb.queries import (
    find_substitutes,
    recipes_makeable_from,
    shared_prep_tasks,
)
from graphdb.seed_toy import seed_toy

pytestmark = pytest.mark.neo4j

ONION, SHALLOT, SHIO_KOJI, LEEK = 1, 2, 34, 36
RECIPE_6_PANTRY = [5, 15, 27, 32, 25]  # garlic, spaghetti, olive oil, chili flake, parsley


@pytest.fixture(scope="module", autouse=True)
def seeded():
    """Make sure the toy graph is loaded, and release the driver afterwards."""
    seed_toy(get_driver())
    yield
    close_driver()


def test_substitutes_for_onion_are_ranked_by_weight():
    result = find_substitutes(ONION)
    assert [(s.name, s.weight) for s in result] == [("shallot", 0.85), ("leek", 0.65)]
    assert all(s.model_version == "toy-v0" for s in result)


def test_direction_matters_shallot_for_onion_vs_onion_for_shallot():
    assert find_substitutes(ONION)[0].weight == 0.85
    assert find_substitutes(SHALLOT)[0].name == "onion"
    assert find_substitutes(SHALLOT)[0].weight == 0.60


def test_exclude_ids_and_limit():
    assert [s.ingredient_id for s in find_substitutes(ONION, exclude_ids=[SHALLOT])] == [LEEK]
    assert len(find_substitutes(ONION, limit=1)) == 1


def test_ingredient_without_substitute_returns_empty_list():
    assert find_substitutes(SHIO_KOJI) == []


def test_pantry_that_covers_a_recipe_makes_it_with_nothing_missing():
    result = recipes_makeable_from(RECIPE_6_PANTRY, max_missing=0)
    assert [r.name for r in result] == ["Garlic Chili Spaghetti"]
    assert result[0].missing_ids == ()


def test_max_missing_lets_in_recipes_that_are_one_item_short():
    pantry = [i for i in RECIPE_6_PANTRY if i != 25]  # no parsley
    assert recipes_makeable_from(pantry, max_missing=0) == []
    short = recipes_makeable_from(pantry, max_missing=1)
    assert [(r.recipe_id, r.missing_names) for r in short] == [(6, ("parsley",))]


def test_empty_pantry_makes_nothing():
    assert recipes_makeable_from([], max_missing=99) == []


def test_shared_prep_for_three_recipes_that_dice_onion():
    result = shared_prep_tasks([1, 3, 4])
    assert [(t.technique, t.ingredient_name, t.recipe_ids) for t in result] == [
        ("dice", "onion", (1, 3, 4)),
        ("mince", "garlic", (1, 3, 4)),
    ]


def test_shared_prep_finds_the_marinated_protein():
    names = {(t.technique, t.form, t.ingredient_name) for t in shared_prep_tasks([1, 2])}
    assert ("marinate", "soy-garlic", "chicken thigh") in names


def test_prep_used_by_only_one_chosen_recipe_is_not_shared():
    # shio koji salmon (7) and tofu bowl (8) share no prep task
    assert shared_prep_tasks([7, 8]) == []
    assert shared_prep_tasks([7]) == []
