"""Tests for graphdb.schema: parsing runs anywhere, applying needs Neo4j."""

import pytest

from graphdb.client import close_driver, get_driver
from graphdb.schema import SCHEMA_FILE, apply_schema, split_statements


def test_split_statements_drops_comments_and_empty_parts():
    text = "// note; with a semicolon\nCREATE A;\n\n// more\nCREATE B\nFOR (x);\n"
    assert split_statements(text) == ["CREATE A", "CREATE B FOR (x)"]


def test_schema_file_has_the_expected_statements():
    statements = split_statements(SCHEMA_FILE.read_text())
    text = " ".join(statements)
    assert len(statements) == 4
    assert all("IF NOT EXISTS" in s for s in statements)
    for label, key in [
        ("Ingredient", "ingredient_id"),
        ("Recipe", "recipe_id"),
        ("PrepTask", "prep_task_id"),
    ]:
        assert f":{label}) REQUIRE" in text and f".{key} IS UNIQUE" in text


def _schema_names(driver) -> tuple[set[str], set[str]]:
    """Return (constraint names, index names) currently in the database."""
    with driver.session() as session:
        constraints = session.execute_read(
            lambda tx: {r["name"] for r in tx.run("SHOW CONSTRAINTS")}
        )
        indexes = session.execute_read(
            lambda tx: {r["name"] for r in tx.run("SHOW INDEXES")}
        )
    return constraints, indexes


@pytest.mark.neo4j
def test_apply_schema_twice_changes_nothing():
    try:
        driver = get_driver()
        apply_schema(driver)
        first = _schema_names(driver)
        apply_schema(driver)
        assert _schema_names(driver) == first
        constraints, indexes = first
        assert {
            "ingredient_id_unique",
            "recipe_id_unique",
            "prep_task_id_unique",
        } <= constraints
        assert "ingredient_name" in indexes
    finally:
        close_driver()
