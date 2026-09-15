"""Builds the development silo databases from the fixture schemas.

The integration suite builds these into a tmp_path for every run, so
the tests have never needed them to persist. A development SERVER
does, and nothing created them -- which is why they vanish whenever
/tmp is cleared and the silos come back unreachable.

Idempotent: an existing database is left alone unless --force is
given, so running this after a reboot costs nothing and running it by
mistake does not discard data someone was using.

DEVELOPMENT ONLY. It reads tests/integration/fixtures and writes into
ELYSIUM_DATA_DIR; a real deployment's silos are somebody else's
databases and are not created by us.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.deployment_loader import resolve_runtime_paths  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "integration" / "fixtures"

# The same three the integration conftest builds, and the same
# schema-to-database mapping -- deliberately, so a developer's server
# and the test suite disagree about nothing.
DATABASES = [
    ("schema.sql", "mediator.db"),
    ("support_schema.sql", "support.db"),
    ("risk_schema.sql", "risk.db"),
]


def _has_tables(db_path) -> bool:
    """Whether a database can actually serve a read.

    PRESENCE IS NOT USABILITY, and this script conflated them. So did
    SQLiteReadAdapter.health_check(), which reported an empty database
    reachable -- the same fault in two places, found when a dev
    database was restored to a state with no tables and every read
    returned a raw 500 while everything claimed to be fine.
    """
    import sqlite3

    try:
        with sqlite3.connect(db_path) as conn:
            return bool(conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0])
    except sqlite3.Error:
        # Unreadable is as unusable as empty, and rebuilding is the
        # right answer to both.
        return False


def db_name_of(db_path: Path) -> str:
    return db_path.name


def _add_bulk_transactions(conn, count: int) -> None:
    """Extra synthetic transactions, for exercising paging in a browser.

    WHY THIS IS A FLAG AND NOT THE FIXTURE. The fixture is shared with
    the integration suite, and this module's own comment says why the
    two must agree: "so a developer's server and the test suite
    disagree about nothing". Tests want small, deterministic data --
    several assert exact counts. A browser wants enough rows to page.

    Opt-in keeps both: `--bulk 60` gives a developer a pageable list,
    and the default of 0 leaves the databases byte-identical to what
    the tests build.

    ON CUSTOMERS THE DEV USER CAN SEE. alice is us-west, and rows
    filed under a region she cannot read would be filtered out by MAC
    before reaching the page -- giving a list that is still short and a
    developer who concludes paging is broken.

    DELIBERATELY BORING VALUES. These exist to make a list long, not to
    be interesting: a synthetic row that looked like real data would
    eventually be quoted in a bug report as though it were.
    """
    rows = [
        (
            "cust_001" if index % 2 == 0 else "cust_002",
            round(10.0 + index, 2),
            "USD",
            f"bulk-{index % 5}",
            "2026-08-01",
        )
        for index in range(count)
    ]
    conn.executemany(
        "INSERT INTO transactions (customer_id, amount, currency, category, "
        "transaction_date) VALUES (?, ?, ?, ?, ?)",
        rows,
    )


def build(schema_path: Path, db_path: Path, bulk: int = 0) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_path.read_text())
        if bulk > 0 and db_name_of(db_path) == "mediator.db":
            _add_bulk_transactions(conn, bulk)
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="rebuild databases that already exist, discarding their contents")
    parser.add_argument("--bulk", type=int, default=0, metavar="N",
                        help="add N extra synthetic transactions, for exercising paging "
                             "and bulk selection in a browser. The default of 0 keeps a "
                             "developer's server identical to the test fixtures.")
    args = parser.parse_args()

    paths = resolve_runtime_paths()
    target = paths.data_dir / "dev_fixtures"

    for schema_name, db_name in DATABASES:
        schema_path = FIXTURES / schema_name
        if not schema_path.exists():
            print(f"Missing fixture schema {schema_path}", file=sys.stderr)
            return 1
        db_path = target / db_name
        if db_path.exists() and not args.force and _has_tables(db_path):
            print(f"  {db_name} exists, left alone (--force to rebuild)")
            continue
        if db_path.exists() and not args.force:
            # EXISTS BUT IS EMPTY, which the old check could not see. It
            # tested for the FILE and reported "left alone" about a
            # database with no tables -- reassurance while the
            # deployment was unusable, and the operator then had to
            # work out that --force was needed for a database they had
            # just been told was fine.
            #
            # Rebuilt without --force, because an empty database is not
            # data anybody is using: the flag exists to protect real
            # rows, and there are none.
            print(f"  {db_name} exists but has no tables -- rebuilding")
        if db_path.exists():
            db_path.unlink()
        build(schema_path, db_path, args.bulk)
        print(f"  built {db_path}")

    print(f"\nSilos are in {target}.")
    print("Restart the server, then check Admin -> Silos: all three should be reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
