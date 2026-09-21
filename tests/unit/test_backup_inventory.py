"""
Every database Elysium creates is either backed up or excluded on purpose.

THE INVENTORY FELL BEHIND THE CODE TWICE, and nothing noticed either
time, because the backup script and the restore check both read the
same hand-kept list.

  FIRST: "seven, not the five the roadmap listed" -- the mirror's
  catalog.db was missed, and sync_attempts.db did not exist yet.

  SECOND: pending_writes.db arrived in the commit AFTER the backup
  script, and saved_views, triggers and notifications later still. A
  restore would have dropped every waiting approval, saved view,
  trigger and notification -- and passed its own check.

SO THIS COMPARES THE LIST WITH THE CODE. Every string constant that is
exactly a database filename, anywhere in the application, must be
listed in OWNED_DATABASES or excluded below with a reason. A new store
that forgets the backup fails here, in the commit that adds it.

WHY STRING CONSTANTS, PARSED. Databases are opened several ways --
`data_dir / "x.db"`, `mirror_dir / "x.db"`, and inside an f-string
building a SQLAlchemy URI. Parsing finds all three. A docstring that
MENTIONS a database is a sentence, never exactly a filename, so it is
not mistaken for one.
"""

import ast
import pathlib
import re

from scripts.backup_deployment import OWNED_DATABASES

_DATABASE_FILENAME = re.compile(r"^[a-z_]+\.db$")

# NOT BACKED UP, EACH FOR A STATED REASON. Adding a name here is a
# decision somebody has to write down, which is the point.
DELIBERATELY_EXCLUDED = {
    # CUSTOMER DATA. The dev silos stand in for a customer's own
    # databases, which a backup of Elysium must not capture -- they
    # belong to their owner and have their own backups.
    "mediator.db": "a data silo -- customer data, not Elysium's",
    "risk.db": "a data silo -- customer data, not Elysium's",
    "support.db": "a data silo -- customer data, not Elysium's",
    # A PendingWriteStore built without saying where its database is
    # makes a private one in a temporary directory -- tests do this.
    # It is never under the data directory.
    "pending.db": "a temporary default, never under the data directory",
}

_APPLICATION = ("api", "core", "scripts", "adapters")


def _database_names_in_code() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for root in _APPLICATION:
        for path in pathlib.Path(root).rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and _DATABASE_FILENAME.match(node.value)
                ):
                    found.setdefault(node.value, []).append(
                        f"{path}:{node.lineno}",
                    )
    return found


def test_every_database_is_backed_up_or_excluded_on_purpose():
    owned = {name.rsplit("/", 1)[-1] for name in OWNED_DATABASES}

    unaccounted = {
        name: where
        for name, where in _database_names_in_code().items()
        if name not in owned and name not in DELIBERATELY_EXCLUDED
    }

    assert unaccounted == {}, (
        "These databases are created by the application but neither "
        "backed up (scripts/backup_deployment.py OWNED_DATABASES) nor "
        f"excluded with a reason (DELIBERATELY_EXCLUDED): {unaccounted}"
    )


def test_nothing_is_both_backed_up_and_excluded():
    owned = {name.rsplit("/", 1)[-1] for name in OWNED_DATABASES}

    assert owned & set(DELIBERATELY_EXCLUDED) == set()


def test_the_scan_finds_what_it_should():
    """THE CONTROL ON THE SCAN ITSELF. A pattern that matched nothing
    would make the first test pass vacuously -- so it must find the
    ones known to be there, including the f-string case."""
    found = _database_names_in_code()

    for name in ("credentials.db", "pending_writes.db", "catalog.db"):
        assert name in found, name


def test_the_four_that_were_missing_are_now_listed():
    """THE SECOND DRIFT, pinned by name."""
    for name in ("pending_writes.db", "saved_views.db", "triggers.db",
                 "notifications.db"):
        assert name in OWNED_DATABASES, name
