"""Roles, where the running application can change them.

WHY THEY MOVE. policy.yaml is read at load and cannot be edited while
the application runs -- short of rewriting a file under /etc, which
fights whatever deployment tooling manages it. Foundry treats roles as
RUNTIME data, administered in Control Panel rather than in files.

POLICY.YAML BECOMES THE BOOTSTRAP, and nothing changes until somebody
edits a role. Until then this store does not exist: loading reads
policy.yaml exactly as before, writes nothing, and a deployment that
never uses role editing never has a roles.db.

THE FIRST EDIT SEEDS IT. From then on the store is authoritative, and a
change to policy.yaml's `roles:` no longer takes effect -- which is why
loading warns, loudly and by name, whenever the two disagree.

WHY LOADING NEVER WRITES. build_generation is "pure with respect to
process state", and that purity is what lets a failed reload leave the
running generation untouched. Seeding here on first load would make
every load a potential write. So reading checks the file EXISTS before
opening it: opening a SQLite database that is not there creates one.

THE SAME SHAPE AS policy.yaml -- {role: {"allowed_actions": [...]}} --
so effective roles pass through the same freeze and the same two
validators whichever source they came from. A role that would be
refused in policy.yaml is refused here.
"""

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema, open_connection

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
    role_name TEXT PRIMARY KEY,
    definition TEXT NOT NULL
);
-- WHEN THE STORE BECAME AUTHORITATIVE. A row here, not "the roles
-- table is non-empty": emptiness would read as "never seeded", and a
-- store somebody emptied would silently hand control back to
-- policy.yaml.
CREATE TABLE IF NOT EXISTS role_store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class RoleStoreUnreadable(RuntimeError):
    """The role store exists and cannot be read.

    ITS OWN TYPE because the remedy is specific and the alternative --
    falling back to policy.yaml -- is the failure being prevented.
    """


class RoleStore:
    """The authoritative roles, once somebody has edited one."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def load(self) -> dict | None:
        """The stored roles, or None if the store has never been seeded.

        NONE MEANS "USE policy.yaml". Checked by the file's EXISTENCE
        before opening it, because opening a SQLite database that is not
        there creates it -- and loading must not write.

        A STORE THAT EXISTS BUT CANNOT BE READ RAISES rather than
        falling back. Falling back to policy.yaml would silently restore
        whatever roles the store had replaced -- possibly grants that
        were deliberately withdrawn.

        READ-ONLY, WHICH IS WHAT MAKES THE PARAGRAPH ABOVE TRUE. It was
        not. `_connection()` goes through `connection_with_schema`,
        which CREATES the tables when they are missing, so a ZERO-BYTE
        roles.db -- a valid SQLite database with no tables -- was given
        a schema, found no `seeded_at`, returned None, and fell back.
        MEASURED: the file grew from 0 to 20,480 bytes merely by being
        loaded.

        THAT IS SEC-19, SURVIVING ITS OWN FIX. The security agent
        raised "a truncated roles.db silently hands authority back to
        policy.yaml". A truncated file does raise. An EMPTY one did
        not, and a zero-byte store is exactly what a full disk, an
        interrupted copy, or a restore that created the file and copied
        nothing leaves behind.
        """
        if not self._db_path.exists():
            return None

        try:
            with open_connection(self._db_path, read_only=True) as conn:
                # AN EMPTY DATABASE IS DAMAGE; A SHARED ONE IS NOT.
                # roles.db holds TWO stores' tables -- the roles and the
                # changes proposed to them -- so a file created by the
                # change store has tables but not ours, and has simply
                # never been seeded. A file with NO tables at all is the
                # zero-byte case: a full disk, an interrupted copy, a
                # restore that made the file and copied nothing.
                #
                # The first version of this raised on both and broke
                # thirteen role-change tests, which was the right
                # failure to have: the legitimate shared-file path is
                # the one that looks like damage from inside one store.
                tables = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                if not tables:
                    raise sqlite3.DatabaseError("the file holds no tables")
                if "role_store_meta" not in tables:
                    return None

                seeded = conn.execute(
                    "SELECT value FROM role_store_meta WHERE key = 'seeded_at'"
                ).fetchone()
                if seeded is None:
                    return None
                rows = conn.execute(
                    "SELECT role_name, definition FROM roles ORDER BY role_name"
                ).fetchall()
        except sqlite3.Error as damaged:
            # NAMED, BECAUSE "no such table: role_store_meta" tells an
            # operator nothing about what to do. The refusal is the
            # point; the message is what makes it actionable.
            raise RoleStoreUnreadable(
                f"{self._db_path} exists but is not a readable role store "
                f"({damaged}). Elysium will NOT fall back to policy.yaml: "
                f"that would silently restore grants this store may have "
                f"deliberately withdrawn.\n"
                f"\n"
                f"A zero-length or truncated file is what a full disk or an "
                f"interrupted copy leaves behind. Restore it from backup, or "
                f"DELETE it to start from policy.yaml deliberately."
            ) from damaged

        return {row["role_name"]: json.loads(row["definition"]) for row in rows}

    def save(self, roles: dict) -> None:
        """Replaces every stored role, and marks the store authoritative.

        ALL OR NOTHING, in one transaction. Roles are validated as a SET
        -- coherence checks look across roles -- so a store holding half
        of an edit would hold a set nobody validated.

        Raw shape in, as policy.yaml writes it: allowed_actions a list.
        """
        with self._connection() as conn:
            conn.execute("DELETE FROM roles")
            conn.executemany(
                "INSERT INTO roles (role_name, definition) VALUES (?, ?)",
                [
                    (name, json.dumps(_raw(definition), sort_keys=True))
                    for name, definition in sorted(roles.items())
                ],
            )
            conn.execute(
                "INSERT OR IGNORE INTO role_store_meta (key, value) "
                "VALUES ('seeded_at', ?)",
                (datetime.now(UTC).isoformat(),),
            )
            conn.commit()


    def unseed(self) -> None:
        """Hands authority back to policy.yaml. FOR ROLLBACK ONLY.

        An approved change that saves the store and then fails to
        reload -- because something ELSE in the configuration broke --
        must leave things exactly as they were. If the store was not
        seeded before, "as they were" means not seeded.
        """
        with self._connection() as conn:
            conn.execute("DELETE FROM roles")
            conn.execute("DELETE FROM role_store_meta WHERE key = 'seeded_at'")
            conn.commit()

def _raw(definition: dict) -> dict:
    """A role definition as policy.yaml would write it.

    Frozen roles carry allowed_actions as a frozenset; stored ones as a
    SORTED list, so the same role always serialises the same way and
    the digest over it is stable.
    """
    raw = dict(definition)
    raw["allowed_actions"] = sorted(definition.get("allowed_actions", []))
    return raw


def canonical(roles: dict) -> str:
    """The roles as one stable string, for the configuration digest.

    WHY THE DIGEST NEEDS THIS. Trigger baselines reset when the digest
    changes, because a count taken under different grants answers a
    different question. The digest hashed policy.yaml's BYTES -- which
    stops seeing grant changes the moment roles live here. So the
    digest now covers the EFFECTIVE roles, which is what actually
    decides what anybody can see.
    """
    return json.dumps(
        {name: _raw(definition) for name, definition in sorted(roles.items())},
        sort_keys=True,
    )
