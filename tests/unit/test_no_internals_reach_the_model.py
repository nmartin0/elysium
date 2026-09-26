"""
What the agent is told, and what it is not (OPEN_RISKS item 5).

THE RISK AS RECORDED: visible_schema() carries binding keys -- the
silo, the table, the column, and the table a link is resolved through
-- and it is what the agent's system prompt is built from. A model
told your column names can repeat them, and a model is not a
confidential channel.

WHAT AUDITING IT FOUND: the keys are in the in-process dict, and
NEITHER the prompt NOR the API response contains them. The prompt is
assembled from a fixed set of fields rather than by dumping the dict,
and the API's response models filter per field. So the risk was real
in shape and already closed in fact -- and nothing held it closed.

THAT IS WHAT THIS FILE IS. Not a fix: a tripwire. The prompt is edited
often, and the edit that starts printing a whole field dict would be
one line long and invisible in review.

AND THE DICT KEEPS ITS KEYS, deliberately. The mediator reads them to
group multi-storage reads (patch 370 found that stripping them broke
27 integration tests, because visible_schema is fed back in). The
boundary that matters is the PROMPT and the RESPONSE, which is where
these tests sit.
"""

import pytest

from core.intermediate_layer.auth import UserRecord
from core.llm.agent_step_prompt import _build_system_prompt

# Everything that describes where data LIVES rather than what it IS.
BINDING_KEYS = ("via_table", "via_column", "via_target_column", "id_column")
# Names from the shipped deployment that only exist in its plumbing.
INTERNAL_NAMES = ("primary_sql", "gold.", "bronze_", "quarantine_")

ANALYST = UserRecord("u", "us-west", "customer_service")


@pytest.fixture
def agent_schema(synced_deployment):
    from core.deployment_loader import build_generation

    generation = build_generation(synced_deployment.config_dir,
                                   synced_deployment.data_dir,
                                   synced_deployment.log_dir)
    return generation.mediator.visible_schema(ANALYST, for_agent=True)


class TestThePrompt:
    def test_it_names_no_binding_key(self, agent_schema):
        prompt = _build_system_prompt(agent_schema, [], False, {})

        for key in BINDING_KEYS:
            assert key not in prompt, f"the prompt told the model about {key}"

    def test_it_names_no_silo_or_lake_table(self, agent_schema):
        """A silo name is the operator's word for a database, and a
        lake namespace is Elysium's own plumbing. Neither helps a model
        answer a question about customers."""
        prompt = _build_system_prompt(agent_schema, [], False, {})

        for name in INTERNAL_NAMES:
            assert name not in prompt, f"the prompt told the model about {name}"

    def test_but_it_DOES_name_the_ontology(self, agent_schema):
        """The control on the two above: a prompt that said nothing
        would pass them and be useless."""
        prompt = _build_system_prompt(agent_schema, [], False, {})

        assert "Customer" in prompt
        assert "region" in prompt

    def test_the_source_table_name_is_not_in_it(self, agent_schema, synced_deployment):
        """`customers` is what the customer's database calls it. The
        ontology calls the type Customer, and that is what the model
        should know -- a distinction that only matters when the two
        differ, which is most real deployments."""
        prompt = _build_system_prompt(agent_schema, [], False, {})

        assert "FROM customers" not in prompt
        assert "table" not in prompt.lower().split("available object types")[0]


class TestTheDictItself:
    def test_it_still_carries_what_the_MEDIATOR_needs(self, agent_schema):
        """NOT A LEAK, and deliberately unchanged: the mediator reads
        these to group a multi-storage read, and patch 370 found that
        stripping them broke 27 integration tests. The boundary is the
        prompt, not the dict."""
        link = agent_schema["Customer"]["fields"]["transactions"]

        assert link["target"] == "Transaction"

    def test_and_a_field_the_user_cannot_read_is_absent_entirely(self, synced_deployment):
        """The older guarantee this file sits beside: for_agent drops
        unreadable fields, because a field the model cannot read is one
        it cannot use -- and naming it invites an attempt."""
        from core.deployment_loader import build_generation

        generation = build_generation(synced_deployment.config_dir,
                                       synced_deployment.data_dir,
                                       synced_deployment.log_dir)
        stranger = UserRecord("s", "us-west", "nobody")

        schema = generation.mediator.visible_schema(stranger, for_agent=True)

        assert schema == {}
