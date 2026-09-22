"""
Silver canonicalises values without changing what they mean (GOLD-1's
first stage, MEDALLION_PIPELINE.md's S1).

THE LINE, from the research: NFC and whitespace cleanup are the
conservative baseline; case folding and stripping accents are
aggressive and lose information. So nothing here can change an answer
-- the aggressive normalisations belong to gold's match keys, as
separate columns, never replacing a value.

Sentinels ("N/A", "-", "") are DECLARED per field: only the deployment
knows what its sources write for "nothing", and a sentinel left as text
sorts, matches and aggregates as though somebody wrote it down.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.standardise import rules_for, standardise
from core.mirror.sync_targets import resolve_sync_targets
from core.mirror.transform import transform_rows

DEFAULTS = rules_for({})
WITH_SENTINELS = rules_for({"standardise": {"null_if": ["N/A", "", "-"]}})


class TestWhatIsAppliedToEveryString:
    @pytest.mark.parametrize("value, expected", [
        ("  Ada  ", "Ada"),
        ("Ada   Lovelace", "Ada Lovelace"),
        ("\tAda\nLovelace ", "Ada Lovelace"),
        ("cafe\u0301", "caf\u00e9"),          # decomposed -> composed
        ("caf\u00e9", "caf\u00e9"),           # already composed
    ])
    def test_canonical_form(self, value, expected):
        assert standardise(value, DEFAULTS) == expected

    @pytest.mark.parametrize("value", ["Ada", "ADA", "us-west", "O'Brien", "Ba\u00dfstra\u00dfe"])
    def test_what_it_leaves_alone(self, value):
        """Case, punctuation and letters carry meaning."""
        assert standardise(value, DEFAULTS) == value

    def test_non_strings_and_null_pass_through(self):
        assert standardise(42, DEFAULTS) == 42
        assert standardise(None, DEFAULTS) is None


class TestDeclaredSentinels:
    @pytest.mark.parametrize("value", ["N/A", " N/A ", "", "   ", "-"])
    def test_a_declared_sentinel_becomes_a_real_null(self, value):
        """Cleaned FIRST, so ' N/A ' counts as the sentinel it is."""
        assert standardise(value, WITH_SENTINELS) is None

    def test_matching_is_exact_never_case_insensitive(self):
        """'null' as a sentinel must not delete the surname Null."""
        rules = rules_for({"standardise": {"null_if": ["null"]}})
        assert standardise("Null", rules) == "Null"

    def test_nothing_is_a_sentinel_unless_declared(self):
        assert standardise("N/A", DEFAULTS) == "N/A"


class TestDeclaringTheRules:
    def test_a_field_can_opt_out(self):
        assert rules_for({"standardise": False}) is None
        assert standardise("  kept  ", rules_for({"standardise": False})) == "  kept  "

    @pytest.mark.parametrize("bad, message", [
        ({"standardise": {"trimm": True}}, "unknown standardise rule"),
        ({"standardise": {"unicode": "NFZ"}}, "standardise.unicode"),
        ({"standardise": {"null_if": "N/A"}}, "must be a list"),
        ({"standardise": 3}, "mapping of rules or false"),
    ])
    def test_a_typo_fails_rather_than_doing_nothing(self, bad, message):
        with pytest.raises(ValueError, match=message):
            rules_for(bad)

    def test_the_rules_reach_the_sync_target(self):
        schema = {"object_types": {"Customer": {
            "id_field": "customer_id",
            "storage": {"silo": "s", "table": "customers", "id_column": "customer_id"},
            "security": {"field": "region"},
            "fields": {"region": {"type": "data"},
                       "raw": {"type": "data", "standardise": False}},
        }}}

        target = resolve_sync_targets(schema)[0]

        assert "region" in target.standardisation and "raw" not in target.standardisation

    def test_a_bad_rule_names_the_field(self):
        schema = {"object_types": {"Customer": {
            "id_field": "customer_id",
            "storage": {"silo": "s", "table": "customers", "id_column": "customer_id"},
            "security": {"field": "region"},
            "fields": {"region": {"type": "data", "standardise": {"nope": 1}}},
        }}}

        with pytest.raises(ValueError, match="Field 'region'"):
            resolve_sync_targets(schema)


class TestThroughTheTransform:
    def test_standardised_before_coercion(self):
        """Trimming ' 42 ' is what lets it coerce as an integer."""
        result = transform_rows([{"n": " 42 "}], ["n"], {"n": "integer"},
                                {"n": DEFAULTS})

        assert not result.has_drift
        assert result.rows[0]["n"] == 42

    def test_a_declared_sentinel_is_a_null_not_drift(self):
        """Left as text, 'N/A' fails to coerce and reads as schema
        drift -- the source blamed for a convention it declared."""
        result = transform_rows([{"n": "N/A"}], ["n"], {"n": "integer"},
                                {"n": WITH_SENTINELS})

        assert not result.has_drift
        assert result.rows[0]["n"] is None

    def test_without_the_rules_nothing_changes(self):
        result = transform_rows([{"s": "  kept  "}], ["s"], {"s": "string"})

        assert result.rows[0]["s"] == "  kept  "


def test_a_messy_source_value_arrives_canonical(tmp_path):
    """END TO END through a real source and a real sync."""
    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1', '  Ada   Lovelace  ')")
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": source})})
    sync.sync_table("primary", "customers", "customer_id", ["customer_id", "name"],
                    {"customer_id": "string", "name": "string"},
                    standardisation={"name": DEFAULTS})

    rows = sync._catalog.load_table("primary.customers").scan().to_arrow().to_pylist()
    assert rows[0]["name"] == "Ada Lovelace"
