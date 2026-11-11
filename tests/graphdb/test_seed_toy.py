"""Tests for graphdb.seed_toy: data checks run anywhere, seeding needs Neo4j."""

from collections import Counter

import pytest

from graphdb.client import close_driver, get_driver
from graphdb.seed_toy import (
    count_toy,
    load_toy_data,
    seed_toy,
    validate_toy_data,
    wipe_toy,
)


@pytest.fixture(scope="module")
def data():
    """The parsed toy CSVs, loaded once for the module."""
    return load_toy_data()


def _ids(data):
    """Map ingredient name to id."""
    return {r["name"]: r["ingredient_id"] for r in data["ingredients"]}


def test_toy_data_passes_validation(data):
    validate_toy_data(data)


def test_sizes_match_the_plan(data):
    assert len(data["recipes"]) == 8
    assert 30 <= len(data["ingredients"]) <= 40


def test_onion_is_diced_for_at_least_three_recipes(data):
    onion = _ids(data)["onion"]
    dice = next(
        t
        for t in data["prep_tasks"]
        if t["ingredient_id"] == onion and t["technique"] == "dice"
    )
    recipes = {
        r["recipe_id"]
        for r in data["recipe_prep_task"]
        if r["prep_task_id"] == dice["prep_task_id"]
    }
    assert len(recipes) >= 3


def test_marinated_protein_is_a_prep_task_shared_by_two_recipes(data):
    marinades = [t for t in data["prep_tasks"] if t["technique"] == "marinate"]
    shared = Counter(r["prep_task_id"] for r in data["recipe_prep_task"])
    assert any(shared[t["prep_task_id"]] >= 2 for t in marinades)


def test_substitution_pairs_exist_in_both_directions(data):
    ids = _ids(data)
    edges = {(s["substitute_id"], s["original_id"]) for s in data["substitutions"]}
    for a, b in [("shallot", "onion"), ("scallion", "chive"), ("soy sauce", "tamari")]:
        assert (ids[a], ids[b]) in edges
        assert (ids[b], ids[a]) in edges


def test_shallot_and_onion_weights_differ_by_direction(data):
    ids = _ids(data)
    weight = {
        (s["substitute_id"], s["original_id"]): s["weight"]
        for s in data["substitutions"]
    }
    assert weight[(ids["shallot"], ids["onion"])] > weight[(ids["onion"], ids["shallot"])]


def test_shio_koji_has_no_substitute(data):
    koji = _ids(data)["shio koji"]
    touching = [
        s for s in data["substitutions"] if koji in (s["substitute_id"], s["original_id"])
    ]
    assert touching == []


def test_validation_rejects_unknown_unit_and_bad_weight(data):
    bad = {k: [dict(r) for r in v] for k, v in data.items()}
    bad["recipe_ingredient"][0]["unit"] = "handful"
    bad["substitutions"][0]["weight"] = 1.5
    with pytest.raises(ValueError) as err:
        validate_toy_data(bad)
    assert "handful" in str(err.value) and "weight" in str(err.value)


def test_validation_rejects_dangling_ids(data):
    bad = {k: [dict(r) for r in v] for k, v in data.items()}
    bad["recipe_prep_task"].append({"recipe_id": 99, "prep_task_id": 1})
    with pytest.raises(ValueError):
        validate_toy_data(bad)


@pytest.mark.neo4j
def test_seeding_twice_keeps_counts_the_same(data):
    try:
        driver = get_driver()
        seed_toy(driver)
        first = count_toy(driver)
        seed_toy(driver)
        assert count_toy(driver) == first
        assert first == {
            "Ingredient": len(data["ingredients"]),
            "Recipe": len(data["recipes"]),
            "PrepTask": len(data["prep_tasks"]),
            "USED_IN": len(data["recipe_ingredient"]),
            "APPLIES_TO": len(data["prep_tasks"]),
            "REQUIRES": len(data["recipe_prep_task"]),
            "SUBSTITUTES_FOR": len(data["substitutions"]),
        }
    finally:
        close_driver()


@pytest.mark.neo4j
def test_wipe_removes_only_toy_nodes_and_reseed_restores_them():
    try:
        driver = get_driver()
        seed_toy(driver)
        with driver.session() as session:
            session.execute_write(
                lambda tx: tx.run("MERGE (:Ingredient {ingredient_id: 999999})")
            )
        wipe_toy(driver)
        assert count_toy(driver) == {}
        with driver.session() as session:
            survivors = session.execute_read(
                lambda tx: tx.run(
                    "MATCH (i:Ingredient {ingredient_id: 999999}) RETURN count(i) AS n"
                ).single()["n"]
            )
            session.execute_write(
                lambda tx: tx.run(
                    "MATCH (i:Ingredient {ingredient_id: 999999}) DELETE i"
                )
            )
        assert survivors == 1
    finally:
        seed_toy(get_driver())
        close_driver()
