"""Apply graphdb/schema.cypher to the database. Safe to run any number of times.

Run: uv run --group agent --env-file .env python -m graphdb.schema
"""

from pathlib import Path

from neo4j import Driver

from graphdb.client import close_driver, get_driver

SCHEMA_FILE = Path(__file__).parent / "schema.cypher"


def split_statements(text: str) -> list[str]:
    """Split Cypher text into statements: drop // comment lines, cut on ';'.

    Pure so it can be tested without a database. Comments are removed first so
    a semicolon inside a comment cannot split a statement in two.
    """
    code = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("//")
    )
    return [" ".join(part.split()) for part in code.split(";") if part.strip()]


def _run(tx, statement: str) -> None:
    """Transaction function: run one schema statement."""
    tx.run(statement)


def apply_schema(driver: Driver | None = None, path: Path = SCHEMA_FILE) -> int:
    """Run every statement in the schema file and return how many ran.

    Each statement gets its own write transaction, because Neo4j does not let
    schema changes share a transaction with each other or with data writes.
    IF NOT EXISTS in the file is what makes a second run a no-op.
    """
    driver = driver or get_driver()
    statements = split_statements(path.read_text())
    with driver.session() as session:
        for statement in statements:
            session.execute_write(_run, statement)
    return len(statements)


if __name__ == "__main__":
    count = apply_schema()
    close_driver()
    print(f"Applied {count} schema statements")
