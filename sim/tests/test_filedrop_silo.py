"""Tests for the folder-of-files silo.

The interesting behaviour here is not "can it write a file" but the
publication discipline: a consumer polling the directory must see a
file either absent or complete, and the dialect must look like what
these files really look like rather than what would be tidy.
"""

import csv
import io
import os
import stat

import pytest
from simulator.ports import PortRegistry
from simulator.silo import SiloError
from simulator.silos.filedrop import (
    PARTIAL_SUFFIX,
    TERMINATED_SUFFIX,
    UTF8_BOM,
    FileDropSilo,
)


@pytest.fixture
def silo(tmp_path):
    made = FileDropSilo(name="bank", data_dir=tmp_path)
    made.create()
    return made


# -- lifecycle -------------------------------------------------------

def test_creation_makes_the_folder(silo):
    assert silo.path.is_dir()
    assert silo.is_reachable()


def test_creating_over_an_existing_folder_refuses(silo):
    with pytest.raises(SiloError, match="already exists"):
        silo.create()


def test_starting_and_stopping_do_nothing(silo):
    silo.start()
    silo.stop()
    assert silo.is_reachable()


def test_it_needs_no_port(tmp_path):
    assert FileDropSilo.requires_port is False
    registry = PortRegistry.allocate_for(tmp_path, [FileDropSilo(name="bank", data_dir=tmp_path)])
    assert registry.ports == {}


def test_a_missing_folder_is_not_reachable(silo):
    silo.path.rmdir()
    assert silo.is_reachable() is False


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission bits")
def test_an_unreadable_folder_is_not_reachable(silo):
    # The realistic way a share becomes unusable is a permission change
    # or a dropped mount, not a deletion -- and in both the path is
    # still there, so existence alone would report it healthy.
    silo.path.chmod(0o000)
    try:
        assert silo.is_reachable() is False
    finally:
        silo.path.chmod(stat.S_IRWXU)


def test_the_descriptor_is_path_shaped_and_names_the_encoding(silo):
    descriptor = silo.connection()
    assert descriptor.kind == "filedrop"
    assert descriptor.details["path"] == str(silo.path)
    # A consumer needs to be told about the BOM, because a file with
    # one read as plain utf-8 puts three stray bytes on the first
    # field name.
    assert descriptor.details["encoding"] == "utf-8-sig"


def test_without_a_bom_the_encoding_changes_too(tmp_path):
    silo = FileDropSilo(name="clean", data_dir=tmp_path, bom=False)
    assert silo.connection().details["encoding"] == "utf-8"


# -- publication discipline ------------------------------------------

def test_a_published_file_is_never_visible_half_written(silo, monkeypatch):
    # THE property this silo exists to get right, and it can only be
    # checked DURING the write. A first version asserted the end state
    # -- file published, no partials left behind -- and passed against
    # a version that wrote straight to the final name, because writing
    # in place also ends with a complete file and no partials. That is
    # a test of the outcome both implementations share.
    #
    # So the interleaving is forced instead: every write is intercepted
    # and asked what a consumer polling the directory would see at that
    # exact moment. The payload must never land on the published name.
    import pathlib as _pathlib

    original = _pathlib.Path.write_bytes
    observations = []

    def observe(self, *args, **kwargs):
        observations.append((self.name, (silo.path / "statement_2026-03-02.csv").exists()))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(_pathlib.Path, "write_bytes", observe)
    silo.write_csv("statement_2026-03-02.csv", ["date", "amount"],
                   [["2026-03-01", "12.50"], ["2026-03-02", "-4.00"]])

    assert observations, "nothing was written"
    for written_name, published_existed in observations:
        assert written_name.endswith(PARTIAL_SUFFIX), written_name
        assert published_existed is False

    assert silo.listing() == ["statement_2026-03-02.csv"]
    assert not list(silo.path.glob(f"*{PARTIAL_SUFFIX}"))


def test_a_non_atomic_write_really_does_land_on_the_published_name(silo, monkeypatch):
    # The counterpart, and the reason atomic=False exists: a
    # badly-behaved publisher writes straight to the name a consumer is
    # polling, which is what makes torn reads possible.
    import pathlib as _pathlib

    original = _pathlib.Path.write_bytes
    written = []

    def observe(self, *args, **kwargs):
        written.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(_pathlib.Path, "write_bytes", observe)
    silo.place("raw.csv", "date,amount\r\n", atomic=False)
    assert written == ["raw.csv"]


def test_listing_hides_partial_writes_that_are_still_in_flight(silo):
    # A consumer WOULD see these -- they are really on disk -- but they
    # are not published, and the silo reports what it published.
    (silo.path / f"statement.csv{PARTIAL_SUFFIX}").write_text("date,amount\r\n")
    assert silo.listing() == []


def test_a_non_atomic_write_is_available_on_purpose(silo):
    # Plenty of real publishers write in place, and the resulting torn
    # reads are a recurring integration failure. Being able to cause it
    # is a property of the upstream being simulated.
    path = silo.place("raw.csv", "date,amount\r\n", atomic=False)
    assert path.exists()
    assert not list(silo.path.glob(f"*{PARTIAL_SUFFIX}"))


def test_publishing_into_an_unreachable_silo_fails_loudly(silo):
    silo.terminate()
    with pytest.raises(SiloError, match="not reachable"):
        silo.place("statement.csv", "a,b\r\n")


@pytest.mark.parametrize("bad", ["../escape.csv", "sub/dir.csv", "back\\slash.csv"])
def test_a_filename_with_a_separator_is_refused(silo, bad):
    # A publisher drops files IN the folder. Allowing a separator would
    # let a pack write outside its own silo.
    with pytest.raises(SiloError, match="plain file name"):
        silo.place(bad, "x")


# -- dialect ---------------------------------------------------------

def test_csv_is_written_the_way_these_files_really_look(silo):
    path = silo.write_csv("export.csv", ["date", "description", "amount"],
                          [["2026-03-01", "Coffee, large", "-4.20"]])
    raw = path.read_bytes()

    # A BOM, because Excel misreads UTF-8 without one and so real
    # exporters emit one.
    assert raw.startswith(UTF8_BOM.encode("utf-8"))
    # CRLF, because these come off Windows.
    assert b"\r\n" in raw
    # And exactly one pair per line. NOTE: this assertion cannot fail
    # on Linux and is kept for what it documents rather than for what
    # it catches. Measured: with newline translation left on,
    # write_text turns "\n" into os.linesep, which IS "\n" here, so
    # CRLF survives unchanged. The CRLFCRLF hazard the newline=""
    # argument prevents only manifests on Windows, where os.linesep is
    # already CRLF. A negative control confirmed the assertion does not
    # fire when newline="" is removed.
    assert b"\r\r\n" not in raw
    # The comma inside a field is quoted rather than breaking the row.
    assert b'"Coffee, large"' in raw


def test_a_consumer_reading_it_as_utf_8_sig_gets_clean_values(silo):
    path = silo.write_csv("export.csv", ["date", "amount"], [["2026-03-01", "-4.20"]])
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["date", "amount"]
    assert rows[1] == ["2026-03-01", "-4.20"]


def test_a_consumer_ignoring_the_bom_sees_it_on_the_first_field(silo):
    # Not a defect -- the condition a real consumer has to handle, and
    # worth pinning so the silo keeps producing it.
    path = silo.write_csv("export.csv", ["date", "amount"], [["2026-03-01", "-4.20"]])
    with path.open("r", encoding="utf-8", newline="") as handle:
        first = next(csv.reader(handle))
    assert first[0] != "date"
    assert first[0].endswith("date")


def test_the_bom_can_be_turned_off(tmp_path):
    silo = FileDropSilo(name="clean", data_dir=tmp_path, bom=False)
    silo.create()
    path = silo.write_csv("export.csv", ["a"], [["1"]])
    assert not path.read_bytes().startswith(UTF8_BOM.encode("utf-8"))


def test_the_line_terminator_can_be_turned_unix(tmp_path):
    silo = FileDropSilo(name="unix", data_dir=tmp_path, line_terminator="\n")
    silo.create()
    raw = silo.write_csv("export.csv", ["a"], [["1"]]).read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"1\n")


def test_many_rows_round_trip(silo):
    rows = [[f"2026-03-{day:02d}", f"{day * 1.5:.2f}"] for day in range(1, 29)]
    path = silo.write_csv("month.csv", ["date", "amount"], rows)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        read_back = list(csv.reader(handle))
    assert read_back[0] == ["date", "amount"]
    assert len(read_back) == 29
    assert read_back[-1] == ["2026-03-28", "42.00"]


# -- termination -----------------------------------------------------

def test_terminate_moves_the_folder_aside_and_is_recoverable(silo):
    silo.write_csv("statement.csv", ["a"], [["1"]])
    silo.terminate()

    assert silo.is_reachable() is False
    moved = silo.path.with_name(silo.path.name + TERMINATED_SUFFIX)
    assert moved.is_dir()

    moved.replace(silo.path)
    assert silo.is_reachable()
    assert silo.listing() == ["statement.csv"]


def test_terminating_an_absent_folder_is_quiet(silo):
    silo.path.rmdir()
    silo.terminate()


def test_listing_an_unreachable_silo_is_empty_rather_than_an_error(silo):
    silo.terminate()
    assert silo.listing() == []


# -- registration ----------------------------------------------------

def test_it_is_registered_as_a_kind():
    from simulator.silos import SILO_TYPES

    assert SILO_TYPES["filedrop"] is FileDropSilo


def test_a_partially_written_file_would_be_a_short_parse(silo):
    # Why the atomic rename matters, demonstrated rather than asserted
    # about: a truncated CSV does not raise, it parses into fewer rows
    # with a mangled last one, which is the failure mode that survives
    # unnoticed.
    complete = io.StringIO()
    writer = csv.writer(complete, lineterminator="\r\n")
    writer.writerow(["date", "amount"])
    for day in range(1, 11):
        writer.writerow([f"2026-03-{day:02d}", day])
    truncated = complete.getvalue()[: len(complete.getvalue()) // 2]

    parsed = list(csv.reader(io.StringIO(truncated)))
    assert len(parsed) < 11


def test_a_share_left_out_by_a_crashed_run_is_restored(tmp_path):
    # Whether a source is out lives in the running process. One killed
    # mid-outage leaves the folder aside, and the next run's silo starts
    # with offline False, so restore has to look at the disk.
    from simulator import outages

    first = FileDropSilo(name="drop", data_dir=tmp_path)
    first.create()
    outages.cut_off(first, None)

    again = FileDropSilo(name="drop", data_dir=tmp_path)
    assert not again.is_reachable()
    outages.restore(again, None)

    assert again.is_reachable()


# -- realism options (REAL_SOURCES.md F1-F6) --------------------------

import csv as _csv  # noqa: E402
import io as _io  # noqa: E402
import zipfile as _zipfile  # noqa: E402
from datetime import UTC as _UTC  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402
from datetime import timedelta as _timedelta  # noqa: E402
from decimal import Decimal as _Decimal  # noqa: E402

from simulator.silos.filedrop import as_excel_saves  # noqa: E402

_T0 = _datetime(2026, 10, 19, 9, 0, tzinfo=_UTC)


def _share(tmp_path, **options):
    silo = FileDropSilo(name="share", data_dir=tmp_path, **options)
    silo.create()
    return silo


def _rows(path, encoding="utf-8-sig", delimiter=","):
    return list(_csv.reader(_io.StringIO(path.read_bytes().decode(encoding)),
                            delimiter=delimiter))


def test_the_options_are_off_by_default(tmp_path):
    silo = _share(tmp_path)
    silo.between_ticks(_T0)
    for day in range(20):
        silo.write_csv(f"f{day:02}.csv", ["a", "b"], [["001", _Decimal("1.50")]])

    assert len(silo.listing()) == 20
    assert _rows(silo.path / "f00.csv") == [["a", "b"], ["001", "1.50"]]


def test_a_windows_code_page_file_has_question_marks_for_what_it_cannot_hold(tmp_path):
    silo = _share(tmp_path, encoding="cp1252")

    silo.write_csv("x.csv", ["name"], [["Café"], ["名前"]])

    raw = (silo.path / "x.csv").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert _rows(silo.path / "x.csv", "cp1252") == [["name"], ["Café"], ["??"]]
    assert silo.connection().details["encoding"] == "cp1252"


def test_a_comma_decimal_locale_writes_semicolons_and_decimal_commas(tmp_path):
    silo = _share(tmp_path, delimiter=";", decimal_comma=True)

    silo.write_csv("x.csv", ["sku", "price"], [["a", _Decimal("12.50")]])

    assert (silo.path / "x.csv").read_bytes().decode("utf-8-sig").splitlines()[1] == "a;12,50"
    assert silo.connection().details["delimiter"] == ";"


def test_a_decimal_comma_with_a_comma_delimiter_is_refused(tmp_path):
    with pytest.raises(SiloError, match="decimal comma"):
        FileDropSilo(name="x", data_dir=tmp_path, decimal_comma=True)


@pytest.mark.parametrize(("value", "saved"), [
    ("00123", "123"),                                 # Microsoft's own examples
    ("12345678901234567890", "1.23457E+19"),
    ("123E5", "1.23E+07"),
    ("JAN1", "1-Jan"),
    (_Decimal("12.50"), "12.5"),
    ("2026-10-19", "10/19/2026"),
    ("2026-10-19 09:05:00", "10/19/2026 9:05"),
    ("2026-10-19T09:05:00+00:00", "2026-10-19T09:05:00+00:00"),   # an offset stays text
    ("hello", "hello"),
    # Found in review: the order of the rules, signs, and what is not a date.
    ("0123456789012345678", "1.23457E+17"),
    ("-12345678901234567890", "-1.23457E+19"),
    ("-007", "-7"),
    ("00.50", "0.5"),
    ("MAY32", "May-32"),                              # no 32nd: May 1932
    ("2026-01-01T10:00", "2026-01-01T10:00"),         # a T stays text
    ("0000-00-00", "0000-00-00"),                     # no such date
])
def test_values_come_back_as_excel_saves_them(value, saved):
    assert as_excel_saves(value) == saved


def test_excel_conversions_apply_to_every_cell_but_the_header(tmp_path):
    silo = _share(tmp_path, excel_conversions=True)

    silo.write_csv("x.csv", ["00id"], [["00042"]])

    assert _rows(silo.path / "x.csv") == [["00id"], ["42"]]


def test_columns_can_come_in_a_different_order_in_each_file(tmp_path):
    silo = _share(tmp_path, reorder_columns=True)
    header = ["a", "b", "c", "d", "e"]

    orders = set()
    for day in range(6):
        silo.write_csv(f"f{day}.csv", header, [header])
        rows = _rows(silo.path / f"f{day}.csv")
        assert rows[0] == rows[1], "each value stays under its own column"
        orders.add(tuple(rows[0]))

    assert len(orders) > 1 and all(sorted(order) == header for order in orders)


def test_a_zipped_export_holds_the_csv(tmp_path):
    silo = _share(tmp_path, zipped=True)

    silo.write_csv("report.csv", ["a"], [["1"]])

    assert silo.listing() == ["report.csv.zip"]
    with _zipfile.ZipFile(silo.path / "report.csv.zip") as archive:
        assert archive.namelist() == ["report.csv"]
        assert archive.read("report.csv").decode("utf-8-sig").splitlines() == ["a", "1"]
    assert silo.connection().details["format"] == "zip"


def test_a_non_atomic_file_is_half_written_until_the_next_tick(tmp_path):
    silo = _share(tmp_path, atomic_writes=False)
    silo.between_ticks(_T0)
    rows = [[f"r{index}", "x" * 20] for index in range(50)]

    silo.write_csv("x.csv", ["id", "pad"], rows)
    seen = _rows(silo.path / "x.csv")
    silo.between_ticks(_T0 + _timedelta(hours=1))

    assert 1 < len(seen) < 51, "a reader now meets a short file"
    assert _rows(silo.path / "x.csv") == [["id", "pad"], *rows]


def test_late_files_arrive_after_their_delay(tmp_path):
    silo = _share(tmp_path, late_rate=1.0, late_seconds=6 * 3600)
    silo.between_ticks(_T0)

    silo.write_csv("x.csv", ["a"], [["1"]])
    silo.between_ticks(_T0 + _timedelta(hours=5))
    early = silo.listing()
    silo.between_ticks(_T0 + _timedelta(hours=6))

    assert early == [] and silo.listing() == ["x.csv"]


def test_a_share_of_files_are_sent_twice(tmp_path):
    silo = _share(tmp_path, duplicate_rate=0.25)
    silo.between_ticks(_T0)

    for day in range(200):
        silo.write_csv(f"f{day:03}.csv", ["a"], [[str(day)]])

    copies = [name for name in silo.listing() if " (1)" in name]
    # 200 draws at 0.25: a band about four standard deviations wide.
    assert 26 <= len(copies) <= 74, len(copies)
    original = copies[0].replace(" (1)", "")
    assert (silo.path / copies[0]).read_bytes() == (silo.path / original).read_bytes()


def test_only_the_newest_files_are_kept(tmp_path):
    silo = _share(tmp_path, keep_last=3)

    for day in range(6):
        silo.write_csv(f"f{day}.csv", ["a"], [["1"]])

    assert silo.listing() == ["f3.csv", "f4.csv", "f5.csv"]


@pytest.mark.parametrize("options", [
    {"encoding": "utf-16"}, {"delimiter": "|"}, {"duplicate_rate": 2},
    {"late_rate": -1}, {"late_seconds": 0}, {"keep_last": 0},
], ids=["encoding", "delimiter", "duplicate", "late", "late-seconds", "keep"])
def test_nonsense_options_are_refused(tmp_path, options):
    with pytest.raises(SiloError):
        FileDropSilo(name="x", data_dir=tmp_path, **options)


def test_excel_and_a_decimal_comma_together_save_as_a_comma_excel_does(tmp_path):
    silo = _share(tmp_path, delimiter=";", decimal_comma=True, excel_conversions=True)

    silo.write_csv("x.csv", ["price"], [[_Decimal("12.50")]])

    assert (silo.path / "x.csv").read_bytes().decode("utf-8-sig").splitlines()[1] == "12,5"


@pytest.mark.parametrize(("name", "copy"), [
    ("report.2026-10-20.csv", "report.2026-10-20 (1).csv"),
    ("report.csv.zip", "report (1).csv.zip"),
])
def test_a_second_copy_is_named_as_a_browser_names_it(tmp_path, name, copy):
    silo = _share(tmp_path, duplicate_rate=1.0, zipped=name.endswith(".zip"))
    silo.between_ticks(_T0)

    silo.write_csv(name.removesuffix(".zip"), ["a"], [["1"]])

    assert sorted(silo.listing()) == sorted([name, copy])


def test_a_half_written_file_that_expires_is_not_brought_back(tmp_path):
    # Found in review: two exports in one tick with keep_last=1; the first,
    # expired while half-written, was finished at the next tick and came
    # back as the newest file.
    silo = _share(tmp_path, atomic_writes=False, keep_last=1)
    silo.between_ticks(_T0)

    silo.write_csv("a.csv", ["x"], [["1"]] * 20)
    silo.write_csv("b.csv", ["x"], [["2"]] * 20)
    silo.between_ticks(_T0 + _timedelta(hours=1))

    assert silo.listing() == ["b.csv"]
    assert len(_rows(silo.path / "b.csv")) == 21


def test_files_waiting_when_the_share_fails_are_kept_for_later(tmp_path):
    silo = _share(tmp_path, late_rate=1.0, late_seconds=3600)
    silo.between_ticks(_T0)
    silo.write_csv("a.csv", ["x"], [["1"]])
    silo.write_csv("b.csv", ["x"], [["2"]])
    silo.terminate()                                  # the share is gone

    with pytest.raises(SiloError):
        silo.between_ticks(_T0 + _timedelta(hours=2))

    assert [entry[1] for entry in silo._pending] == ["a.csv", "b.csv"]
