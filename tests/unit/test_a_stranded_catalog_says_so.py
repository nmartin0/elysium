"""
A catalog pointing at metadata that is not there REFUSES, and names
the repair (BACKLOG.md, "a catalog commit and its metadata write are
not atomic").

WHAT HAPPENS WITHOUT THIS. Iceberg commits in two steps -- write the
metadata file, then swap the catalog's pointer to it -- and SQLite
fsyncs the pointer while pyiceberg's metadata write is unsynced. A
full disk or a power loss between them strands the table: the catalog
names a file that never landed.

BACKLOG.md recorded it as the most serious thing its audit turned up,
and asked for the sync to "fail when the catalog and warehouse
disagree, rather than reporting 0/2 with no explanation."

IT WAS WORSE THAN 0/2. Measured on a real mirror by deleting the
current metadata file: the failure happened inside
`_snapshot_ids_from_catalog` during DEPLOYMENT LOAD, before any table
was touched, so the operator got a bare pyarrow traceback and NOT ONE
TABLE SYNCED -- including every healthy one.

AND THE REMEDY ALREADY EXISTED. `scripts/repair_catalog.py` was
written for this exact failure, and nothing pointed at it from the
place the failure surfaces. Measured end to end afterwards: the
refusal names the repair, the repair repoints the table, and the next
sync reports 2/2.

WHY A SEPARATE EXCEPTION TYPE. Nothing else raises it, and its remedy
is a specific command. A bare OSError would have to be told apart from
every other IO failure by reading its message.
"""

import pytest

from core.deployment_loader import MirrorCatalogStranded


class TestTheExceptionItself:
    def test_it_is_an_oserror(self):
        """The failure IS an IO failure, so anything already catching
        OSError around a load keeps working."""
        assert issubclass(MirrorCatalogStranded, OSError)

    def test_it_is_not_merely_an_oserror(self):
        """A caller that wants to offer the repair must be able to
        tell this apart from a permissions problem."""
        assert MirrorCatalogStranded is not OSError


class TestWhatTheMessageHasToCarry:
    @pytest.fixture
    def message(self):
        return str(MirrorCatalogStranded(
            "primary_sql.customers: the mirror's catalog points at metadata "
            "that is not on disk (missing). This happens when a write was "
            "interrupted -- a full disk, or a power loss -- between writing "
            "the metadata and swapping the pointer to it.\n\n"
            "To see what is stranded, and then repair it:\n"
            "    python -m scripts.repair_catalog\n"
            "    python -m scripts.repair_catalog --write\n\n"
            "Bronze and silver can also be rebuilt from source. THE CHANGELOG "
            "CANNOT: it is the one layer nothing can derive again, so repair "
            "before rebuilding."))

    def test_it_names_the_table(self, message):
        assert "primary_sql.customers" in message

    def test_it_names_the_repair_command(self, message):
        """The tool existed before the exception did. The whole point
        of this patch is that the failure now reaches it."""
        assert "scripts.repair_catalog" in message

    def test_it_offers_the_dry_run_first(self, message):
        """`--write` repoints a table and loses the commits recorded
        only in the missing file, so the reporting run comes first."""
        assert message.index("repair_catalog\n") < message.index("--write")

    def test_it_warns_that_the_changelog_cannot_be_rebuilt(self, message):
        """Bronze and silver are derivable and the changelog is not --
        so 'just delete the mirror and re-sync' is the one piece of
        advice that must not be followed first."""
        assert "CHANGELOG CANNOT" in message


class TestTheSyncPresentsItAsARefusal:
    def test_run_sync_catches_it(self):
        """Not a traceback. The message already names the table, the
        cause and the command; pyarrow frames above it bury all
        three."""
        from pathlib import Path

        source = Path("scripts/run_sync.py").read_text()

        assert "except MirrorCatalogStranded" in source

    def test_and_exits_non_zero(self):
        from pathlib import Path

        source = Path("scripts/run_sync.py").read_text()
        window = source[source.index("except MirrorCatalogStranded"):]

        assert "sys.exit(1)" in window[:400]


class TestTheLoaderRaisesIt:
    def test_a_missing_metadata_file_is_turned_into_this(self):
        from pathlib import Path

        source = Path("core/deployment_loader.py").read_text()
        window = source[source.index("def _snapshot_ids_from_catalog"):]

        assert "except (FileNotFoundError, OSError)" in window[:2000]
        assert "raise MirrorCatalogStranded" in window[:2500]

    def test_a_table_that_never_synced_is_still_skipped(self):
        """NoSuchTable is not a stranded catalog -- it is a table that
        has not been written yet, which is ordinary on a first run."""
        from pathlib import Path

        source = Path("core/deployment_loader.py").read_text()
        window = source[source.index("def _snapshot_ids_from_catalog"):]

        assert "except (NoSuchTableError, NoSuchNamespaceError)" in window[:1200]
        assert "continue" in window[:1200]
