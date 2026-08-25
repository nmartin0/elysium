"""
sqlite_connection.py  (the ONE shared "open a raw connection" helper)

Used by adapters/sqlite_adapter.py (swappable, business-data adapter)
AND core/auth/database.py (fixed, non-adapter security infrastructure)
-- genuinely different purposes at the architecture level, which is why
they stay two separate files, not one merged module. But the exact
mechanical act of opening a connection was, before this, identical code
duplicated in both places -- real DRY territory (same KNOWLEDGE, not
just similar syntax): if every connection ever needed an added pragma
(e.g. foreign_keys = ON), it would be easy to update one file and
forget the other. This is that one shared mechanical piece, extracted,
without collapsing the real separation between the two callers.
"""

import sqlite3
from pathlib import Path


def open_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
