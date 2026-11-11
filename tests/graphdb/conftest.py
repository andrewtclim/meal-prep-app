"""Skip tests marked `neo4j` when no database is configured (e.g. in CI)."""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Add a skip to every neo4j-marked test if NEO4J_URI is not set."""
    if os.environ.get("NEO4J_URI"):
        return
    skip = pytest.mark.skip(reason="NEO4J_URI not set; needs a running Neo4j")
    for item in items:
        if "neo4j" in item.keywords:
            item.add_marker(skip)
