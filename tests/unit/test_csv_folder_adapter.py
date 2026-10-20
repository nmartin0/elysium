"""A folder of CSV files as a source (19 October).

adapters/csv_folder_adapter.py has the precedent behind each rule. These
pin them: the two shapes, the newer file winning, a broken line stopping
the table with its file and line named, half-written files left alone,
one listing per sync, and the formats real exports arrive in -- several
written by the simulator's own file writer, so the files are the ones a
simulated supplier really drops.
"""

import os
import time
from decimal import Decimal

import pytest

from adapters.csv_folder_adapter import BadLine, CsvFolderAdapter
from core.ontology.interface import StorageUnavailable

CONFIG = {"storage": {"table": "sold", "id_column": "id"}}


def _write(folder, name, text, *, encoding="utf-8", age=0.0):
    path = folder / name
    path.write_bytes(text.encode(encoding))
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def _adapter(folder, shape="combined", **extra):
    return CsvFolderAdapter({"path": folder, "tables": {"sold": {"files": "sold_*.csv", "shape": shape}},
                             **extra})


def _rows(adapter, columns=("id", "qty")):
    return sorted(adapter.read_all_rows("sold", list(columns), CONFIG), key=lambda r: str(r["id"]))


class TestTheTwoShapes:
    def test_latest_reads_only_the_newest_file(self, tmp_path):
        _write(tmp_path, "sold_1.csv", "id,qty\na,1\nb,2\n", age=60)
        _write(tmp_path, "sold_2.csv", "id,qty\na,5\n")

        assert _rows(_adapter(tmp_path, "latest")) == [{"id": "a", "qty": "5"}]

    def test_combined_reads_them_all_and_the_newer_file_wins(self, tmp_path):
        _write(tmp_path, "sold_1.csv", "id,qty\na,1\nb,2\n", age=60)
        _write(tmp_path, "sold_2.csv", "id,qty\na,5\nc,3\n")

        assert _rows(_adapter(tmp_path)) == [
            {"id": "a", "qty": "5"}, {"id": "b", "qty": "2"}, {"id": "c", "qty": "3"}]

    def test_newest_is_by_when_it_was_written_not_its_name(self, tmp_path):
        _write(tmp_path, "sold_z.csv", "id,qty\na,old\n", age=60)
        _write(tmp_path, "sold_a.csv", "id,qty\na,new\n")

        assert _rows(_adapter(tmp_path, "latest")) == [{"id": "a", "qty": "new"}]

    def test_a_duplicate_within_one_file_is_left_for_the_syncs_guard(self, tmp_path):
        """Choosing between two lines of ONE file would hide a fault the
        sync's duplicate guard exists to report."""
        _write(tmp_path, "sold_1.csv", "id,qty\na,1\na,2\n")

        assert len(_rows(_adapter(tmp_path))) == 2


class TestAFileThatCannotBeRead:
    def test_a_broken_line_stops_the_table_naming_the_file_and_line(self, tmp_path):
        _write(tmp_path, "sold_1.csv", "id,qty\na,1\nb,2,extra\n")

        with pytest.raises(BadLine, match=r"sold_1\.csv, line 3: 3 values where the header names 2"):
            _rows(_adapter(tmp_path))

    def test_text_in_another_encoding_says_so(self, tmp_path):
        _write(tmp_path, "sold_1.csv", "id,qty\ncafé,1\n", encoding="cp1252")

        with pytest.raises(BadLine, match="is not utf-8-sig text"):
            _rows(_adapter(tmp_path))

    def test_and_reads_when_told_the_encoding(self, tmp_path):
        _write(tmp_path, "sold_1.csv", "id,qty\ncafé,1\n", encoding="cp1252")

        assert _rows(_adapter(tmp_path, encoding="cp1252"))[0]["id"] == "café"

    def test_no_matching_file_is_a_source_that_cannot_answer(self, tmp_path):
        with pytest.raises(StorageUnavailable, match="no file matches"):
            _rows(_adapter(tmp_path))

    def test_a_header_naming_a_column_twice(self, tmp_path):
        _write(tmp_path, "sold_1.csv", "id,qty,qty\na,1,2\n")

        with pytest.raises(BadLine, match="names a column twice"):
            _rows(_adapter(tmp_path))


class TestWhatIsNotRead:
    @pytest.mark.parametrize("name", ["sold_2.csv.part", ".sold_2.csv", "~$sold_2.csv",
                                      "sold_2.csv.tmp", "sold_2.csv.writing"])
    def test_half_written_hidden_and_lock_files(self, tmp_path, name):
        """Under a pattern that MATCHES them -- `*` -- so the only thing
        keeping each out is the rule being tested. Under `sold_*.csv` most
        would never have matched, and the test could not have failed."""
        _write(tmp_path, "sold_1.csv", "id,qty\na,1\n", age=60)
        _write(tmp_path, name, "id,qty\na,999\n")
        adapter = CsvFolderAdapter({"path": tmp_path,
                                    "tables": {"sold": {"files": "*", "shape": "latest"}}})

        assert _rows(adapter) == [{"id": "a", "qty": "1"}]

    def test_a_file_the_pattern_does_not_name(self, tmp_path):
        _write(tmp_path, "sold_1.csv", "id,qty\na,1\n", age=60)
        _write(tmp_path, "other_2.csv", "id,qty\na,999\n")

        assert _rows(_adapter(tmp_path, "latest")) == [{"id": "a", "qty": "1"}]

    def test_a_file_arriving_mid_sync_waits_for_the_next(self, tmp_path):
        _write(tmp_path, "sold_1.csv", "id,qty\na,1\n", age=60)
        adapter = _adapter(tmp_path, "latest")

        with adapter.consistent_read() as pinned:
            columns = adapter.columns_present("sold")
            _write(tmp_path, "sold_2.csv", "id,qty,note\na,9,x\n")
            rows = _rows(adapter)

        assert pinned is True and columns == {"id", "qty"} and rows == [{"id": "a", "qty": "1"}]
        assert _rows(adapter) == [{"id": "a", "qty": "9"}], "and is read by the next sync"


class TestFormatsAsTheyArrive:
    def test_excel_on_windows(self, tmp_path):
        """A BOM, CRLF, a `sep=` line, quoted commas and line breaks."""
        _write(tmp_path, "sold_1.csv",
               '﻿sep=;\r\nid;qty;note\r\na;1;"semi; colon"\r\nb;2;"two\r\nlines"\r\n')

        rows = _rows(_adapter(tmp_path), ("id", "qty", "note"))

        assert rows == [{"id": "a", "qty": "1", "note": "semi; colon"},
                        {"id": "b", "qty": "2", "note": "two\r\nlines"}]

    def test_empty_means_null_and_others_can_be_named(self, tmp_path):
        _write(tmp_path, "sold_1.csv", "id,qty\na,\nb,N/A\n")

        assert [r["qty"] for r in _rows(_adapter(tmp_path))] == [None, "N/A"]
        assert [r["qty"] for r in _rows(_adapter(tmp_path, null_values=["", "N/A"]))] == [None, None]

    def test_a_column_added_since_older_files(self, tmp_path):
        _write(tmp_path, "sold_1.csv", "id,qty\na,1\n", age=60)
        _write(tmp_path, "sold_2.csv", "id,qty,note\nb,2,new\n")
        adapter = _adapter(tmp_path)

        assert adapter.columns_present("sold") == {"id", "qty", "note"}
        assert _rows(adapter, ("id", "note")) == [{"id": "a", "note": None}, {"id": "b", "note": "new"}]

    def test_files_the_simulator_drops(self, tmp_path):
        """Written by the simulator's own supplier-feed writer: a BOM,
        CRLF, Decimal and timestamp values as it renders them."""
        from datetime import UTC, datetime

        from simulator.silos.filedrop import FileDropSilo

        drop = FileDropSilo("supplier", tmp_path)
        drop.create()
        drop.write_csv("sold_2026-01-07.csv", ["id", "qty", "at"],
                       [("s1", Decimal("2.5000"), datetime(2026, 1, 7, 9, 30, tzinfo=UTC))])

        adapter = _adapter(drop.path)
        rows = adapter.read_all_rows("sold", ["id", "qty", "at"], CONFIG)

        assert rows == [{"id": "s1", "qty": "2.5000", "at": "2026-01-07 09:30:00+00:00"}]
        assert not (drop.path / "sold_2026-01-07.csv.part").exists()


class TestItsDeclaration:
    @pytest.mark.parametrize("connection, error", [
        ({"tables": {"sold": {"files": "*.csv"}}}, "path"),
        ({"path": "x"}, "tables"),
        ({"path": "x", "tables": {"sold": {}}}, "needs `files`"),
        ({"path": "x", "tables": {"sold": {"files": "a/*.csv"}}}, "not a path"),
        ({"path": "x", "tables": {"sold": {"files": "*.csv", "shape": "append"}}}, "shape must be"),
        ({"path": "x", "tables": {"sold": {"files": "*.csv"}}, "delimiter": ";;"}, "one character"),
        ({"path": "x", "tables": {"sold": {"files": "*.csv"}}, "encoding": "klingon"}, "unknown encoding"),
    ])
    def test_a_wrong_declaration_is_refused_at_load(self, connection, error):
        with pytest.raises(ValueError, match=error):
            CsvFolderAdapter(connection)

    def test_the_folder_is_checked_for_health(self, tmp_path):
        _adapter(tmp_path).health_check()
        with pytest.raises(FileNotFoundError):
            _adapter(tmp_path / "missing").health_check()

    def test_it_answers_nothing_but_the_sync(self, tmp_path):
        with pytest.raises(NotImplementedError, match="answered from gold"):
            _adapter(tmp_path).find_ids("Sale", [], CONFIG)


class TestThroughTheSync:
    """End to end into the mirror, as run_sync drives it."""

    def _sync(self, tmp_path, folder):
        from core.mirror.iceberg_sync import IcebergMirrorSync

        return IcebergMirrorSync(tmp_path / "mirror", {"supplier": _adapter(folder)})

    def test_a_folder_becomes_a_mirrored_table(self, tmp_path):
        folder = tmp_path / "drop"
        folder.mkdir()
        _write(folder, "sold_1.csv", "id,qty\na,1\nb,2\n", age=60)
        _write(folder, "sold_2.csv", "id,qty\nb,7\n")

        result = self._sync(tmp_path, folder).sync_table("supplier", "sold", "id", ["id", "qty"])

        assert result.row_count == 2

    def test_a_broken_line_leaves_the_last_good_copy(self, tmp_path):
        folder = tmp_path / "drop"
        folder.mkdir()
        _write(folder, "sold_1.csv", "id,qty\na,1\nb,2\n", age=60)
        sync = self._sync(tmp_path, folder)
        sync.sync_table("supplier", "sold", "id", ["id", "qty"])
        _write(folder, "sold_2.csv", "id,qty\nc,3,oops\n")

        with pytest.raises(BadLine, match="sold_2.csv, line 2"):
            sync.sync_table("supplier", "sold", "id", ["id", "qty"])

        served = sync.catalog.load_table("supplier.sold").scan().to_arrow().num_rows
        assert served == 2


def test_it_is_registered():
    from core.deployment_loader import _READ_ADAPTER_REGISTRY

    assert _READ_ADAPTER_REGISTRY["csv_folder"] is CsvFolderAdapter



def test_a_frozen_declaration_is_accepted(tmp_path):
    """As the deployment loader hands it over: deep-frozen. The first run
    against a real deployment failed here while every dict-fed test passed."""
    from core.immutable import deep_freeze

    _write(tmp_path, "sold_1.csv", "id,qty\na,1\n")
    frozen = deep_freeze({"path": str(tmp_path), "null_values": [""],
                          "tables": {"sold": {"files": "sold_*.csv", "shape": "combined"}}})

    assert _rows(CsvFolderAdapter(frozen)) == [{"id": "a", "qty": "1"}]


class TestFoundInReview:
    def test_a_broken_record_spanning_lines_is_named_by_its_first_line(self, tmp_path):
        _write(tmp_path, "sold_1.csv", 'id,qty\na,"one\ntwo",extra\nb,2\n')

        with pytest.raises(BadLine, match=r"sold_1\.csv, line 2:"):
            _rows(_adapter(tmp_path))

    def test_an_empty_value_in_a_one_column_file_is_a_row(self, tmp_path):
        _write(tmp_path, "sold_1.csv", 'id\na\n""\nb\n')
        adapter = CsvFolderAdapter({"path": tmp_path, "tables": {"sold": {"files": "sold_*.csv"}}})

        assert len(adapter.read_all_rows("sold", ["id"], CONFIG)) == 3


class TestCompressedFiles:
    """Read as Fivetran's file connectors read them (20 October)."""

    def _zipped(self, folder, name, members):
        import zipfile

        with zipfile.ZipFile(folder / name, "w") as archive:
            for member, text in members.items():
                archive.writestr(member, text)

    def test_a_zipped_export_from_the_simulator_is_read(self, tmp_path):
        from simulator.silos.filedrop import FileDropSilo

        drop = FileDropSilo(name="supplier", data_dir=tmp_path, zipped=True)
        drop.create()
        drop.write_csv("sold_2026-01-05.csv", ["id", "qty"], [["a", "1"], ["b", "2"]])
        adapter = CsvFolderAdapter({"path": drop.path, "encoding": "utf-8-sig",
                                    "tables": {"sold": {"files": "sold_*.csv.zip",
                                                        "shape": "combined"}}})

        assert _rows(adapter) == [{"id": "a", "qty": "1"}, {"id": "b", "qty": "2"}]

    def test_a_gzipped_file_is_read(self, tmp_path):
        import gzip

        (tmp_path / "sold_1.csv.gz").write_bytes(gzip.compress(b"id,qty\na,1\n"))
        adapter = CsvFolderAdapter({"path": tmp_path, "tables": {
            "sold": {"files": "sold_*.csv.gz", "shape": "combined"}}})

        assert _rows(adapter) == [{"id": "a", "qty": "1"}]

    def test_a_zip_of_several_files_stops_the_table_rather_than_guess(self, tmp_path):
        self._zipped(tmp_path, "sold_1.zip", {"a.csv": "id,qty\na,1\n", "b.csv": "id,qty\nb,2\n"})
        adapter = CsvFolderAdapter({"path": tmp_path, "tables": {
            "sold": {"files": "sold_*.zip", "shape": "combined"}}})

        with pytest.raises(BadLine, match="holds 2 files"):
            _rows(adapter)

    def test_a_mac_archives_hidden_extras_are_not_counted(self, tmp_path):
        self._zipped(tmp_path, "sold_1.zip", {"sold.csv": "id,qty\na,1\n",
                                              "__MACOSX/._sold.csv": "junk"})
        adapter = CsvFolderAdapter({"path": tmp_path, "tables": {
            "sold": {"files": "sold_*.zip", "shape": "combined"}}})

        assert _rows(adapter) == [{"id": "a", "qty": "1"}]

    def test_a_cut_off_archive_is_a_broken_file(self, tmp_path):
        (tmp_path / "sold_1.zip").write_bytes(b"PK\x03\x04 not really")
        adapter = CsvFolderAdapter({"path": tmp_path, "tables": {
            "sold": {"files": "sold_*.zip", "shape": "combined"}}})

        with pytest.raises(BadLine, match="not a whole zip"):
            _rows(adapter)


    def test_a_damaged_gzip_is_a_broken_file_naming_it(self, tmp_path):
        import gzip

        # Damaged inside the compressed stream, which zlib reports as its
        # own error, not an OSError (found in review).
        damaged = bytearray(gzip.compress(b"id,qty\n" + b"a,1\n" * 2000))
        damaged[20:30] = b"\xff" * 10
        (tmp_path / "sold_1.csv.gz").write_bytes(bytes(damaged))
        adapter = CsvFolderAdapter({"path": tmp_path, "tables": {
            "sold": {"files": "sold_*.csv.gz", "shape": "combined"}}})

        with pytest.raises(BadLine, match="sold_1.csv.gz"):
            _rows(adapter)
