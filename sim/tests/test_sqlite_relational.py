"""A SQLite silo that holds tables (24 October): provisioned, written to,
read back and drifted through the same relational layer as the servers,
and storing what it is given as SQLite does -- by affinity, the way an
ordinary application's file holds it (dialect.py, SqliteDialect).

No server is needed, so these run everywhere, as root too.
"""

import sqlite3
import textwrap
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from simulator import runner
from simulator.dialect import dialect_for
from simulator.drift import (
    AddColumn,
    ChangeColumnType,
    DropColumn,
    RenameColumn,
    RenameTable,
    RescaleColumn,
    history,
)
from simulator.relational import (
    adjust_column,
    all_table_names,
    apply_and_verify,
    catalogue_columns,
    count_rows,
    fetch_all,
    fetch_rows_by_key,
    insert_rows,
    read_schema,
    update_columns,
    verify_schema,
)
from simulator.schema import Column, ColumnType, Schema, Table
from simulator.silo import SiloError
from simulator.silos.sqlite import SqliteSilo, as_written
from simulator.spec import PackError, load_pack

PARTS = Table(name="parts", columns=(
    Column("part_id", ColumnType.TEXT, length=32, primary_key=True, nullable=False),
    Column("description", ColumnType.TEXT, length=200, nullable=False),
    Column("unit_cost", ColumnType.DECIMAL, precision=10, scale=2, nullable=False),
    Column("on_hand", ColumnType.INTEGER, nullable=False),
    Column("stocked", ColumnType.BOOLEAN, nullable=False),
    Column("counted_at", ColumnType.TIMESTAMP),
    Column("first_stocked", ColumnType.DATE),
))
SCHEMA = Schema(tables=(PARTS,))

ROWS = [
    {"part_id": "P-1", "description": "Compression elbow", "unit_cost": Decimal("19.99"),
     "on_hand": 12, "stocked": True, "counted_at": datetime(2026, 10, 24, 9, 30, tzinfo=UTC),
     "first_stocked": date(2026, 1, 2)},
    {"part_id": "P-2", "description": "Thermostatic valve", "unit_cost": Decimal("20.00"),
     "on_hand": 0, "stocked": False, "counted_at": None, "first_stocked": None},
]


@pytest.fixture
def silo(tmp_path):
    made = SqliteSilo(name="parts_desk", data_dir=tmp_path, database="parts")
    made.create()
    apply_and_verify(made, "parts", SCHEMA)
    return made


def raw(silo, statement):
    connection = sqlite3.connect(f"file:{silo.path}?mode=ro", uri=True)
    try:
        return connection.execute(statement).fetchall()
    finally:
        connection.close()


# -- the file is the database ----------------------------------------

def test_the_file_is_named_after_its_database(silo):
    assert silo.path.name == "parts.db"
    assert silo.connection().details == {"path": str(silo.path), "database": "parts"}


def test_it_holds_no_other_database(silo):
    with pytest.raises(SiloError, match="holds no database called 'books'"), silo.connect("books"):
        pass


def test_the_schema_lands_as_declared_and_reads_back_as_declared(silo):
    # SQLite keeps the declared type's text, the only record of what was
    # meant: VARCHAR(32), DECIMAL(10, 2), BOOL and DATETIME come back as
    # the pack's text, decimal, boolean and timestamp.
    assert read_schema(silo, "parts") == Schema(tables=(Table(name="parts", columns=(
        Column("part_id", ColumnType.TEXT, length=32, primary_key=True, nullable=False),
        Column("description", ColumnType.TEXT, length=200, nullable=False),
        Column("unit_cost", ColumnType.DECIMAL, precision=10, scale=2, nullable=False),
        Column("on_hand", ColumnType.INTEGER, nullable=False),
        Column("stocked", ColumnType.BOOLEAN, nullable=False),
        Column("counted_at", ColumnType.TIMESTAMP),
        Column("first_stocked", ColumnType.DATE),
    )),))
    assert raw(silo, "SELECT sql FROM sqlite_master WHERE name = 'parts'")[0][0].count("DECIMAL(10, 2)") == 1


def test_verification_fails_on_a_column_the_schema_does_not_have(silo):
    wider = Schema(tables=(Table(name="parts", columns=(*PARTS.columns, Column("bin", ColumnType.TEXT))),))

    with pytest.raises(SiloError, match="differs"):
        verify_schema(silo, "parts", wider)


def test_its_own_tables_are_not_the_business_s(silo):
    # sqlite_sequence appears with the first AUTOINCREMENT table; it is
    # SQLite's, not the application's.
    with silo.connect("parts") as connection:
        connection.execute("CREATE TABLE seq (n INTEGER PRIMARY KEY AUTOINCREMENT)")
    assert "sqlite_sequence" in [r[0] for r in raw(silo, "SELECT name FROM sqlite_master")]

    assert all_table_names(silo, "parts") == ["parts", "seq"]
    assert catalogue_columns(silo, "parts", "parts") == [c.name for c in PARTS.columns]


# -- stored as SQLite stores it --------------------------------------

def test_values_are_stored_as_an_ordinary_application_s_file_holds_them(silo):
    insert_rows(silo, "parts", PARTS, ROWS)

    stored = raw(silo, "SELECT unit_cost, typeof(unit_cost), stocked, typeof(stocked), "
                       "counted_at, first_stocked FROM parts ORDER BY part_id")

    # sqlite.org/datatype3.html: text in a NUMERIC column becomes "INTEGER
    # or REAL", the integer when it can -- so 20.00 is 20; booleans are
    # "integers 0 (false) and 1 (true)"; times are "TEXT as ISO8601".
    assert stored == [
        (19.99, "real", 1, "integer", "2026-10-24 09:30:00", "2026-01-02"),
        (20, "integer", 0, "integer", None, None),
    ]


def test_a_timestamp_is_written_in_utc_without_its_offset():
    eastern = datetime(2026, 10, 24, 5, 30, tzinfo=timezone(timedelta(hours=-4)))

    assert as_written(eastern) == "2026-10-24 09:30:00"
    assert as_written(Decimal("0.10")) == "0.10"
    assert as_written(True) is True


# -- the relational layer, unchanged above it ------------------------

def test_a_session_commits_its_writes_as_one_and_a_failure_as_none(silo):
    with silo.session("parts"):
        insert_rows(silo, "parts", PARTS, ROWS[:1])
        # Not yet visible to another reader: one transaction.
        assert raw(silo, "SELECT count(*) FROM parts")[0][0] == 0
    assert count_rows(silo, "parts", "parts") == 1

    with pytest.raises(sqlite3.IntegrityError), silo.session("parts"):
        insert_rows(silo, "parts", PARTS, ROWS[1:])
        insert_rows(silo, "parts", PARTS, ROWS[1:])   # the same key again
    assert count_rows(silo, "parts", "parts") == 1


def test_adjusting_stock_is_clamped_at_the_floor_in_the_database(silo):
    insert_rows(silo, "parts", PARTS, ROWS)

    assert adjust_column(silo, "parts", PARTS, "on_hand", -50, {"part_id": "P-1"}, floor=0) == 1

    assert fetch_all(silo, "parts", "SELECT on_hand FROM parts WHERE part_id = 'P-1'") == [(0,)]


def test_updating_and_fetching_by_key(silo):
    insert_rows(silo, "parts", PARTS, ROWS)

    assert update_columns(silo, "parts", PARTS, {"on_hand": 4, "stocked": True}, {"part_id": "P-2"}) == 1

    found = fetch_rows_by_key(silo, "parts", PARTS, "part_id", ["P-2"])
    assert found["P-2"]["on_hand"] == 4 and found["P-2"]["stocked"] == 1


# -- drift ------------------------------------------------------------

AT = datetime(2026, 10, 24, tzinfo=UTC)


def test_a_retype_rebuilds_the_table_keeping_every_row(silo):
    insert_rows(silo, "parts", PARTS, ROWS)

    revised = ChangeColumnType("parts", "on_hand", Column("on_hand", ColumnType.BIGINT, nullable=False)) \
        .apply(silo, "parts", SCHEMA, AT)

    assert read_schema(silo, "parts") == revised
    assert fetch_all(silo, "parts", "SELECT part_id, on_hand FROM parts ORDER BY part_id") == [("P-1", 12), ("P-2", 0)]
    # Nothing of the rebuild left behind.
    assert all_table_names(silo, "parts") == ["_simulator_migrations", "parts"]


def test_a_retype_is_one_transaction(silo):
    # sqlite.org/lang_altertable.html, step 2: "Start a transaction". A
    # rebuild that failed after creating its new table must leave none.
    insert_rows(silo, "parts", PARTS, ROWS)
    steps = dialect_for("sqlite").change_column_type_steps(
        PARTS, Column("on_hand", ColumnType.BIGINT, nullable=False))

    with pytest.raises(sqlite3.OperationalError), silo.connect("parts") as connection:
        with connection.cursor() as cursor:
            cursor.execute(steps[0])
            cursor.execute(steps[1])
            cursor.execute("SELECT * FROM no_such_table")

    assert all_table_names(silo, "parts") == ["parts"]


def test_retyping_text_that_holds_money_into_a_decimal_converts_it(silo):
    # The affinity applies as each row is copied: what a real application's
    # migration gets.
    table = Table(name="parts", columns=(*PARTS.columns, Column("list_price", ColumnType.TEXT)))
    schema = AddColumn("parts", Column("list_price", ColumnType.TEXT)).apply(silo, "parts", SCHEMA, AT)
    insert_rows(silo, "parts", table, [{**ROWS[0], "list_price": "24.50"}])

    ChangeColumnType("parts", "list_price", Column("list_price", ColumnType.DECIMAL, precision=10, scale=2)) \
        .apply(silo, "parts", schema, AT)

    assert raw(silo, "SELECT list_price, typeof(list_price) FROM parts") == [(24.5, "real")]


@pytest.mark.parametrize("change", [
    AddColumn("parts", Column("bin", ColumnType.TEXT, length=8)),
    DropColumn("parts", "first_stocked"),
    RenameColumn("parts", "on_hand", "quantity"),
    RenameTable("parts", "stock_items"),
])
def test_the_other_changes_take_effect_and_are_recorded(silo, change):
    insert_rows(silo, "parts", PARTS, ROWS)

    revised = change.apply(silo, "parts", SCHEMA, AT)

    assert read_schema(silo, "parts") == revised
    assert [entry["operation"] for entry in history(silo, "parts")] == [type(change).__name__]


def test_rescaling_moves_the_meaning_and_nothing_else(silo):
    insert_rows(silo, "parts", PARTS, ROWS)

    RescaleColumn("parts", "on_hand", Decimal(100)).apply(silo, "parts", SCHEMA, AT)

    assert fetch_all(silo, "parts", "SELECT on_hand FROM parts ORDER BY part_id") == [(1200,), (0,)]


# -- a pack, and a world built from it --------------------------------

PACK = textwrap.dedent("""
    pack: parts_only
    description: A back office with a desktop parts application.

    silos:
      parts_desk: {kind: sqlite, database: parts}

    schemas:
      parts_desk:
        tables:
          parts:
            columns:
              part_id:     {type: text, length: 32, primary_key: true, nullable: false}
              description: {type: text, length: 200, nullable: false}
              unit_cost:   {type: decimal, precision: 10, scale: 2, nullable: false}
              on_hand:     {type: integer, nullable: false}

    seed:
      - table: parts_desk.parts
        count: 20
        columns:
          part_id:     {generator: id, prefix: part}
          description: {generator: choice, options: [Elbow, Valve, Washer]}
          unit_cost:   {generator: decimal, min: 1, max: 90, scale: 2}
          on_hand:     {generator: integer, min: 0, max: 40}
    """)


def test_a_world_with_a_sqlite_database_is_built_seeded_and_verified(tmp_path):
    path = tmp_path / "parts.yaml"
    path.write_text(PACK)
    world = runner.build(load_pack(path), tmp_path / "var", seed=7)
    try:
        assert runner.seed(world) == {"parts_desk.parts": 20}
        silo = world.silos["parts_desk"]
        assert silo.path == tmp_path / "var" / "parts_desk" / "parts.db"
        assert count_rows(silo, "parts", "parts") == 20
        assert {t for (t,) in raw(silo, "SELECT DISTINCT typeof(unit_cost) FROM parts")} <= {"real", "integer"}
    finally:
        runner.stop(world)


def test_simulator_verify_checks_it_as_a_consumer_would(tmp_path):
    from simulator.health import _CHECKS

    path = tmp_path / "parts.yaml"
    path.write_text(PACK)
    world = runner.build(load_pack(path), tmp_path / "var", seed=7)
    try:
        runner.seed(world)
        details = world.silos["parts_desk"].connection().details | {"kind": "sqlite"}
        notes = [check("parts_desk", details, tmp_path / "var") for _, check in _CHECKS["sqlite"]]
    finally:
        runner.stop(world)

    assert notes == [None, "1 tables, all populated", None, "DELETE refused, as it should be"]


def test_simulator_verify_notices_a_table_with_no_key(tmp_path):
    # A desktop program's table made without one, as some are: a consumer
    # has nothing to tell its rows apart by, and verify says which.
    from simulator.health import _CHECKS

    path = tmp_path / "parts.yaml"
    path.write_text(PACK)
    world = runner.build(load_pack(path), tmp_path / "var", seed=7)
    try:
        runner.seed(world)
        silo = world.silos["parts_desk"]
        with sqlite3.connect(silo.path) as connection:
            connection.execute("CREATE TABLE notes (body TEXT)")
            connection.execute("INSERT INTO notes VALUES ('reorder washers')")
        details = silo.connection().details | {"kind": "sqlite"}
        [keyed] = [check for name, check in _CHECKS["sqlite"] if name == "every table has a primary key"]
        with pytest.raises(RuntimeError, match=r"no primary key on \['notes'\]"):
            keyed("parts_desk", details, tmp_path / "var")
    finally:
        runner.stop(world)


def test_a_pack_may_not_withhold_a_table_in_a_file(tmp_path):
    path = tmp_path / "parts.yaml"
    path.write_text(PACK.replace("{kind: sqlite, database: parts}",
                                 "{kind: sqlite, database: parts, withheld: [parts]}"))

    with pytest.raises(PackError, match="no account to withhold a table from"):
        load_pack(path)
