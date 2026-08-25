"""
conftest.py  (integration tests -- a FULLY isolated test deployment)

tests/integration/fixtures/ is a genuinely separate deployment used
ONLY by this test suite -- config, schema, policy, and data all live
here, never in the real deployment/ folder a human explores. Same
principle tests/conftest.py's Author/Book test schema already
established for tests/unit/, applied here too.

A FRESH SQLite database is built from fixtures/schema.sql into
pytest's tmp_path for EVERY test -- matching tests/conftest.py's own
per-test isolation pattern exactly. Nothing a test does here can ever
affect another test, a future test run, or the real deployment/'s
shipped demo data.
"""

import sqlite3
from pathlib import Path

import pytest

from core.deployment_loader import load_deployment_bundle

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def _bundle(tmp_path: Path):
    data_dir = tmp_path / "data"
    dev_fixtures_dir = data_dir / "dev_fixtures"
    dev_fixtures_dir.mkdir(parents=True)

    db_path = dev_fixtures_dir / "mediator.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((FIXTURES_DIR / "schema.sql").read_text())
    conn.commit()
    conn.close()

    return load_deployment_bundle(FIXTURES_DIR, data_dir)


@pytest.fixture
def deployment(_bundle):
    config, _ = _bundle
    return config


@pytest.fixture
def mediator(_bundle):
    _, mediator = _bundle
    return mediator
