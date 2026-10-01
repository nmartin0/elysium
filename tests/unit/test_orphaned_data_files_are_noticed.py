"""
Data files no live snapshot references are reported (ELT_ROADMAP.md,
corrected 1 October).

WHAT THE DOCUMENT CLAIMED: "BRONZE is the bounded layer ... retaining
exactly TWO snapshots -- current and previous, which is all a diff
needs. Bounded at roughly 2x table size."

IT IS NOT BOUNDED. Bronze does retain two snapshots, and that is now
enforced -- patch 477 found the retention properties declared for
months with nothing calling expiry on them. But EXPIRY UNREFERENCES;
IT DOES NOT DELETE, and pyiceberg has no orphan sweep
(apache/iceberg-python #3361), so the files of expired snapshots stay
for ever.

MEASURED, with the retention margin shortened so expiry actually ran
and one row changed per sync:

    after sync 1    92 KB    2 parquet
    after sync 4   252 KB    5 parquet
    after sync 8   512 KB    9 parquet

One file per sync, none reclaimed, growing at full table size --
which is the copy-on-write behaviour ELT_ROADMAP already measured
elsewhere in the same file. OPEN_RISKS item 3 says plainly that
"expiry unreferences while ORPHAN CLEANUP is what actually reclaims
bytes"; the roadmap stated the bound as fact anyway.

IT ONLY REPORTS, deliberately. Deleting a data file is a deletion
against a lake: it wants the margin argument expiry has and a dry run
before it writes, which is repair_catalog's shape rather than a cron
job's. What was missing was anybody NOTICING.

A TOLERANCE, NOT ZERO. A write in flight and a just-expired snapshot
each leave one behind legitimately. It is the unbounded growth that is
the finding, not the existence of an unreferenced file.
"""

import pytest

from core.mirror.integrity import (
    _ORPHAN_TOLERANCE,
    _check_for_orphaned_data_files,
)


class _Report:
    def __init__(self):
        self.problems = []

    def note(self, message):
        self.problems.append(message)


def _warehouse(tmp_path, names):
    directory = tmp_path / "p" / "t" / "data"
    directory.mkdir(parents=True)
    for name in names:
        (directory / name).write_bytes(b"x" * 2048)
    return tmp_path


class _Catalog:
    """A stand-in. The real lookup is patched out in every test here,
    so this exists only to be passed."""

    def load_table(self, identifier):
        raise AssertionError("_files_a_snapshot_references is patched")


def _check(tmp_path, on_disk, live, monkeypatch):
    import core.mirror.integrity as integrity

    monkeypatch.setattr(integrity, "_files_a_snapshot_references",
                         lambda catalog, identifier: set(live))
    report = _Report()
    _check_for_orphaned_data_files(_Catalog(), _warehouse(tmp_path, on_disk),
                                    {"p.t"}, report)
    return report.problems


class TestWhatIsReported:
    def test_many_files_no_snapshot_references(self, tmp_path, monkeypatch):
        """THE CASE THIS EXISTS FOR. Eight syncs left nine files and
        nothing noticed."""
        on_disk = [f"{n}.parquet" for n in range(12)]

        problems = _check(tmp_path, on_disk, {"0.parquet"}, monkeypatch)

        assert len(problems) == 1
        assert "11 data file(s)" in problems[0]

    def test_the_message_carries_the_size(self, tmp_path, monkeypatch):
        """A count alone does not say whether it matters. The growth
        is the finding, so the number that shows it belongs there."""
        problems = _check(tmp_path, [f"{n}.parquet" for n in range(12)],
                           set(), monkeypatch)

        assert "KB" in problems[0]

    def test_it_points_at_the_explanation(self, tmp_path, monkeypatch):
        """An operator reading this has to be able to find out why
        nothing reclaims, which is not obvious."""
        problems = _check(tmp_path, [f"{n}.parquet" for n in range(12)],
                           set(), monkeypatch)

        assert "ELT_ROADMAP.md" in problems[0]
        assert "Expiry unreferences" in problems[0]


class TestWhatIsQuiet:
    def test_a_table_whose_files_are_all_referenced(self, tmp_path,
                                                     monkeypatch):
        on_disk = [f"{n}.parquet" for n in range(12)]

        assert _check(tmp_path, on_disk, set(on_disk), monkeypatch) == []

    def test_a_few_unreferenced_files(self, tmp_path, monkeypatch):
        """A write in flight and a just-expired snapshot each leave one
        legitimately. A fresh deployment must not be reported."""
        on_disk = [f"{n}.parquet" for n in range(_ORPHAN_TOLERANCE)]

        assert _check(tmp_path, on_disk, set(), monkeypatch) == []

    def test_many_files_of_which_only_a_few_are_orphaned(self, tmp_path,
                                                          monkeypatch):
        """THE CASE THE TOLERANCE ACTUALLY GUARDS, and without it this
        file's control proved nothing: with plenty of files on disk,
        the first guard passes and only the ORPHAN count should decide.
        Removing the tolerance left every test green until this
        existed."""
        on_disk = [f"{n}.parquet" for n in range(40)]
        referenced = {f"{n}.parquet" for n in range(_ORPHAN_TOLERANCE, 40)}

        assert _check(tmp_path, on_disk, referenced, monkeypatch) == []

    def test_a_table_with_no_data_directory(self, tmp_path, monkeypatch):
        """A table that has never been written. Ordinary on a first
        run."""
        report = _Report()
        _check_for_orphaned_data_files(_Catalog(), tmp_path, {"p.t"},
                                        report)

        assert report.problems == []


class TestTheTolerance:
    def test_it_is_small_but_not_zero(self):
        assert 0 < _ORPHAN_TOLERANCE <= 10

    @pytest.mark.parametrize("extra", [1, 5, 20])
    def test_growth_beyond_it_is_always_reported(self, tmp_path, monkeypatch,
                                                  extra):
        on_disk = [f"{n}.parquet" for n in range(_ORPHAN_TOLERANCE + 1 + extra)]

        assert _check(tmp_path, on_disk, set(), monkeypatch) != []
