"""Unit tests for graphdb.client. No database needed except the marked one."""

import pytest
from neo4j.exceptions import ServiceUnavailable

from graphdb.client import close_driver, config_from_env, get_driver, health_check

GOOD_ENV = {
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "s3cret-value",
}


class FakeSession:
    """Stands in for a driver session; execute_read just calls the function."""

    def __init__(self, tx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_read(self, fn):
        return fn(self.tx)


class FakeTx:
    """Stands in for a transaction whose RETURN 1 query yields `value`."""

    def __init__(self, value):
        self.value = value

    def run(self, _query):
        return self

    def single(self):
        return {"one": self.value}


class FakeDriver:
    """Driver double: can be told to fail on connect or to return a value."""

    def __init__(self, value=1, connect_error=None):
        self.value = value
        self.connect_error = connect_error

    def verify_connectivity(self):
        if self.connect_error:
            raise self.connect_error

    def session(self):
        return FakeSession(FakeTx(self.value))


def test_config_from_env_reads_values():
    config = config_from_env(GOOD_ENV)
    assert (config.uri, config.user) == ("bolt://localhost:7687", "neo4j")


def test_config_repr_hides_password():
    assert "s3cret-value" not in repr(config_from_env(GOOD_ENV))


def test_config_names_missing_variables_but_no_values():
    env = {"NEO4J_URI": "bolt://x:7687", "NEO4J_PASSWORD": "s3cret-value"}
    with pytest.raises(ValueError) as err:
        config_from_env(env)
    assert "NEO4J_USER" in str(err.value)
    assert "s3cret-value" not in str(err.value)


def test_health_check_true_when_query_returns_one():
    assert health_check(FakeDriver()) is True


def test_health_check_false_when_unreachable():
    assert health_check(FakeDriver(connect_error=ServiceUnavailable("down"))) is False


def test_health_check_false_on_wrong_answer():
    assert health_check(FakeDriver(value=2)) is False


@pytest.mark.neo4j
def test_health_check_against_real_database():
    try:
        assert health_check() is True
    finally:
        close_driver()


def test_get_driver_is_cached_when_configured(monkeypatch):
    for name, value in GOOD_ENV.items():
        monkeypatch.setenv(name, value)
    close_driver()
    try:
        assert get_driver() is get_driver()
    finally:
        close_driver()
