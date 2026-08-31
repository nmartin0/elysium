"""
conftest.py  (shared pytest fixtures)

Unit tests get their own ISOLATED temp SQLite database, never the real
deployment/var/lib/dev_fixtures/mediator.db -- that file is for your
own manual exploration, and a test suite that depends on its exact
current contents would be fragile and could interfere with what you're
doing by hand.

They also use a self-contained, made-up schema (Author/Book, not
Customer/Transaction) -- this is deliberate: it proves core/ontology's
logic is genuinely generic, not accidentally coupled to the real
deployment's specific domain.

isolated_audit_log / read_audit_log mirror
tests/integration/conftest.py's own fixture exactly -- the same
isolation need exists at the unit level: each test needs its own,
separate audit.log file, not one shared across the whole test
process. This USED TO require saving, mutating, and restoring
core.intermediate_layer.audit's own module-level LOG_PATH global by
hand -- exactly the kind of fragile, easy-to-get-wrong test-isolation
workaround a real global forces (see AuditLog's own module docstring
for the full reasoning behind eliminating it). Now that AuditLog is a
real, per-instance object, this fixture is just an isolated directory
-- nothing to save or restore, since there's no shared global left to
corrupt in the first place. Callers construct their own
AuditLog(isolated_audit_log / "audit.log") to pass into DataMediator
explicitly.

scripted_llm_client() is a shared helper for scripting AgentLoop's
model responses without touching the real HTTP layer -- was
duplicated near-verbatim (identical mocking logic, only the final
AgentLoop construction differing) across
test_agentic_loop_writes_and_cancellation.py and
test_tool_authorization.py before this extraction, caught during a
full pass over every test helper function looking for exactly this
kind of duplication.
"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

TEST_SCHEMA = {
    "Author": {
        "storage": {"silo": "test_silo", "table": "authors", "id_column": "author_id"},
        "id_field": "author_id",
        "security": {"field": "org_id"},
        "fields": {
            "org_id": {"type": "data"},
            "name": {"type": "data"},
            "books": {
                "type": "link",
                "target": "Book",
                "cardinality": "many",
                "via_table": "books",
                "via_column": "author_id",
            },
        },
    },
    "Book": {
        "storage": {"silo": "test_silo", "table": "books", "id_column": "book_id"},
        "id_field": "book_id",
        "security": {"via_field": "author_id"},
        "fields": {
            "title": {"type": "data"},
            "year": {"type": "data"},
            "author_id": {"type": "link", "target": "Author", "cardinality": "one"},
        },
    },
}

TEST_SCHEMA_SQL = """
CREATE TABLE authors (
    author_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    name TEXT NOT NULL
);
CREATE TABLE books (
    book_id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id TEXT NOT NULL,
    title TEXT NOT NULL,
    year INTEGER NOT NULL,
    FOREIGN KEY (author_id) REFERENCES authors (author_id)
);
INSERT INTO authors (author_id, org_id, name) VALUES
    ('auth_001', 'org-a', 'Ada Lovelace'),
    ('auth_002', 'org-b', 'Grace Hopper');
INSERT INTO books (author_id, title, year) VALUES
    ('auth_001', 'Notes on the Analytical Engine', 1843),
    ('auth_001', 'Sketch of the Analytical Engine', 1842),
    ('auth_002', 'A New Glossary', 1952);
"""


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    # A fresh, isolated SQLite database for one test, built from
    # TEST_SCHEMA_SQL. tmp_path is a pytest builtin -- a unique temp
    # directory per test, cleaned up automatically.
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(TEST_SCHEMA_SQL)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def test_schema() -> dict:
    return TEST_SCHEMA


@pytest.fixture
def isolated_audit_log(tmp_path: Path) -> Path:
    # Just an isolated directory now -- nothing to save or restore, no
    # global left to corrupt. See this file's own module docstring.
    return tmp_path / "log"


def scripted_llm_client(scripted_steps: list[dict]) -> MagicMock:
    # A MagicMock standing in for an LLMAdapter, whose .chat() replays
    # a fixed sequence of JSON-encoded step responses -- shared by
    # every unit test that needs to script AgentLoop's model behavior
    # deterministically, without touching the real HTTP layer at all.
    # Once the scripted sequence is exhausted, repeats the LAST entry
    # rather than raising IndexError -- a test scripting "propose the
    # action, then optionally get asked for one more hop" doesn't need
    # to pad its own list with a redundant final entry just to survive
    # an extra call.
    client = MagicMock()
    call_count = {"n": 0}

    def fake_chat(*args, **kwargs):
        idx = min(call_count["n"], len(scripted_steps) - 1)
        call_count["n"] += 1
        return json.dumps(scripted_steps[idx])

    client.chat.side_effect = fake_chat
    return client


def read_audit_log(log_dir: Path) -> list[dict]:
    log_path = log_dir / "audit.log"
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
