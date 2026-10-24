"""
dialect.py  (rendering a neutral schema as one engine's SQL)

Why this exists now and not before. An earlier note in this project
said plainly that a dialect abstraction with one implementation would
be the speculative abstraction its own rules forbid, and that the seam
should be cut when a second engine arrived. It has. Two engines now
render the same declarations and disagree about almost every detail,
which is the "something real to factor out" that the silos package
docstring was waiting for.

WHERE they disagree, and none of it is cosmetic:

  - identifier quoting. PostgreSQL uses double quotes; MariaDB uses
    backticks, and its double quotes mean a string literal unless
    ANSI_QUOTES is set. The same DDL sent to the wrong engine is not
    an error, it is a table with a column whose name is a string.
  - TEXT. PostgreSQL's TEXT is unbounded and idiomatic. MariaDB has
    VARCHAR(n) and TEXT, and they are genuinely different: VARCHAR can
    be indexed whole, TEXT needs a prefix length. A declared length
    should become VARCHAR there and is simply ignored by PostgreSQL.
  - BOOLEAN. PostgreSQL has a real one. MariaDB's BOOLEAN is an alias
    for TINYINT(1), so a consumer reads 0 and 1 rather than false and
    true -- a difference worth preserving rather than papering over,
    because a consumer of the real thing would meet it.
  - timestamps. PostgreSQL's TIMESTAMPTZ keeps the offset. MariaDB's
    DATETIME does not, and its TIMESTAMP silently converts through the
    session time zone and has a 2038 limit. DATETIME is the honest
    choice there, and the lost offset is a real property of the
    system, not a defect in the rendering.

The rendering is pure. Nothing here connects to anything. A dialect
turns declarations into strings; the silos execute them. That is what
lets every statement in this file be tested without a server, and then
separately proved valid by executing it against a real one.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from simulator.schema import Column, ColumnType, Identifier, Table


class SqlDialect(ABC):
    """How one engine spells a schema."""

    #: Matches the silo kind this dialect belongs to.
    kind: ClassVar[str]

    #: The character pair used to quote an identifier.
    quote_character: ClassVar[str]

    #: Which columns of information_schema.columns this engine needs
    #: read back in order to answer column_type_for. Declared per
    #: dialect because the catalogue is not the same everywhere:
    #: `column_type` is MySQL's, and asking PostgreSQL for it fails
    #: outright rather than returning null.
    catalogue_fields: ClassVar[tuple[str, ...]] = (
        "column_name", "data_type", "is_nullable",
        "character_maximum_length", "numeric_precision", "numeric_scale",
    )

    #: The placeholder a parameterised statement uses. psycopg and
    #: pymysql both accept %s; it is a property of the driver rather
    #: than the engine, which is why it is stated rather than assumed.
    placeholder: ClassVar[str] = "%s"

    def quote(self, identifier: str) -> str:
        """Quote an identifier.

        Validates as well as quotes, which is the whole point. Every
        name that reaches SQL in this codebase passes through here --
        it is the only place an identifier is interpolated -- so
        checking here is checking everywhere. Typing the parameter as
        Identifier instead was tried first: mypy correctly named all
        forty-one call sites, but the fix at each was to construct one,
        which puts the guarantee in forty-one places rather than in a
        choke point that cannot be gone around.

        The check is what stops a name being SQL. Placeholders stand
        for values and never for identifiers, so names are interpolated
        by hand -- and RenameColumn took its `new_name` straight from a
        pack file or the console prompt, so `to: 'x"; DROP TABLE users;
        --'` produced exactly the statement it looks like. Quoting
        alone would not have helped; the check is what does.

        Quoting is still needed on top, because a column legitimately
        named `order` or `group` is a reserved word on both engines -- but they are quoted anyway, because a
        column legitimately named `order` or `group` is a reserved word
        on both engines and would otherwise be a syntax error a pack
        author could not diagnose.
        """
        return f"{self.quote_character}{Identifier(identifier)}{self.quote_character}"

    @abstractmethod
    def render_type(self, column: Column) -> str:
        """This engine's spelling of a column's declared type."""

    # -- reading the catalogue back -----------------------------------
    #
    # information_schema on the two server engines; SQLite has none and
    # answers through PRAGMA instead, so how to ASK is the dialect's,
    # and what to do with the answer stays in relational.py. `fetch`
    # runs a statement with its parameters and returns the rows.

    def table_names(self, fetch: Any, scope: str) -> list[str]:
        """Every base table, sorted, the simulator's own included."""
        return [str(row[0]) for row in fetch(
            "SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = {self.placeholder} AND table_type = 'BASE TABLE' "
            "ORDER BY table_name", (scope,))]

    def catalogue_rows(self, fetch: Any, scope: str, table: str) -> list[dict[str, Any]]:
        """A table's columns in storage order, each a dict keyed by
        `catalogue_fields` -- what column_type_for and the rest read."""
        return [dict(zip(self.catalogue_fields, row, strict=True)) for row in fetch(
            f"SELECT {', '.join(self.catalogue_fields)} FROM information_schema.columns "
            f"WHERE table_schema = {self.placeholder} AND table_name = {self.placeholder} "
            "ORDER BY ordinal_position", (scope, table))]

    def primary_keys(self, fetch: Any, scope: str) -> dict[str, str]:
        """Each table's primary key column, where it has a single one."""
        return {str(table): str(column) for table, column in fetch(
            "SELECT t.table_name, k.column_name "
            "FROM information_schema.table_constraints t "
            "JOIN information_schema.key_column_usage k "
            "  ON k.constraint_name = t.constraint_name "
            " AND k.table_schema = t.table_schema "
            " AND k.table_name = t.table_name "
            f"WHERE t.table_schema = {self.placeholder} AND t.constraint_type = 'PRIMARY KEY'",
            (scope,))}

    def greatest(self, left: str, right: str) -> str:
        """The larger of two expressions: GREATEST on both server engines."""
        return f"GREATEST({left}, {right})"

    def render_column(self, column: Column) -> str:
        parts = [self.quote(column.name), self.render_type(column)]
        if column.primary_key:
            parts.append("PRIMARY KEY")
        elif not column.nullable:
            parts.append("NOT NULL")
        return " ".join(parts)

    def create_table(self, table: Table) -> str:
        body = ",\n  ".join(self.render_column(column) for column in table.columns)
        return f"CREATE TABLE {self.quote(table.name)} (\n  {body}\n)"

    def insert(self, table_name: str, columns: Sequence[str]) -> str:
        """A parameterised INSERT. Values are bound, never interpolated."""
        if not columns:
            raise ValueError(f"cannot insert into {table_name!r} with no columns")
        names = ", ".join(self.quote(name) for name in columns)
        placeholders = ", ".join(self.placeholder for _ in columns)
        return f"INSERT INTO {self.quote(table_name)} ({names}) VALUES ({placeholders})"

    @abstractmethod
    def create_database(self, name: str) -> str:
        """Create a database inside this engine's instance."""

    def declared_length_for(self, reported: Mapping[str, Any]) -> int | None:
        """The length a pack declared, if this engine kept it.

        Not the same as character_maximum_length, and the difference
        matters. A schema read back is what the engine holds, which is
        not always what was declared -- and where those differ, the
        difference is informative rather than a defect to paper over.
        """
        return None

    @abstractmethod
    def column_type_for(self, reported: Mapping[str, Any]) -> ColumnType:
        """Read an engine's own type name back as a declared type.

        The inverse of render_type, and needed by anything that has to
        learn a schema from a live database rather than be told it --
        a second process attaching to a running world, and eventually
        a verification that compares types rather than just names.

        `reported` is a row of information_schema.columns. It is passed
        whole rather than as a type string, because one engine cannot
        answer from the type name alone: MariaDB reports BOOLEAN as
        `tinyint`, and only `column_type` being `tinyint(1)` says it is
        not a small integer.
        """

    # -- changing a table that already exists ------------------------
    #
    # The engines agree about adding, dropping and renaming, and
    # disagree completely about retyping -- which is the one that
    # matters most, since it is on Foundry's own breaking-change list.

    def add_column(self, table_name: str, column: Column) -> str:
        return (f"ALTER TABLE {self.quote(table_name)} "
                f"ADD COLUMN {self.render_column(column)}")

    def drop_column(self, table_name: str, column_name: str) -> str:
        return (f"ALTER TABLE {self.quote(table_name)} "
                f"DROP COLUMN {self.quote(column_name)}")

    def rename_column(self, table_name: str, old_name: str, new_name: str) -> str:
        return (f"ALTER TABLE {self.quote(table_name)} "
                f"RENAME COLUMN {self.quote(old_name)} TO {self.quote(new_name)}")

    def rename_table(self, old_name: str, new_name: str) -> str:
        return f"ALTER TABLE {self.quote(old_name)} RENAME TO {self.quote(new_name)}"

    def drop_table(self, table_name: str) -> str:
        return f"DROP TABLE {self.quote(table_name)}"

    @abstractmethod
    def change_column_type(self, table_name: str, column: Column) -> str:
        """Retype an existing column, keeping what is already in it."""

    def change_column_type_steps(self, table: Table, column: Column) -> list[str]:
        """The statements that retype `column` of `table`, in order.

        One, on the server engines. A list because SQLite has no way to
        retype a column in place and documents a rebuild instead.
        """
        return [self.change_column_type(table.name, column)]

    def rescale_column(self, table_name: str, column_name: str) -> str:
        """Multiply every value in a column by a bound parameter.

        The one change that alters no structure at all -- every read
        still succeeds, every type still checks, and the meaning has
        moved. Dollars becoming cents is a real migration that real
        systems perform.
        """
        quoted = self.quote(column_name)
        return (f"UPDATE {self.quote(table_name)} SET {quoted} = {quoted} * "
                f"{self.placeholder} WHERE {quoted} IS NOT NULL")


class PostgresDialect(SqlDialect):
    kind: ClassVar[str] = "postgresql"
    quote_character: ClassVar[str] = '"'

    def render_type(self, column: Column) -> str:
        match column.type:
            case ColumnType.TEXT:
                # Length is deliberately ignored. PostgreSQL's TEXT is
                # unbounded, has no performance cost against VARCHAR(n),
                # and is what its own documentation recommends; honouring
                # a length here would add a constraint the real system
                # would not have.
                return "TEXT"
            case ColumnType.INTEGER:
                return "INTEGER"
            case ColumnType.BIGINT:
                return "BIGINT"
            case ColumnType.DECIMAL:
                return f"NUMERIC({column.precision}, {column.scale})"
            case ColumnType.BOOLEAN:
                return "BOOLEAN"
            case ColumnType.DATE:
                return "DATE"
            case ColumnType.TIMESTAMP:
                # With the offset kept, which is the whole reason to
                # prefer it over TIMESTAMP WITHOUT TIME ZONE.
                return "TIMESTAMPTZ"
        raise ValueError(f"unhandled column type {column.type}")

    def create_database(self, name: str) -> str:
        return f"CREATE DATABASE {self.quote(name)}"

    def column_type_for(self, reported: Mapping[str, Any]) -> ColumnType:
        # Measured against a real instance rather than taken from the
        # documentation: these are the exact strings PostgreSQL 16
        # reports for every type this project declares.
        name = str(reported["data_type"]).lower()
        mapping = {
            "text": ColumnType.TEXT,
            "character varying": ColumnType.TEXT,
            "integer": ColumnType.INTEGER,
            "bigint": ColumnType.BIGINT,
            "numeric": ColumnType.DECIMAL,
            "boolean": ColumnType.BOOLEAN,
            "date": ColumnType.DATE,
            "timestamp with time zone": ColumnType.TIMESTAMP,
            "timestamp without time zone": ColumnType.TIMESTAMP,
        }
        if name not in mapping:
            raise ValueError(f"PostgreSQL type {name!r} has no declared equivalent")
        return mapping[name]

    def change_column_type(self, table_name: str, column: Column) -> str:
        # USING is not optional here. PostgreSQL will not implicitly
        # convert between most types, so a plain ALTER ... Type fails
        # with "column cannot be cast automatically" -- and the whole
        # point of retyping in a drift test is that the data already
        # in the column comes along.
        rendered = self.render_type(column)
        # And nullability, which ALTER ... TYPE leaves alone: a migration
        # saying `nullable` stopped the world on its own schema check
        # (found in review, 21 October). Unsaid, the builder carries the
        # column's own over, so this restates what it already was.
        return (f"ALTER TABLE {self.quote(table_name)} "
                f"ALTER COLUMN {self.quote(column.name)} TYPE {rendered} "
                f"USING {self.quote(column.name)}::{rendered}, "
                f"ALTER COLUMN {self.quote(column.name)} "
                + ("DROP NOT NULL" if column.nullable else "SET NOT NULL"))


class MariaDbDialect(SqlDialect):
    kind: ClassVar[str] = "mariadb"
    quote_character: ClassVar[str] = "`"
    # Plus column_type, which is the only way to tell a BOOLEAN from a
    # small integer here -- see column_type_for.
    catalogue_fields: ClassVar[tuple[str, ...]] = (
        *SqlDialect.catalogue_fields, "column_type",
    )

    def render_type(self, column: Column) -> str:
        match column.type:
            case ColumnType.TEXT:
                # A declared length becomes VARCHAR, which can be
                # indexed whole; without one, TEXT, which cannot. That
                # difference is real on this engine and is why the
                # neutral declaration carries an optional length at all.
                return f"VARCHAR({column.length})" if column.length else "TEXT"
            case ColumnType.INTEGER:
                return "INT"
            case ColumnType.BIGINT:
                return "BIGINT"
            case ColumnType.DECIMAL:
                return f"DECIMAL({column.precision}, {column.scale})"
            case ColumnType.BOOLEAN:
                # An alias for TINYINT(1) here, so a consumer reads 0
                # and 1 rather than false and true. Preserved rather
                # than papered over: a consumer of the real thing meets
                # exactly this.
                return "BOOLEAN"
            case ColumnType.DATE:
                return "DATE"
            case ColumnType.TIMESTAMP:
                # DATETIME rather than TIMESTAMP. MariaDB's TIMESTAMP
                # converts through the session time zone on the way in
                # and out, and runs out in 2038. DATETIME does neither,
                # and the offset it cannot keep is a real property of
                # the system rather than a defect here.
                return "DATETIME"
        raise ValueError(f"unhandled column type {column.type}")

    def create_table(self, table: Table) -> str:
        # InnoDB and utf8mb4 stated explicitly. Defaults vary by server
        # version and configuration, and the combination that bites is
        # a table created as utf8 (three bytes) which then rejects an
        # emoji in a customer's name -- a genuinely common production
        # failure on this engine.
        return super().create_table(table) + " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"

    def create_database(self, name: str) -> str:
        return f"CREATE DATABASE {self.quote(name)} CHARACTER SET utf8mb4"

    def declared_length_for(self, reported: Mapping[str, Any]) -> int | None:
        # Only for VARCHAR, which is what a declared length renders to
        # here. A TEXT column reports character_maximum_length = 65535
        # -- the type's capacity, not anything a pack asked for -- and
        # reading that back as a declared length would invent a
        # constraint nobody wrote.
        if str(reported["data_type"]).lower() != "varchar":
            return None
        length = reported["character_maximum_length"]
        return int(length) if length else None

    def column_type_for(self, reported: Mapping[str, Any]) -> ColumnType:
        name = str(reported["data_type"]).lower()
        # The reason this takes a whole row. BOOLEAN is an alias for
        # TINYINT(1) here, so `data_type` says `tinyint` for both a
        # boolean and a small integer, and only the full `column_type`
        # tells them apart. Measured: BOOLEAN comes back as
        # data_type='tinyint', column_type='tinyint(1)'.
        if name == "tinyint":
            full = str(reported.get("column_type", "")).lower()
            return ColumnType.BOOLEAN if full.startswith("tinyint(1)") else ColumnType.INTEGER
        mapping = {
            "varchar": ColumnType.TEXT,
            "text": ColumnType.TEXT,
            "longtext": ColumnType.TEXT,
            "int": ColumnType.INTEGER,
            "bigint": ColumnType.BIGINT,
            "decimal": ColumnType.DECIMAL,
            "date": ColumnType.DATE,
            "datetime": ColumnType.TIMESTAMP,
            "timestamp": ColumnType.TIMESTAMP,
        }
        if name not in mapping:
            raise ValueError(f"MariaDB type {name!r} has no declared equivalent")
        return mapping[name]

    def change_column_type(self, table_name: str, column: Column) -> str:
        # Modify column restates the whole definition, so nullability
        # has to be repeated or it is silently dropped -- a NOT NULL
        # column quietly becoming nullable is a change nobody asked
        # for, arriving inside a change they did.
        definition = f"{self.quote(column.name)} {self.render_type(column)}"
        if not column.nullable and not column.primary_key:
            definition += " NOT NULL"
        return f"ALTER TABLE {self.quote(table_name)} MODIFY COLUMN {definition}"


class SqliteDialect(SqlDialect):
    """SQLite, as an ordinary application's database layer writes it.

    The owner's choice (24 October): ordinary tables, not STRICT ones,
    because that is what the software small businesses run creates.
    SQLite then does what it documents (sqlite.org/datatype3.html), and
    a consumer meets it:

      - a declared type is a hint. "VARCHAR(255)" has TEXT affinity and
        "numeric arguments in parentheses ... are ignored"; DECIMAL,
        BOOLEAN, DATE and DATETIME have NUMERIC affinity.
      - money is a number of the engine's choosing: "When text data is
        inserted into a NUMERIC column, the storage class of the text is
        converted to INTEGER or REAL" -- so 19.99 is a double, and 20.00
        is the integer 20.
      - "SQLite does not have a separate Boolean storage class. Instead,
        Boolean values are stored as integers 0 (false) and 1 (true)."
      - a date or time is "TEXT as ISO8601 strings", which is what an
        application writes (the session does it; silos/sqlite.py).

    The names are what an application's layer declares -- Django's
    SQLite backend writes `varchar(n)`, `integer`, `bigint`, `decimal`,
    `bool`, `date` and `datetime` -- so they are read back as the pack
    declared them: SQLite keeps the declared text, which is the only
    record of what was meant.

    There are no accounts and no databases. The file is the database,
    made by the silo; whoever can read the file reads every table.
    """

    kind: ClassVar[str] = "sqlite"
    quote_character: ClassVar[str] = '"'
    #: sqlite3's qmark style; it does not take %s.
    placeholder: ClassVar[str] = "?"
    catalogue_fields: ClassVar[tuple[str, ...]] = (
        "column_name", "data_type", "is_nullable",
        "character_maximum_length", "numeric_precision", "numeric_scale",
    )

    def render_type(self, column: Column) -> str:
        match column.type:
            case ColumnType.TEXT:
                return f"VARCHAR({column.length})" if column.length else "TEXT"
            case ColumnType.INTEGER:
                return "INTEGER"
            case ColumnType.BIGINT:
                return "BIGINT"
            case ColumnType.DECIMAL:
                return f"DECIMAL({column.precision}, {column.scale})"
            case ColumnType.BOOLEAN:
                return "BOOL"
            case ColumnType.DATE:
                return "DATE"
            case ColumnType.TIMESTAMP:
                return "DATETIME"
        raise ValueError(f"unhandled column type {column.type}")

    def create_database(self, name: str) -> str:
        """Nothing to run: the file is the database, and the silo made it."""
        return ""

    def table_names(self, fetch: Any, scope: str) -> list[str]:
        # sqlite_% are SQLite's own (sqlite_sequence, sqlite_stat1).
        return [str(row[0]) for row in fetch(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name", ())]

    def catalogue_rows(self, fetch: Any, scope: str, table: str) -> list[dict[str, Any]]:
        # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk --
        # in storage order, the declared type as it was written.
        rows = []
        for _cid, name, declared, notnull, _default, pk in fetch(
                f"PRAGMA table_info({self.quote(table)})", ()):
            numbers = _bracketed(declared)
            base = _base(declared)
            rows.append({
                "column_name": name,
                "data_type": declared,
                # A PRIMARY KEY column in an ordinary table may hold NULL
                # (a documented SQLite quirk), so it reports notnull = 0;
                # it is no more nullable for that than on the servers.
                "is_nullable": "NO" if (notnull or pk) else "YES",
                "character_maximum_length": numbers[0] if base == "VARCHAR" else None,
                "numeric_precision": numbers[0] if base in ("DECIMAL", "NUMERIC") else None,
                "numeric_scale": numbers[1] if base in ("DECIMAL", "NUMERIC") else None,
            })
        return rows

    def primary_keys(self, fetch: Any, scope: str) -> dict[str, str]:
        keys = {}
        for table in self.table_names(fetch, scope):
            named = [row[1] for row in fetch(f"PRAGMA table_info({self.quote(table)})", ()) if row[5]]
            if len(named) == 1:
                keys[table] = str(named[0])
        return keys

    def greatest(self, left: str, right: str) -> str:
        # SQLite's scalar max() takes two or more arguments; GREATEST is
        # not a function there.
        return f"max({left}, {right})"

    def declared_length_for(self, reported: Mapping[str, Any]) -> int | None:
        length = reported.get("character_maximum_length")
        return int(length) if length else None

    def column_type_for(self, reported: Mapping[str, Any]) -> ColumnType:
        base = _base(str(reported["data_type"]))
        mapping = {
            "TEXT": ColumnType.TEXT, "VARCHAR": ColumnType.TEXT,
            "INTEGER": ColumnType.INTEGER, "INT": ColumnType.INTEGER,
            "BIGINT": ColumnType.BIGINT,
            "DECIMAL": ColumnType.DECIMAL, "NUMERIC": ColumnType.DECIMAL,
            "BOOL": ColumnType.BOOLEAN, "BOOLEAN": ColumnType.BOOLEAN,
            "DATE": ColumnType.DATE,
            "DATETIME": ColumnType.TIMESTAMP, "TIMESTAMP": ColumnType.TIMESTAMP,
        }
        if base not in mapping:
            raise ValueError(f"SQLite declared type {reported['data_type']!r} has no declared equivalent")
        return mapping[base]

    def change_column_type(self, table_name: str, column: Column) -> str:
        raise NotImplementedError(
            "SQLite cannot retype a column in place; use change_column_type_steps")

    def change_column_type_steps(self, table: Table, column: Column) -> list[str]:
        """SQLite's documented rebuild (sqlite.org/lang_altertable.html,
        "Making Other Kinds Of Table Schema Changes"): "the full 12-step
        procedure ... is appropriate for ... changing the datatype for a
        column". What applies to a table with no indexes, triggers,
        views or foreign keys of its own, which is every table a pack
        declares: create the new table under another name, copy the
        rows, drop the old one, rename the new one into place -- in that
        order, because renaming the old one first "might corrupt
        references to that table". The caller holds them in one
        transaction, as step 2 says.

        Values are copied as they are. SQLite converts by the new
        column's affinity as each row is inserted, which is what a real
        application's migration gets too.
        """
        revised = Table(name=f"_new_{table.name}", columns=tuple(
            column if c.name == column.name else c for c in table.columns))
        names = ", ".join(self.quote(c.name) for c in table.columns)
        return [
            self.create_table(revised),
            f"INSERT INTO {self.quote(revised.name)} ({names}) SELECT {names} FROM {self.quote(table.name)}",
            self.drop_table(table.name),
            self.rename_table(revised.name, table.name),
        ]


def _base(declared: str) -> str:
    """A declared type's name without its bracketed numbers, upper-cased."""
    return declared.split("(", 1)[0].strip().upper()


def _bracketed(declared: str) -> tuple[int | None, int | None]:
    """The numbers in a declared type's brackets: VARCHAR(40) -> (40,
    None), DECIMAL(10, 2) -> (10, 2). SQLite ignores them; they are the
    only record of what the application declared."""
    if "(" not in declared:
        return None, None
    inside = declared.split("(", 1)[1].rstrip(") ").split(",")
    numbers = [int(part) for part in (p.strip() for p in inside) if part.isdigit()]
    return (numbers[0] if numbers else None, numbers[1] if len(numbers) > 1 else None)


#: By silo kind, so a caller with a silo can find its dialect without
#: a conditional. Explicit rather than discovered: two entries do not
#: need a registry mechanism, and a greppable dict is what a reader
#: wants when a kind has no dialect.
DIALECTS: dict[str, SqlDialect] = {
    PostgresDialect.kind: PostgresDialect(),
    MariaDbDialect.kind: MariaDbDialect(),
    SqliteDialect.kind: SqliteDialect(),
}


def dialect_for(kind: str) -> SqlDialect:
    if kind not in DIALECTS:
        raise KeyError(
            f"no SQL dialect for silo kind {kind!r}; relational kinds are {sorted(DIALECTS)}"
        )
    return DIALECTS[kind]


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section
# whenever something genuinely open, deferred, or rejected comes up here.
# =============================================================================
#
# RESOLVED (kept for history): this module exists because a second engine now
# does. An earlier note said a dialect abstraction with one implementation
# would be speculative and that the seam should be cut when a second arrived.
# The silos package docstring said each module would own its own SQL "until
# there is something real to factor out"; two engines rendering the same
# declarations is that, and the docstring has been updated rather than left
# contradicting this file.
#
# RESOLVED: identifiers are quoted even though schema.py already restricts them
# to plain Python identifiers, so there is nothing to escape. A column named
# `order` or `group` is a reserved word on both engines and would otherwise be
# a syntax error a pack author could not diagnose from the message.
#
# RESOLVED: MariaDB gets DATETIME rather than TIMESTAMP, and the lost offset is
# deliberate. TIMESTAMP converts through the session time zone in both
# directions and expires in 2038; DATETIME is the honest rendering, and a
# consumer meeting a timestamp without an offset is meeting the real system.
#
# RESOLVED: a drop_table() renderer was written here and deleted before commit
# -- nothing called it, and the drift operations that will are not in this
# repository yet.
#
# RESOLVED: PostgreSQL never reports a declared length, because render_type
# deliberately ignores one -- its TEXT is unbounded and that was a considered
# choice. So a schema read back from PostgreSQL has length=None on every text
# column, whatever the pack declared. That asymmetry is real and is left
# visible: a read-back schema describes what the engine holds, not what was
# asked for, and the two differing is information.
#
# RESOLVED: column_type_for takes a whole information_schema row rather than a
# type name, because MariaDB cannot answer from the name alone -- BOOLEAN is an
# alias for TINYINT(1), so `data_type` is `tinyint` for both a boolean and a
# small integer and only `column_type` distinguishes them. Every mapping here
# was measured against a real instance rather than taken from documentation.
#
# RESOLVED (24 October): the SQLite dialect exists, and the design question
# this note deferred was answered with the owner rather than by analogy:
# ordinary tables, as the software small businesses run creates them, with
# SQLite's affinity left to do what it documents. See SqliteDialect.
#
# RESOLVED: ALTER rendering exists, and the engines diverge exactly where
# predicted. PostgreSQL needs ALTER ... Type ... USING, because it refuses to
# convert between most types implicitly. MariaDB needs Modify column with the
# whole definition restated, which means nullability has to be repeated or a
# NOT NULL column silently becomes nullable inside a change nobody asked for.
