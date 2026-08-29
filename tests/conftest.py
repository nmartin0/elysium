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
isolation need exists at the unit level: core.intermediate_layer.audit's
LOG_PATH is module-level, in-process state, not scoped per-test on its
own. Without this, a test asserting on audit-log CONTENT (not just a
function's return value) would fall back to whatever LOG_PATH's
default resolves to, and could leak its own logging configuration into
whatever test runs next in the same pytest process.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from core.intermediate_layer import audit
from core.intermediate_layer.audit import configure_audit_log

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
