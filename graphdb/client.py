"""Connection to Neo4j: one shared driver built from environment variables.

Everything that talks to the graph goes through get_driver(), so moving from
local Docker to AuraDB only changes NEO4J_URI in the environment.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

REQUIRED_VARS = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")


@dataclass(frozen=True)
class Neo4jConfig:
    """Where and how to connect. The password is hidden from repr and logs."""

    uri: str
    user: str
    password: str = field(repr=False)


def config_from_env(env: Mapping[str, str] | None = None) -> Neo4jConfig:
    """Read the three NEO4J_* variables into a Neo4jConfig.

    Takes the mapping as an argument so tests can pass a plain dict instead of
    touching os.environ. Raises a ValueError that names the missing variables
    (never their values).
    """
    env = os.environ if env is None else env
    missing = [name for name in REQUIRED_VARS if not env.get(name)]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    return Neo4jConfig(
        uri=env["NEO4J_URI"], user=env["NEO4J_USER"], password=env["NEO4J_PASSWORD"]
    )


@lru_cache(maxsize=1)
def get_driver() -> Driver:
    """Return the process-wide driver, creating it on the first call.

    A driver owns a pool of connections and is safe to share, so we build one
    and reuse it. Creating one per query would pay the connection and login
    cost every time.
    """
    config = config_from_env()
    return GraphDatabase.driver(config.uri, auth=(config.user, config.password))


def close_driver() -> None:
    """Close the shared driver and forget it, so the next get_driver() rebuilds."""
    if get_driver.cache_info().currsize:
        get_driver().close()
        get_driver.cache_clear()


def _return_one(tx) -> int:
    """Transaction function: ask the database for the number 1."""
    return tx.run("RETURN 1 AS one").single()["one"]


def health_check(driver: Driver | None = None) -> bool:
    """Return True if the database accepts our login and answers a query.

    Two steps: verify_connectivity() proves we can reach the server and log in,
    then a managed read transaction proves a query round-trips. Any driver or
    server error means False, because a health check should report, not raise.
    """
    driver = driver or get_driver()
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            return session.execute_read(_return_one) == 1
    except (DriverError, Neo4jError):
        return False
