"""
Bronze and silver expire their snapshots, not just gold (BACKLOG.md
0d4, "snapshot growth, observed September 19").

WHAT WAS WRONG, and it is a shape this project keeps producing:
`BRONZE_RETENTION` declares `history.expire.min-snapshots-to-keep` and
`history.expire.max-snapshot-age-ms` on every bronze table, and
NOTHING EVER CALLED EXPIRY ON THEM. Properties describe what expiry
should do; they do not perform it. Only gold called
`expire_snapshots`.

MEASURED, AND MY FIRST MEASUREMENT WAS WRONG. Six syncs of the dev
deployment left bronze and silver at ELEVEN snapshots each while gold
held six, and I read that as expiry working on gold. It was not --
gold writes once per run where bronze and silver write twice, and with
the seven-day margin NOTHING expires on any layer in a test lasting
seconds.

With the margin shrunk to a millisecond, which is the only way to see
it at all:

    before wiring   bronze 11   silver 11
    bronze wired    bronze  1   silver 11
    both wired      bronze  1   silver  1

WHY IT MATTERS, and it is not disk. Expiry bounds METADATA, not files:
gold's own measurement was 15 snapshots to 3 with the Parquet
untouched. Every generation build loads every table, so an unbounded
metadata.json is paid on every request rather than at sync time.

THE SEVEN-DAY MARGIN IS WHAT MAKES IT SAFE FOR READERS. A request pins
a snapshot id, and only snapshots older than RETENTION_MARGIN_MS are
candidates, so nothing a live request could be holding is eligible.

SILVER EXPIRES ON THE DATA PATH ONLY. The unchanged branch writes a
property and adds no snapshot, so there is nothing new to expire and a
commit there would be pure cost.
"""

from pathlib import Path

from core.mirror.iceberg_sync import RETENTION_MARGIN_MS, expire_unreferenced

SOURCE = Path("core/mirror/iceberg_sync.py").read_text()


def _the_function() -> str:
    """The body of expire_unreferenced.

    ENDS AT THE NEXT TOP-LEVEL STATEMENT, not at the next `def`: what
    follows it is a CLASS, so an end anchor of "\ndef " found nothing
    and this test raised ValueError instead of asserting anything.
    """
    start = SOURCE.index("def expire_unreferenced")
    rest = SOURCE[start:]
    for marker in ("\nclass ", "\ndef "):
        if marker in rest[10:]:
            return rest[:rest.index(marker, 10)]
    return rest


class TestTheHelperIsShared:
    def test_it_lives_beside_the_margin_it_uses(self):
        """It was private to gold.py and imported the margin from
        here. One implementation, one place."""
        assert callable(expire_unreferenced)

    def test_gold_calls_the_shared_one(self):
        gold = Path("core/mirror/gold.py").read_text()

        assert "from core.mirror.iceberg_sync import expire_unreferenced" in gold
        assert "def _expire_unreferenced" not in gold

    def test_gold_keeps_its_import_local(self):
        """It was function-local to avoid a cycle, and moving it to the
        top of the module would reintroduce one."""
        gold = Path("core/mirror/gold.py").read_text()
        i = gold.index("from core.mirror.iceberg_sync import expire_unreferenced")

        assert gold[:i].rstrip().endswith("try:")


class TestBothLayersCallIt:
    def test_bronze_does(self):
        """THE REGRESSION TEST. Bronze declared retention properties
        for months and nothing ran expiry on them."""
        window = SOURCE[SOURCE.index("**BRONZE_RETENTION,"):]

        assert "expire_unreferenced(table)" in window[:2000]

    def test_silver_does(self):
        i = SOURCE.index("BRONZE_SNAPSHOT_PROPERTY: str(bronze_snapshot)")
        window = SOURCE[i:i + 900]

        assert "expire_unreferenced(table)" in window

    def test_silver_does_NOT_on_the_unchanged_path(self):
        """That branch sets a property and adds no snapshot. Expiring
        there is a commit that can only cost."""
        i = SOURCE.index("tx.set_properties(_read_properties(read_started_at,")
        before_else = SOURCE[i:SOURCE.index("else:", i)]

        assert "expire_unreferenced" not in before_else

    def test_all_three_layers_are_covered(self):
        gold = Path("core/mirror/gold.py").read_text()

        # TWO CALL SITES PLUS THE DEFINITION in iceberg_sync, and one
        # call in gold. Counting the bare name would count the def as
        # a third call site -- the mistake patch 466's tests record
        # making with _read_properties.
        # BY WHOLE LINE. Counting the indented string double-counts,
        # because the 16-space form contains the 12-space one -- and
        # counting the bare name counts the `def` as a call site,
        # which is the mistake patch 466's tests record making.
        calls = [line.strip() for line in SOURCE.splitlines()
                 if line.strip() == "expire_unreferenced(table)"]

        assert len(calls) == 2, "bronze and silver, one each"
        assert gold.count("expire_unreferenced(table)") == 1


class TestTheMargin:
    def test_it_is_a_week(self):
        """Long enough that no live request can be holding a snapshot
        old enough to expire."""
        assert RETENTION_MARGIN_MS == 7 * 24 * 60 * 60 * 1000

    def test_expiry_never_raises_through_a_caller(self):
        """Retention is housekeeping. A publish or a sync that already
        succeeded must not be failed by it -- gold's own comment
        records a measured case where it was."""
        window = _the_function()

        assert "except Exception" in window

    def test_a_table_that_cannot_expire_is_only_logged(self):
        window = _the_function()

        assert "logger" in window
        assert "raise" not in window.split("except Exception")[1][:300]


class TestItRuns:
    def test_a_table_that_raises_does_not_raise_through(self):
        """Housekeeping must never fail the write it follows. The stub
        raises from exactly where pyiceberg would."""

        class _Hostile:
            class maintenance:
                @staticmethod
                def expire_snapshots():
                    raise RuntimeError("catalog moved on")

            # THE LOG LINE NAMES THE TABLE, so a stub without this
            # fails inside the handler rather than outside it -- which
            # is how the first version of this test "passed" the wrong
            # thing.
            @staticmethod
            def name():
                return ("p", "t")

        expire_unreferenced(_Hostile())  # must simply return
