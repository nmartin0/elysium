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


def build(schema_path: Path, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_path.read_text())
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="rebuild databases that already exist, discarding their contents")
    args = parser.parse_args()

    paths = resolve_runtime_paths()
    target = paths.data_dir / "dev_fixtures"

    for schema_name, db_name in DATABASES:
        schema_path = FIXTURES / schema_name
        if not schema_path.exists():
            print(f"Missing fixture schema {schema_path}", file=sys.stderr)
            return 1
        db_path = target / db_name
        if db_path.exists() and not args.force:
            print(f"  {db_name} exists, left alone (--force to rebuild)")
            continue
        if db_path.exists():
            db_path.unlink()
        build(schema_path, db_path)
        print(f"  built {db_path}")

    print(f"\nSilos are in {target}.")
    print("Restart the server, then check Admin -> Silos: all three should be reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
