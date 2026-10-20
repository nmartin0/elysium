"""
silos.py  (the systems a business runs, before anything is in them)

The shortest section and the first one read, because everything after
it is anchored to a silo name: a schema belongs to one, an emission
writes to one, a migration changes one. Getting a name wrong here
would otherwise surface much later as "no schema is declared for silo
'dispatc'", which names the wrong problem.

What it refuses is a silo declared with a database it cannot hold. A
folder of CSV files has no databases in it, and a pack saying
otherwise is describing a system that does not exist -- so `database`
on a filedrop is an error rather than something quietly ignored. The
list of kinds that CAN hold one is derived from the dialects rather
than written again, because a kind with no dialect cannot have tables
created in it and writing that fact twice is how two lists drift.
"""


from simulator.silos import SILO_TYPES
from simulator.spec.model import SiloSpec
from simulator.spec.schemas import _relational_kinds
from simulator.spec.values import (
    PackError,
    _duration,
    _require_mapping,
    _string,
)


def _load_withheld(raw: object, path: str, kind: str,
                   database: str | None) -> tuple[str, ...]:
    """Tables the consumer accounts may not read.

    A real deployment rarely grants a reporting tool everything --
    payroll and audit tables are the usual exceptions -- and a consumer
    meeting a table it can FIND but cannot select from is a genuine
    production failure. Reproducing it needs a pack to be able to say
    so.

    Whether the named tables exist is checked later, once the schemas
    are loaded: silos are read first, so nothing here knows what tables
    there will be. See _check_withheld_tables.
    """
    if raw is None:
        return ()
    if kind not in _relational_kinds() or database is None:
        raise PackError(
            path, f"a {kind!r} silo has no tables to withhold")
    if not isinstance(raw, list) or not raw:
        raise PackError(f"{path}.withheld", "must be a non-empty list of table names")
    names = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise PackError(f"{path}.withheld", f"{entry!r} is not a table name")
        names.append(entry)
    if len(set(names)) != len(names):
        raise PackError(f"{path}.withheld", "names a table twice")
    return tuple(names)


#: PostgreSQL silo options that write the catalog, which a standby reads
#: from its source and cannot write.
_CATALOG_OPTIONS = frozenset({"row_security", "reader_default_privileges",
                              "reader_statement_timeout_ms",
                              "reader_idle_session_timeout_ms",
                              "reader_idle_in_transaction_timeout_ms"})


def _load_silos(raw: dict) -> dict[str, SiloSpec]:
    if not raw:
        raise PackError("silos", "a pack must declare at least one silo")
    silos = {}
    for name, definition in raw.items():
        path = f"silos.{name}"
        definition = _require_mapping(definition, path)
        kind = _string(definition, "kind", path)
        if kind not in SILO_TYPES:
            raise PackError(path, f"unknown silo kind {kind!r}; available: {sorted(SILO_TYPES)}")
        database = definition.get("database")
        if database is not None:
            if not isinstance(database, str):
                raise PackError(path, "database must be a string")
            if kind not in _relational_kinds():
                raise PackError(
                    path,
                    f"a {kind!r} silo holds no databases; remove `database`"
                )
        options = definition.get("options") or {}
        if not isinstance(options, dict):
            raise PackError(path, "options must be a mapping")
        withheld = _load_withheld(definition.get("withheld"), path, kind, database)
        replicates = definition.get("replicates")
        refresh = 0.0
        replication = str(definition.get("replication", "copy"))
        if replication not in ("copy", "streaming"):
            raise PackError(f"{path}.replication", "must be copy or streaming")
        if replication == "streaming" and replicates is None:
            raise PackError(path, "`replication` only means something with `replicates`")
        if replication == "streaming":
            # A standby is the engine's own: there is no refresh, and
            # PostgreSQL's is the one built (MariaDB's binlog is not).
            if kind != "postgresql":
                raise PackError(f"{path}.replication",
                                f"streaming is built for postgresql, not {kind}")
            if "refresh" in definition:
                raise PackError(f"{path}.refresh",
                                "a streaming replica has no refresh; its lag is replay's")
            # Its catalog is its source's: a standby cannot REVOKE, switch
            # on row security or alter a role, so these would be ignored.
            catalog = sorted(set(options) & _CATALOG_OPTIONS)
            if definition.get("withheld") or catalog:
                raise PackError(path, f"a streaming replica's grants are its source's; declare "
                                      f"{'withheld' if definition.get('withheld') else catalog} "
                                      f"on {replicates!r} instead")
        if replicates is not None and replication == "copy":
            if not isinstance(replicates, str):
                raise PackError(path, "replicates must name a silo")
            if replicates == name:
                raise PackError(path, "a silo cannot be a replica of itself")
            if kind not in _relational_kinds() or database is None:
                raise PackError(
                    path, f"a {kind!r} silo has no tables to replicate into")
            if "refresh" not in definition:
                # Without one the copy would be rebuilt every tick,
                # which is a replica with no lag -- an expensive way of
                # having a second copy of the same answers.
                raise PackError(path, "a replica needs a `refresh` interval")
            refresh = _duration(definition["refresh"], f"{path}.refresh")
            if refresh <= 0:
                raise PackError(f"{path}.refresh", "must be a positive interval")
        elif replicates is None and "refresh" in definition:
            raise PackError(path, "`refresh` only means something with `replicates`")
        if replicates is not None and replication == "streaming":
            if not isinstance(replicates, str) or replicates == name:
                raise PackError(path, "replicates must name another silo")

        silos[name] = SiloSpec(name=name, kind=kind, database=database,
                               options=options, withheld=withheld,
                               replicates=replicates, refresh_seconds=refresh,
                               replication=replication)
    return silos
