"""
No pipeline rule may change who can see a row (found by LLM3).

WHAT WAS HAPPENING. Silver standardises every declared text field --
NFC, trim, collapse whitespace -- and it did that to the SECURITY
FIELD too. A customer whose source `region` is "us-west " (a trailing
space, the sort a CSV import leaves behind):

    LIVE   read: {'name': None}    -- invisible
    MIRROR read: {'name': 'Ada'}   -- VISIBLE

The same user, the same row, two answers. A whitespace-cleaning rule
moved an access boundary, with no audit entry and no approval --
because to the pipeline, "correct a typo" and "widen access" are the
same operation.

THE DECISION WAS ALREADY MADE, FOR TYPE COERCION, and written down in
UNIFIED_ROADMAP.md:

    THE SECURITY-VALUE PATH IS DELIBERATELY EXCLUDED -- it is compared
    for equality against the user's own, and changing the
    representation of one side of the comparison that decides
    authorization is not worth tidying a region name for.

Standardisation was built later and did not carry it across. So this
is not a new policy: it is an existing one reaching a feature that
grew up after it.

WHAT THIS DOES NOT COVER, said plainly because the next reader will
assume otherwise:

  - a type whose security is reached through a link (`via_field`) has
    no security column of its own here, so nothing is excluded for it
  - expectations, quarantine and the duplicate policy can still act on
    a security column -- a row QUARANTINED for a bad region is a row
    nobody can see
  - the general principle ("the security attribute is not ordinary
    data") is unenforced; this closes the one path that was measurably
    moving access

Those are recorded for the owner. This fixes what was live.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.intermediate_layer.auth import UserRecord
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.mirror_adapter import MirrorReadAdapter
from core.mirror.sync_targets import resolve_sync_targets
from core.ontology.mediator import DataMediator

SCHEMA = {
    "Customer": {
        "id_field": "id", "security": {"field": "region"},
        "storage": {"silo": "p", "table": "customers", "id_column": "id"},
        "fields": {"id": {"type": "data"}, "name": {"type": "data"},
                    "region": {"type": "data"}},
    }
}
USER = UserRecord(user_id="u", security_value="us-west", role_name="r")


@pytest.fixture
def both_paths(tmp_path):
    def build(region_value):
        source = tmp_path / f"s{abs(hash(region_value))}.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT, "
                     "region TEXT)")
        conn.execute("INSERT INTO customers VALUES ('c1','Ada',?)", (region_value,))
        conn.commit()
        conn.close()
        target = resolve_sync_targets({"object_types": SCHEMA})[0]
        sync = IcebergMirrorSync(tmp_path / f"m{abs(hash(region_value))}",
                                  {"p": SQLiteReadAdapter({"path": source})})
        sync.sync_table(target.silo_name, target.table_name, target.id_column,
                        target.columns, target.column_types,
                        target.fields_by_column, target.standardisation,
                        target.expectations, target.duplicate_policy,
                        target.object_types, target.link_pair)
        grants = ["read:Customer"] + [f"read:Customer.{f}"
                                       for f in SCHEMA["Customer"]["fields"]]
        roles = {"r": {"allowed_actions": grants}}
        return {
            "live": DataMediator(SCHEMA, {"p": SQLiteReadAdapter({"path": source})},
                                  {"Customer": "p"}, roles),
            "mirror": DataMediator(SCHEMA, {"p": MirrorReadAdapter(sync.catalog, "p")},
                                    {"Customer": "p"}, roles),
            "sync": sync,
        }
    return build


class TestTheTwoPathsAgreeAboutVisibility:
    @pytest.mark.parametrize("region", [
        "us-west ", " us-west", "us-west\t", "us west", "us-west",
    ])
    def test_whatever_whitespace_the_source_holds(self, both_paths, region):
        """THE REGRESSION TEST. The mirror must not make a row visible
        that the source does not."""
        paths = both_paths(region)

        live = paths["live"].get_object(USER, "Customer", "c1", ["name"])
        mirror = paths["mirror"].get_object(USER, "Customer", "c1", ["name"])

        assert mirror == live

    def test_a_trailing_space_keeps_the_row_invisible(self, both_paths):
        """Named explicitly because this is the measured case: silver
        used to trim it and hand the row over."""
        paths = both_paths("us-west ")

        assert paths["mirror"].get_object(USER, "Customer", "c1",
                                           ["name"]) == {"name": None}

    def test_an_exact_match_is_still_visible(self, both_paths):
        """The fix must not hide rows that should be seen."""
        paths = both_paths("us-west")

        assert paths["mirror"].get_object(USER, "Customer", "c1",
                                           ["name"]) == {"name": "Ada"}


class TestTheSecurityColumnIsStoredAsFound:
    def test_silver_holds_the_source_value_exactly(self, both_paths):
        paths = both_paths("us-west ")

        stored = paths["sync"].catalog.load_table("p.customers") \
            .scan().to_arrow().to_pylist()[0]["region"]

        assert stored == "us-west "

    def test_other_columns_are_still_standardised(self, both_paths):
        """The exclusion is narrow. Everything else still gets the
        tidying it was built for."""
        target = resolve_sync_targets({"object_types": SCHEMA})[0]

        assert "region" not in target.standardisation
        assert sorted(target.standardisation) == ["id", "name"]


class TestWhatIsStillOpen:
    def test_a_via_field_type_has_no_local_security_column(self):
        """RECORDED, NOT FIXED. A type whose security is reached
        through a link has no security column here, so nothing is
        excluded for it -- and its target's column is excluded on the
        TARGET's own type. Pinned so the gap is visible rather than
        assumed closed."""
        schema = {"Order": {
            "id_field": "id",
            "security": {"via_field": "customer", "field": "region"},
            "storage": {"silo": "p", "table": "orders", "id_column": "id"},
            "fields": {"id": {"type": "data"}, "note": {"type": "data"}},
        }}

        target = resolve_sync_targets({"object_types": schema})[0]

        # `note` is standardised; there is no local security column to
        # exclude. This is the documented limit, not a passing fix.
        assert "note" in target.standardisation
