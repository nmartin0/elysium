"""
READS COME FROM GOLD (GOLD-8), so the reader being observed here is
the gold connector rather than the mirror adapter. The pushdown
machinery is the same -- it is shared, in iceberg_reader.py -- and
what this file tests is which CONDITIONS reach it.

The MAC filter reaches the query where the ontology lets it.

THE CANONICAL NAME IS PREDICATE PUSHDOWN, and what cannot be pushed is
the RESIDUAL predicate, applied after the read. Row-level security is
the same idea stated as "an enforced, invisible WHERE clause".

WHY IT MATTERS HERE: `search_object` fetched every matching id and
filtered afterwards. Measured on a 200,000-row table: 0.70s and 66MB,
extrapolating to ~35s and ~3.3GB for ten million rows -- per request,
before any filtering. Pushed down, the database returns only rows the
user may see, so a row limit becomes CORRECT rather than a guess.

`field:` IS PUSHABLE -- the value is a column of this table.
`via_field:` IS NOT -- it is reached by following a link, possibly
into another silo.

THAT SPLIT IS A KNOWN HAZARD RATHER THAN A LOCAL LIMITATION: the field
guidance for row-level security is "keep predicates join-free", and
Databricks' SecureView barrier forces full scans for the same reason.
"""

from unittest.mock import patch

import pytest

from core.intermediate_layer.auth import UserRecord
from core.mirror.gold_connector import GoldConnector


@pytest.fixture
def generation(synced_deployment):
    """A SYNCED deployment, because reads come from gold (GOLD-8).

    It used to build one over a fresh data directory and read the
    SOURCE adapters directly -- which is the path this change
    removed, so there is nothing to read until a sync has run."""
    from core.deployment_loader import build_generation

    paths = synced_deployment  # E-08: never the developer's deployment
    return build_generation(paths.config_dir, paths.data_dir, paths.log_dir)


def _conditions_reaching_the_adapter(generation, object_type, user):
    seen = []
    real = GoldConnector.find_ids

    def spy(self, name, conditions, type_config, limit=None):
        seen.append([(c.field, c.operator, c.value) for c in conditions])
        return real(self, name, conditions, type_config, limit)

    with patch.object(GoldConnector, "find_ids", spy):
        generation.mediator.search_object(user, object_type, [])
    return seen[0] if seen else []


class TestWhatIsPushed:
    def test_a_direct_field_becomes_a_condition(self, generation):
        user = UserRecord("u", "us-west", "customer_service")

        assert ("region", "equals", "us-west") in _conditions_reaching_the_adapter(
            generation, "Customer", user,
        )

    def test_a_linked_field_is_not(self, generation):
        """`via_field:` resolves by FOLLOWING A LINK, so no single
        query against this table expresses it. The residual filter
        still runs and the answer is the same; only the cost differs."""
        user = UserRecord("u", "us-west", "customer_service")

        assert _conditions_reaching_the_adapter(
            generation, "Transaction", user,
        ) == []

    def test_the_pushed_value_is_the_caller_s_own(self, generation):
        # A pushed predicate carrying the WRONG value would be a
        # security bug wearing an optimisation's clothes.
        user = UserRecord("u", "us-east", "customer_service")

        assert ("region", "equals", "us-east") in _conditions_reaching_the_adapter(
            generation, "Customer", user,
        )


class TestTheAnswerIsUnchanged:
    def test_pushing_does_not_change_what_a_user_sees(self, generation):
        """THE PROPERTY THAT MATTERS. Pushdown is an optimisation; if
        it altered the result set it would be a defect, however much
        faster."""
        west = UserRecord("w", "us-west", "customer_service")
        east = UserRecord("e", "us-east", "customer_service")

        west_ids = set(generation.mediator.search_object(west, "Customer", []))
        east_ids = set(generation.mediator.search_object(east, "Customer", []))

        # DISJOINT, NOT NON-EMPTY. The fixture builds against a FRESH
        # data directory, so the mirror is empty and both sets are too
        # -- a first version asserted `west_ids` truthy and failed for
        # that reason rather than for a real one.
        #
        # Disjointness is the property pushdown must preserve, and it
        # holds whether or not there is data: two partitions never
        # share an id.
        assert not (west_ids & east_ids)
        assert all(
            generation.mediator._pushable_security_column(
                "Customer", *generation.mediator._resolve_shared_storage("Customer", []),
            ) == "region"
            for _ in (west, east)
        )


class TestWhereItRefusesToPush:
    def test_an_mdo_security_column_in_another_table_is_not_pushed(self, generation):
        """WITH MDO AN OBJECT TYPE SPANS SEVERAL STORAGES, and which
        one a search routes to depends on the fields it filters on.

        A first version resolved the "searched" storage itself and got
        the DEFAULT one, producing `WHERE region = ?` against a table
        with no such column. Three MDO tests failed outright. The
        caller passes its own routed config now.
        """
        mediator = generation.mediator
        adapter, config = mediator._resolve_shared_storage("Customer", [])

        assert mediator._pushable_security_column("Customer", adapter, config)

        # A different storage must refuse, whatever the column is named.
        other = {**config, "storage": {**config["storage"], "table": "elsewhere"}}
        assert mediator._pushable_security_column("Customer", adapter, other) is None
