"""
The MAC pushdown guard still distinguishes storages on gold
(OPEN_RISKS item 4, "the one genuinely dangerous line in GOLD-3").

THE RISK AS RECORDED:

    TODAY it reads: same adapter, and `security_config["storage"] !=
    searched_config["storage"]` returns None -- "same silo AND same
    table", because a column name means nothing outside one table.
    ON GOLD every type is one table in one namespace, so that
    comparison stops distinguishing anything.

MEASURED, AND THE PREMISE IS OUT OF DATE. `gold_view.py` rebinds each
type to its OWN table:

    rebound["storage"] = {"silo": GOLD_NAMESPACE,
                          "table": object_type, ...}

So `gold.Customer` and `gold.SupportCase` are different storages, and
the comparison distinguishes them exactly as it does two tables in one
silo. The entry was written when "one namespace" was read as "one
table"; one namespace holds one table per type.

WHAT THE RISK WAS RIGHT ABOUT, and these tests pin it: a lost guard
pushes a column name into a table that may hold a different column of
the same name, and the query silently DROPS rows the user is entitled
to -- a silent DENIAL, not a silent grant, because `check_access()`
runs per candidate id after the read whatever the pushdown does.

ITS OWN STEP 4 WAS "a CONTROL: remove the comparison entirely and
confirm the tests fail. A security test that passes when the check is
gone is not a test." That control is run against these.

WHAT IS STILL NOT DONE is its step 2, re-keying the comparison to
"same object type". These tests say why it is not urgent rather than
doing it: the entry asked for "a second pair of eyes before it
merges", and measuring first is what makes that review cheap.
"""

from core.ontology.gold_view import GOLD_NAMESPACE, build_gold_view


class TestGoldKeepsOneTablePerType:
    def test_two_types_get_different_storage(self):
        """THE MEASUREMENT THE RISK TURNS ON. If gold put every type in
        one table the guard would stop distinguishing; it does not."""
        types = {
                "Customer": {"id_field": "customer_id",
                              "fields": {"customer_id": {"data_type": "string"},
                                          "region": {"data_type": "string"}}},
                "SupportCase": {"id_field": "case_id",
                                 "fields": {"case_id": {"data_type": "string"},
                                             "region": {"data_type": "string"}}},
        }

        rebound = build_gold_view(types)[0]

        assert rebound["Customer"]["storage"]["table"] == "Customer"
        assert rebound["SupportCase"]["storage"]["table"] == "SupportCase"
        assert (rebound["Customer"]["storage"]
                != rebound["SupportCase"]["storage"])

    def test_they_share_only_the_namespace(self):
        """One namespace, one table per type -- which is what the
        original entry read as 'one table'."""
        types = {
                "A": {"id_field": "a_id",
                       "fields": {"a_id": {"data_type": "string"}}},
                "B": {"id_field": "b_id",
                       "fields": {"b_id": {"data_type": "string"}}},
        }

        rebound = build_gold_view(types)[0]

        assert rebound["A"]["storage"]["silo"] == GOLD_NAMESPACE
        assert rebound["B"]["storage"]["silo"] == GOLD_NAMESPACE

    def test_a_same_named_field_on_two_types_stays_separable(self):
        """`region` on Customer and `region` on SupportCase are
        different columns in different tables, and the guard compares
        the whole storage block rather than the column name."""
        types = {
                "Customer": {"id_field": "customer_id",
                              "fields": {"customer_id": {"data_type": "string"},
                                          "region": {"data_type": "string"}}},
                "SupportCase": {"id_field": "case_id",
                                 "fields": {"case_id": {"data_type": "string"},
                                             "region": {"data_type": "string"}}},
        }

        rebound = build_gold_view(types)[0]
        customer, case = rebound["Customer"], rebound["SupportCase"]

        assert "region" in customer["fields"]
        assert "region" in case["fields"]
        assert customer["storage"]["table"] != case["storage"]["table"]


class TestTheComparisonIsStillThere:
    def test_the_guard_compares_whole_storage_blocks(self):
        """THE REGRESSION TEST for the line the risk names. Comparing
        the column name, or the silo alone, would pass on gold and let
        a MAC filter reach a table that never held that column."""
        from pathlib import Path

        source = Path("core/ontology/mediator.py").read_text()

        assert ('security_config["storage"] != searched_config["storage"]'
                in source)

    def test_and_that_the_adapter_check_precedes_it(self):
        """Two silos on different adapters cannot share a pushdown at
        all, and that is checked first."""
        from pathlib import Path

        source = Path("core/ontology/mediator.py").read_text()
        i = source.index("if searched_adapter is not security_adapter:")
        j = source.index('security_config["storage"] != searched_config')

        assert i < j
