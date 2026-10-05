"""
The value that decides who may see a row is copied once, into a column
no pipeline stage rewrites.

`LLM3-3` asks where the security attribute should live. The risk is
that the pipeline rewrites it, and that was measured, not theorised:
silver standardised every column including that one, so a region of
`"N/A"` became None and the object belonged to NO compartment, and
`" us-west "` became `"us-west"` and stopped matching a caller whose
own value kept its spacing.

Exempting the column fixed the one stage that existed. THE RULE DOES
NOT TRAVEL -- enrichment, redaction, anything added later has to know
it exists, and the owner confirmed more stages are coming. The
precedent names where that ends: "the sheer number of derived
datasets, and derived columns therein, makes manual propagation of
column metadata prohibitive", and specifically "confirm that
classification is not only present, but still true after
transformation, export, and enrichment".

SO THE VALUE IS COPIED INTO `_security` AT SYNC, in the namespace
Elysium owns.

WHAT THIS COST, STATED HONESTLY, because the pitch was wrong. I
claimed later stages would inherit the behaviour for free, on the
strength of fusion copying anything that `startswith("_")`. That is
ONE call site. Measured: `_security` reached silver and was absent
from gold entirely. FOUR places name an explicit list -- with_lineage,
gold's conform, gold's schema builder, and the arrow conformer -- and
all four had to be told. They now name one set, `CARRIED_COLUMNS`, so
a fifth stage that copies it is free and a fifth stage that writes its
own list is not.

NOT YET WIRED TO MAC. `_get_security_value` still reads the declared
field. Pointing it at `_security` failed 146 tests -- every fixture
reading an adapter directly, where no sync has run -- and the fallback
needs `_resolve_shared_storage`, which takes FIELD NAMES and which I
twice called wrongly. That half is deliberately separate.
"""

import pytest

from core.carried_columns import (
    CARRIED_COLUMNS,
    LINEAGE_COLUMNS,
    SECURITY_COLUMN,
)
from core.mirror.lineage import with_lineage

ROWS = [{"customer_id": "c1", "region": " us-west ", "name": "Ada"},
        {"customer_id": "c2", "region": "N/A", "name": "Bo"}]
COLUMNS = ["customer_id", "region", "name"]


class TestTheValueIsCopied:
    def test_it_lands_in_the_carried_column(self):
        out = with_lineage(ROWS, COLUMNS, "p", "customers",
                           security_column="region")

        assert out[0][SECURITY_COLUMN] == " us-west "

    def test_it_is_copied_verbatim(self):
        """A sentinel is the deployment's problem to fix. Turning it
        into None makes the row invisible to everyone, which hides the
        problem rather than reporting it."""
        out = with_lineage(ROWS, COLUMNS, "p", "customers",
                           security_column="region")

        assert out[1][SECURITY_COLUMN] == "N/A"

    def test_the_source_column_is_untouched(self):
        """A copy, not a move. The declared field is still the data."""
        out = with_lineage(ROWS, COLUMNS, "p", "customers",
                           security_column="region")

        assert out[0]["region"] == " us-west "

    def test_a_type_with_no_security_field_gets_no_column(self):
        """Most types: one secured through `via_field` reads its value
        from a different type's row."""
        out = with_lineage(ROWS, COLUMNS, "p", "customers")

        assert SECURITY_COLUMN not in out[0]

    def test_the_lineage_columns_are_unaffected(self):
        out = with_lineage(ROWS, COLUMNS, "p", "customers",
                           security_column="region")

        assert out[0]["_silo"] == "p"
        assert out[0]["_source_table"] == "customers"


class TestTheNamedSet:
    def test_the_security_column_is_carried(self):
        assert SECURITY_COLUMN in CARRIED_COLUMNS

    def test_it_is_not_lineage(self):
        """The security value is not provenance, and putting it in
        LINEAGE_COLUMNS would say it was."""
        assert SECURITY_COLUMN not in LINEAGE_COLUMNS

    def test_carried_is_lineage_plus_security(self):
        assert set(CARRIED_COLUMNS) == set(LINEAGE_COLUMNS) | {SECURITY_COLUMN}

    def test_the_names_live_in_a_leaf(self):
        """`core/mirror` writes them and `core/ontology` will read one,
        and the contract forbids ontology reaching into mirror. The
        import linter caught this; it is pinned so the next person does
        not move them back."""
        from pathlib import Path

        source = Path("core/carried_columns.py").read_text()
        imports = [line for line in source.splitlines()
                   if line.startswith(("import ", "from "))]

        assert imports == [], imports


class TestEveryStageNamesTheSet:
    """THE HONEST LIMIT. Four places had to be told, and these pin
    them. A fifth stage that writes its own list is not covered by
    anything here -- that is the cost the side table would not have."""

    @pytest.mark.parametrize("path", [
        "core/mirror/gold.py",
        "core/mirror/gold_arrow.py",
    ])
    def test_the_gold_stages_carry_the_set(self, path):
        from pathlib import Path

        source = Path(path).read_text()

        assert "CARRIED_COLUMNS" in source
        assert "LINEAGE_COLUMNS" not in source, (
            f"{path} still names LINEAGE_COLUMNS, which omits the "
            f"security value")

    def test_the_sync_passes_the_security_column(self):
        from pathlib import Path

        source = Path("core/mirror/iceberg_sync.py").read_text()

        assert "security_column=security_column" in source


class TestConformMatchesTheSchema:
    def test_a_carried_column_is_present_even_when_absent_upstream(self):
        """`if column in row` left the KEY ABSENT while the published
        table reads it back as None. The changelog diffs those dicts,
        so an unchanged row looked like an UPDATE on every publication
        -- four history tests said so the moment `_security` joined the
        set, it being the first carried column that can legitimately be
        missing."""
        from core.mirror.gold import conform

        type_def = {
            "id_field": "customer_id",
            "fields": {"customer_id": {"data_type": "string"}},
            "storage": {"silo": "p", "table": "customers",
                         "id_column": "customer_id"},
        }

        out = conform(type_def, [{"customer_id": "c1"}])

        assert SECURITY_COLUMN in out[0]
        assert out[0][SECURITY_COLUMN] is None
