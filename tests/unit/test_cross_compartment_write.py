"""
An action may not carry data across a security compartment.

THE GAP THIS CLOSES. Every MAC check in this codebase compares an
object to the USER. Nothing compared two OBJECTS -- so an analyst
cleared for two compartments could read one and write the other, and
every individual check passed.

THE BELL-LAPADULA \\*-PROPERTY is the name for what was missing: "no
write down". It is about the FLOW rather than about either end of it,
which is why per-object authorization cannot see it.

COMPARTMENTS, NOT LEVELS. A Bell-LaPadula label is a pair -- a
sensitivity LEVEL and a set of COMPARTMENTS -- and dominance is
`S1 <= S2 and C1 subset-of C2`. Elysium's values (`us-east`,
`us-west`) are compartments: disjoint, unranked.

FOUNDRY MAKES THE SAME SPLIT and ships only one by default. Markings
are compartments -- "a user must be a member of ALL Markings applied
to a resource". Classification-based Access Controls are levels, are
off by default, and "can not be used together with markings... on the
same mandatory control property".

AND DEFERRING LEVELS COSTS NO EXPRESSIVENESS: a level hierarchy is a
chain of nested compartment sets, `{secret}` inside `{secret,
topsecret}`.
"""


import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import _compartment_crossings

EAST = UserRecord(user_id="e", security_value="us-east", role_name="agent")


class TestItFindsTheCrossing:
    def test_reading_one_compartment_and_writing_another(self):
        crossings = _compartment_crossings(
            {("Customer", "c1"): "us-east"},
            {("Transaction", "t1"): "us-west"},
        )

        assert len(crossings) == 1

    def test_it_says_which_object_went_where(self):
        """A REFUSAL THAT CANNOT SAY WHICH OBJECT went where is one
        nobody can act on."""
        (read_type, read_id, read_label,
         write_type, write_id, write_label), = _compartment_crossings(
            {("Customer", "c1"): "us-east"},
            {("Transaction", "t1"): "us-west"},
        )

        assert (read_type, read_id, read_label) == ("Customer", "c1", "us-east")
        assert (write_type, write_id, write_label) == (
            "Transaction", "t1", "us-west")

    def test_one_crossing_among_several_reads_is_enough(self):
        crossings = _compartment_crossings(
            {("Customer", "c1"): "us-west", ("Customer", "c2"): "us-east"},
            {("Transaction", "t1"): "us-west"},
        )

        assert len(crossings) == 1


class TestItAllowsWhatItShould:
    def test_the_same_compartment_is_not_a_crossing(self):
        assert _compartment_crossings(
            {("Customer", "c1"): "us-west"},
            {("Transaction", "t1"): "us-west"},
        ) == []

    def test_an_unlabelled_source_cannot_leak(self):
        """AN OBJECT WITH NO SECURITY VALUE is one the ontology
        declared as needing none -- it has no compartment to carry."""
        assert _compartment_crossings(
            {("Customer", "c1"): None},
            {("Transaction", "t1"): "us-west"},
        ) == []

    def test_an_unlabelled_target_is_not_a_crossing(self):
        assert _compartment_crossings(
            {("Customer", "c1"): "us-east"},
            {("Transaction", "t1"): None},
        ) == []

    def test_an_action_that_read_nothing_writes_freely(self):
        """A CREATE READS NO OBJECT, so it carries nothing. The
        per-object check still governs whether the caller may write at
        all."""
        assert _compartment_crossings({}, {("Transaction", "t1"): "us-west"}) == []


class TestItGeneralisesToSets:
    def test_equality_is_todays_containment(self):
        """ELYSIUM'S LABELS ARE SINGLE COMPARTMENTS, so containment
        reduces to equality -- and that is what the check does. When a
        label becomes a SET, `!=` becomes "not a superset" and nothing
        else moves.

        This test pins the property rather than the implementation:
        identical labels pass, different ones do not.
        """
        assert _compartment_crossings(
            {("A", "1"): "x"}, {("B", "2"): "x"}) == []
        assert _compartment_crossings(
            {("A", "1"): "x"}, {("B", "2"): "y"}) != []


class TestTheRefusalType:
    def test_it_is_not_an_authorization_error(self):
        """EVERY INDIVIDUAL CHECK PASSED. The caller may read the
        source and may write the target; what is refused is the
        COMBINATION, and a PermissionError would send somebody looking
        at grants that are perfectly correct.
        """
        from core.ontology.write_mediator import CrossCompartmentWrite

        assert issubclass(CrossCompartmentWrite, ValueError)
        assert not issubclass(CrossCompartmentWrite, PermissionError)


class TestACreateIsAWriteToo:
    """SEC-28: a create carries data into a compartment exactly as an
    update does. It was left out of the write set because it has no row
    to read a label from; its label is the one it SETS."""

    @pytest.fixture
    def propose(self, tmp_path):
        import sqlite3

        from adapters.sqlite_adapter import SQLiteReadAdapter, SQLiteWriteAdapter
        from core.ontology.mediator import DataMediator
        from core.ontology.write_log import WriteLogWriter
        from core.ontology.write_mediator import WriteMediator

        schema = {"Ticket": {
            "id_field": "id", "security": {"field": "region"},
            "storage": {"silo": "p", "table": "t", "id_column": "id"},
            "fields": {"id": {"type": "data"}, "status": {"type": "data"},
                       "region": {"type": "data"}},
        }}
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, status TEXT, region TEXT)")
        conn.execute("INSERT INTO t VALUES ('t-east','open','us-east')")
        conn.commit()
        conn.close()

        def build(region_value):
            mutations = [{"set": {"property": "id", "value": "parameter.new_id"}},
                         {"set": {"property": "status", "value": "open"}}]
            if region_value is not None:
                mutations.append({"set": {"property": "region", "value": region_value}})
            actions = {"follow_up": {
                "display_name": "Follow up", "description": "d",
                "affected_object_types": ["Ticket"],
                "parameters": {
                    "ticket": {"type": "object_reference", "object_type": "Ticket"},
                    "new_id": {"type": "string"}},
                "sub_writes": [{"operation": "create", "object_type": "Ticket",
                                 "object_id": "parameter.new_id", "mutations": mutations}],
            }}
            roles = {"agent": {"allowed_actions": frozenset(
                ["execute:follow_up", "read:Ticket", "read:Ticket.status",
                 "read:Ticket.region", "read:Ticket.id"])}}
            mediator = DataMediator(schema, {"p": SQLiteReadAdapter({"path": source})},
                                     {"Ticket": "p"}, roles,
                                     write_log=WriteLogWriter(tmp_path / "wl.db"))
            writer = WriteMediator(mediator, {"p": SQLiteWriteAdapter({"path": source})},
                                    roles, actions, 1)
            return writer.propose_action(EAST, "follow_up",
                                         {"ticket": "t-east", "new_id": "t-new"},
                                         origin="human")
        return build

    def test_reading_one_compartment_and_creating_in_another_is_refused(self, propose):
        from core.ontology.write_mediator import CrossCompartmentWrite

        with pytest.raises(CrossCompartmentWrite, match="t-east.*us-east.*t-new.*us-west"):
            propose("us-west")

    def test_creating_in_the_compartment_it_read_is_allowed(self, propose):
        assert propose("us-east").sub_writes[0].changes["region"] == "us-east"

    def test_the_proposers_own_compartment_is_allowed(self, propose):
        assert propose("user.security_value").sub_writes[0].changes["region"] == "us-east"

    def test_a_create_that_sets_no_compartment_carries_nothing_out(self, propose):
        """Unlabelled: visible to nobody, so nothing written leaks."""
        assert "region" not in propose(None).sub_writes[0].changes
