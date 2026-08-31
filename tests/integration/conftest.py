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

isolated_audit_log extends the SAME isolation principle to logging.
This USED TO require saving, mutating, and restoring
core.intermediate_layer.audit's own module-level LOG_PATH global by
hand -- exactly the kind of fragile, easy-to-get-wrong test-isolation
workaround a real global forces (see AuditLog's own module docstring
for the full reasoning behind eliminating it). Now that AuditLog is a
real, per-instance object, this fixture is just an isolated directory
-- nothing to save or restore, since there's no shared global left to
corrupt in the first place.

_bundle now depends on isolated_audit_log directly and threads it
through load_deployment_bundle() -- a genuine improvement over the
old design, not just a mechanical translation: EVERY test using
mediator/deployment now automatically gets a properly isolated audit
log, not just the ones that remembered to also request
isolated_audit_log explicitly. Under the old, global-based design, a
test that forgot to request isolated_audit_log could silently write
real entries into the actual deployment/var/log/audit.log a human
might be reading, or leak its own logging configuration into whatever
ran next in the same pytest process; neither is possible now.

This is PURELY a test-suite hygiene concern -- a real deployment runs
as a completely separate OS process (uvicorn, or python3 -m
scripts.run_deployment) and is never touched by anything happening
inside a pytest run.

read_audit_log() now lives in tests/conftest.py, not duplicated here
-- it used to be defined verbatim in both conftest.py files (a real,
exact duplication, caught during a full pass over every test helper
function looking for exactly this). Both test_full_roundtrip.py and
test_region_enforcement_e2e.py import it directly from tests.conftest
now, not via this file at all -- the canonical source, not a
re-export through an intermediate module, for parsing the JSON-lines
audit log an isolated_audit_log-using test just produced, so each test
can assert on its OWN real, specific log entries.

_bundle builds THREE genuinely separate SQLite databases (schema.sql ->
mediator.db, support_schema.sql -> support.db, risk_schema.sql ->
risk.db), matching fixtures/config.yaml's three declared data_silos
(primary_sql, support_crm, risk_sql) -- for tests/integration/
test_cross_silo_e2e.py (a real model following a link that genuinely
crosses silos) and test_mdo_e2e.py (a real model transparently reading
an MDO field backed by a different silo than the rest of its object
type), neither scripted -- both already proven mechanically, with a
scripted model, by tests/unit/test_cross_silo_links.py and
tests/unit/test_mdo.py respectively. All three are rebuilt fresh into
pytest's tmp_path for every single test, same isolation discipline as
the single-database case this extends.
"""

import sqlite3
from pathlib import Path

import pytest

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import load_deployment_bundle
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.write_mediator import WriteMediator

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _build_sqlite_db(sql_file: Path, db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(sql_file.read_text())
    conn.commit()
    conn.close()


def propose_named_action(deployment, mediator, query_text: str):
    # Shared by test_named_actions_e2e.py and test_write_confirmation_e2e.py
    # -- both real-Ollama tests run a query through a real model,
    # expecting it to produce a propose_action step, then hand back
    # everything the calling test needs to confirm/reject and verify.
    # Was duplicated near-verbatim (identical logic, differing only in
    # the assertion's error-message wording) before this extraction,
    # caught during a full pass over every test helper function looking
    # for exactly this kind of duplication.
    write_mediator = WriteMediator(mediator, deployment.roles, deployment.action_types)
    loop = AgentLoop.from_deployment(deployment, mediator, write_mediator=write_mediator)
    user_record = resolve_user_record(deployment.users, "user_eve", deployment.security_attribute)

    result = loop.run(user_record, query_text)
    print(f"\n[diagnostic] pending_write: {result.pending_write}")
    print(f"[diagnostic] full gathered steps: {result.gathered}")

    assert result.pending_write is not None, (
        "Expected the real model to produce a well-formed propose_action step, "
        f"but it never reached the pending stage. Gathered: {result.gathered}"
    )
    return write_mediator, result.pending_write, user_record


@pytest.fixture
def isolated_audit_log(tmp_path: Path) -> Path:
    # Just an isolated directory now -- nothing to save or restore, no
    # global left to corrupt. See this file's own module docstring.
    return tmp_path / "log"


@pytest.fixture
def _bundle(tmp_path: Path, isolated_audit_log: Path):
    data_dir = tmp_path / "data"
    dev_fixtures_dir = data_dir / "dev_fixtures"
    dev_fixtures_dir.mkdir(parents=True)

    _build_sqlite_db(FIXTURES_DIR / "schema.sql", dev_fixtures_dir / "mediator.db")
    _build_sqlite_db(FIXTURES_DIR / "support_schema.sql", dev_fixtures_dir / "support.db")
    _build_sqlite_db(FIXTURES_DIR / "risk_schema.sql", dev_fixtures_dir / "risk.db")

    return load_deployment_bundle(FIXTURES_DIR, data_dir, isolated_audit_log)


@pytest.fixture
def deployment(_bundle):
    config, _ = _bundle
    return config


@pytest.fixture
def mediator(_bundle):
    _, mediator = _bundle
    return mediator
