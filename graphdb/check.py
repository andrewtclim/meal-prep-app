"""Print whether Neo4j is reachable. Run: uv run --env-file .env python -m graphdb.check"""

import sys

from graphdb.client import close_driver, config_from_env, health_check


def main() -> int:
    """Return exit code 0 if the database is reachable, 1 otherwise."""
    try:
        config = config_from_env()
    except ValueError as err:
        print(err)
        return 1
    ok = health_check()
    close_driver()
    print(f"Neo4j at {config.uri}: {'reachable' if ok else 'NOT reachable'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
