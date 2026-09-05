"""
Tests for core/mirror/transform.py -- the raw -> clean stage (Phase 3).

The property that matters most here is NOT that casting works (that is
core/ontology/field_types.py's own job, tested there) but that DRIFT is
detected and reported usefully. A column whose real values stopped
matching the ontology means the customer's source system changed
underneath us, and the whole reason this stage exists -- per Foundry's
own guidance -- is to catch that rather than let it become wrong data
in the mirror.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.transform import describe_drift, transform_rows


def test_declared_types_are_cast_to_real_python_types():
    result = transform_rows(
        [{"id": "a1", "balance": "500.0", "count": "3"}],
        ["id", "balance", "count"],
        {"balance": "number", "count": "integer"},
    )

    assert not result.has_drift
    assert result.rows == [{"id": "a1", "balance": 500.0, "count": 3}]
    assert isinstance(result.rows[0]["balance"], float)
    assert isinstance(result.rows[0]["count"], int)


def test_an_undeclared_column_passes_through_as_a_string():
    # The same default the ontology itself applies, so a schema
    # predating field types behaves exactly as before.
    result = transform_rows([{"label": "checking"}], ["label"], {})

    assert not result.has_drift
    assert result.rows == [{"label": "checking"}]


def test_nulls_survive_rather_than_counting_as_drift():
    # A real NULL is not a type error -- treating it as drift would
    # fail syncs on every nullable column.
    result = transform_rows([{"balance": None}], ["balance"], {"balance": "number"})

    assert not result.has_drift
    assert result.rows == [{"balance": None}]


def test_a_value_that_does_not_fit_its_declared_type_is_reported_as_drift():
    result = transform_rows(
        [{"balance": "not-a-number"}], ["balance"], {"balance": "number"}
    )

    assert result.has_drift
    assert len(result.drift) == 1
    assert result.drift[0].column == "balance"
    assert result.drift[0].declared_type == "number"
    assert result.drift[0].example_value == "not-a-number"


def test_drift_is_reported_once_per_column_not_once_per_row():
    # A source column that changed type affects every row. One report
    # naming a real example is the signal; thousands would bury it.
    rows = [{"balance": "bad"} for _ in range(500)]

    result = transform_rows(rows, ["balance"], {"balance": "number"})

    assert len(result.drift) == 1
    assert result.drift[0].row_count_checked == 500


def test_several_drifted_columns_are_all_reported_in_one_pass():
    # Collected rather than raised on the first, so an operator learns
    # about every problem at once instead of one sync at a time.
    result = transform_rows(
        [{"balance": "bad", "count": "also-bad", "name": "fine"}],
        ["balance", "count", "name"],
        {"balance": "number", "count": "integer"},
    )

    assert {d.column for d in result.drift} == {"balance", "count"}


def test_a_drifted_value_is_kept_raw_rather_than_defaulted():
    # Silently substituting a default would destroy the evidence of
    # what actually arrived.
    result = transform_rows([{"balance": "bad"}], ["balance"], {"balance": "number"})

    assert result.rows[0]["balance"] == "bad"


def test_good_rows_alongside_a_bad_one_are_still_cast():
    result = transform_rows(
        [{"balance": "1.5"}, {"balance": "bad"}, {"balance": "2.5"}],
        ["balance"],
        {"balance": "number"},
    )

    assert result.rows[0]["balance"] == 1.5
    assert result.rows[2]["balance"] == 2.5
    assert result.has_drift


def test_the_drift_description_names_what_an_operator_needs():
    # Written for whoever reads a failed sync's output: the table, the
    # column, what was expected, and what actually arrived.
    result = transform_rows([{"balance": "bad"}], ["balance"], {"balance": "number"})

    message = describe_drift("primary_sql", "accounts", result.drift)

    assert "primary_sql.accounts" in message
    assert "balance" in message
    assert "number" in message
    assert "bad" in message


# --- The stage wired into a real sync -----------------------------------


@pytest.fixture
def source_db(tmp_path):
    path = tmp_path / "biz.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE accounts (account_id TEXT PRIMARY KEY, balance TEXT)")
    conn.executemany(
        "INSERT INTO accounts VALUES (?, ?)", [("a1", "500.0"), ("a2", "1000.0")]
    )
    conn.commit()
    conn.close()
    return path


def test_a_real_sync_casts_through_the_transform_stage(tmp_path, source_db):
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source_db})})

    sync.sync_table("p", "accounts", "account_id", ["account_id", "balance"], {"balance": "number"})

    mirrored = sync._catalog.load_table("p.accounts").scan().to_arrow().to_pydict()
    assert mirrored["balance"] == [500.0, 1000.0]


def test_a_real_sync_fails_loudly_on_drift(tmp_path, source_db):
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source_db})})
    sync.sync_table("p", "accounts", "account_id", ["account_id", "balance"], {"balance": "number"})

    # The source system changes underneath us.
    conn = sqlite3.connect(source_db)
    conn.execute("INSERT INTO accounts VALUES ('a3', 'not-a-number')")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="Schema drift"):
        sync.sync_table(
            "p", "accounts", "account_id", ["account_id", "balance"], {"balance": "number"}
        )


def test_the_last_good_mirror_survives_a_drifted_sync(tmp_path, source_db):
    # "Fail loudly, never silently substitute" -- a drifted sync must
    # leave the previous good contents readable rather than writing
    # partial or wrong data over them.
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source_db})})
    sync.sync_table("p", "accounts", "account_id", ["account_id", "balance"], {"balance": "number"})

    conn = sqlite3.connect(source_db)
    conn.execute("INSERT INTO accounts VALUES ('a3', 'not-a-number')")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError):
        sync.sync_table(
            "p", "accounts", "account_id", ["account_id", "balance"], {"balance": "number"}
        )

    mirrored = sync._catalog.load_table("p.accounts").scan().to_arrow().to_pydict()
    assert mirrored["account_id"] == ["a1", "a2"]
    assert mirrored["balance"] == [500.0, 1000.0]
