"""
A boolean column stored as WORDS syncs, and reads back as booleans
(001's F-01).

MEASURED BEFORE: coerce("true", "boolean") raised. Strings went through
int(), which is right for SQLite's 0/1 and wrong for every other source
-- Postgres writes 't'/'f' and 'true'/'false', MySQL and CSV exports
'TRUE'/'FALSE' or 'yes'/'no'. And a raise in coerce is reported by the
sync as SCHEMA DRIFT, so the column could never sync AND the report
said the source had changed shape.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.transform import transform_rows
from core.ontology.field_types import coerce

WORDS = ["true", "TRUE", " t ", "yes", "y", "on", "false", "F", "no", "n", "off"]


class TestCoerce:
    @pytest.mark.parametrize("value", ["true", "TRUE", " t ", "yes", "Y", "on", "1", 1, True, "2"])
    def test_the_true_spellings(self, value):
        assert coerce(value, "boolean") is True

    @pytest.mark.parametrize("value", ["false", "FALSE", "f", "no", "N", "off", "0", 0, False])
    def test_the_false_spellings(self, value):
        assert coerce(value, "boolean") is False

    @pytest.mark.parametrize("value", ["maybe", "", "1.5", "null"])
    def test_what_is_not_a_boolean_still_raises(self, value):
        """The docstring means it: an honest mismatch is never defaulted."""
        with pytest.raises(ValueError, match="is not a boolean"):
            coerce(value, "boolean")

    def test_the_message_says_what_is_accepted(self):
        with pytest.raises(ValueError, match="true.*yes|yes.*true"):
            coerce("maybe", "boolean")

    def test_a_null_stays_null(self):
        assert coerce(None, "boolean") is None


class TestTheTransform:
    def test_words_are_not_drift(self):
        rows = [{"id": "a", "active": "true"}, {"id": "b", "active": "f"}]

        result = transform_rows(rows, ["id", "active"], {"id": "string", "active": "boolean"})

        assert not result.has_drift
        assert [row["active"] for row in result.rows] == [True, False]

    def test_a_value_that_is_not_a_boolean_still_drifts(self):
        rows = [{"id": "a", "active": "maybe"}]

        result = transform_rows(rows, ["id", "active"], {"id": "string", "active": "boolean"})

        assert result.has_drift
        assert result.drift[0].column == "active"
        assert result.drift[0].example_value == "maybe"


def test_a_text_boolean_column_syncs_and_reads_back(tmp_path):
    """END TO END, through a real source and a real sync: the case that
    could not sync at all."""
    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE flags (id TEXT PRIMARY KEY, active TEXT)")
    conn.executemany("INSERT INTO flags VALUES (?, ?)",
                     [(f"r{i}", word) for i, word in enumerate(WORDS)])
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": source})})
    result = sync.sync_table("primary", "flags", "id", ["id", "active"],
                             {"id": "string", "active": "boolean"})

    assert result.row_count == len(WORDS), result
    # Through the sync's OWN catalog, as the other mirror tests do.
    table = sync._catalog.load_table("primary.flags").scan().to_arrow()
    assert table.schema.field("active").type == "bool"
    by_id = {row["id"]: row["active"] for row in table.to_pylist()}
    assert [by_id[f"r{i}"] for i in range(len(WORDS))] == [coerce(word, "boolean") for word in WORDS]
