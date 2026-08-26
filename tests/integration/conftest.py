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

isolated_audit_log extends the SAME isolation principle to logging --
core.intermediate_layer.audit's LOG_PATH is module-level, in-process
state, not something scoped per-test on its own. Without this, a test
exercising real writes/reads (test_full_roundtrip.py,
test_region_enforcement_e2e.py) would fall back to whatever LOG_PATH's
default resolves to -- the REAL deployment/var/log/audit.log a human
might actually be reading -- and, worse, whatever it gets set to would
persist for any OTHER test that runs afterward in the same pytest
process, regardless of that test's own intentions. This resets
LOG_PATH back to whatever it was before, in teardown, so no test's
logging configuration can leak into whatever runs next -- deterministic
regardless of test execution order, not just "happens to work" today.

This is PURELY a test-suite hygiene concern -- LOG_PATH lives in one
process's memory; a real deployment runs as a completely separate OS
process (uvicorn, or python3 -m scripts.run_deployment) and is never
touched by anything happening inside a pytest run.

read_audit_log() is a small shared helper (not a fixture -- just a
plain function both test_full_roundtrip.py and
test_region_enforcement_e2e.py import) for parsing the JSON-lines
audit log an isolated_audit_log-using test just produced, so each test
can assert on its OWN real, specific log entries.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from core.deployment_loader import load_deployment_bundle
from core.intermediate_layer import audit
from core.intermediate_layer.audit import configure_audit_log

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


@pytest.fixture
def isolated_audit_log(tmp_path: Path):
    original_log_path = audit.LOG_PATH
    log_dir = tmp_path / "log"
    configure_audit_log(log_dir)
    yield log_dir
    audit.LOG_PATH = original_log_path


def read_audit_log(log_dir: Path) -> list[dict]:
    log_path = log_dir / "audit.log"
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
