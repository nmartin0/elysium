"""A search result carries names beside its ids.

AR-4: a search returns bare ids -- ["cust_001", "cust_002"] -- and the
model has no idea which is which. It spends hops reading names back
one at a time to find out, and an answer built before it does cites an
id at the user.

THE DECLARATION ALREADY EXISTED AND WAS WIRED TO NOTHING.
`title_field` is Palantir's "title key" -- "the property that acts as
a display name for objects of this type" -- validated at schema load
by object_type_validation.py, declared in the SHIPPED deployment as
`title_field: name` on Customer, with a runtime lookup
get_title_field() in schema.py that had ZERO production call sites.
Built, validated, declared, unused.

REAL MEDIATOR, NOT A MOCK. 001AGENTLOOP records that the decimal crash
reached the shipped configuration because agent tests mock the
mediator and hand back floats and strings. Whether a title can be read
is a question about authorisation and real data, so these ask a real
one.
"""

import contextlib
import io

import pytest

from core.agent.agentic_loop import MAX_OBJECT_IDS
from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record

USER_ID = "user_alice"


class Scripted:
    max_concurrent_requests = 1

    def __init__(self, *steps):
        self._steps = list(steps)

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None):
        return self._steps.pop(0) if self._steps else '{"step": "finish"}'


@pytest.fixture
def loop_and_user(synced_deployment):
    generation = build_generation(
        synced_deployment.config_dir,
        synced_deployment.data_dir,
        synced_deployment.log_dir,
    )
    user = resolve_user_record(
        generation.config.users, USER_ID, generation.config.security_attribute
    )
    assert user.role_name is not None, "the fixture user has no role"
    return generation, user


def _run(generation, user, *steps):
    generation.loop.client = Scripted(*steps)
    with contextlib.redirect_stdout(io.StringIO()):
        return generation.loop.run(user, "who are the customers?")


SEARCH_CUSTOMERS = (
    '{"step": "search_object", "object_type": "Customer", '
    '"filter": {"region": "us-west"}}'
)


def test_a_search_result_carries_a_name_for_each_id(loop_and_user):
    generation, user = loop_and_user
    result = _run(generation, user, SEARCH_CUSTOMERS)

    entry = result.gathered[0]
    assert entry["titles"] == {
        "cust_001": "Ada Okafor",
        "cust_002": "Bram Feldman",
    }


def test_the_ids_keep_their_shape(loop_and_user):
    """TITLES SIT BESIDE `result`, NEVER INSIDE IT.

    The model copies ids out of `result` to use as object_id in its
    next step. A list of {"id": ..., "name": ...} objects would invite
    it to pass the whole object where an id belongs -- trading a
    cosmetic problem for a functional one.
    """
    generation, user = loop_and_user
    result = _run(generation, user, SEARCH_CUSTOMERS)

    assert result.gathered[0]["result"] == ["cust_001", "cust_002"]


def test_a_type_with_no_declared_title_gets_no_titles_key(loop_and_user):
    """Transaction declares no title_field in the shipped deployment.

    Degrading to silence rather than to an empty dict or an id-as-name
    keeps "no title declared" distinguishable from "titles were read
    and came back blank".
    """
    generation, user = loop_and_user
    result = _run(
        generation, user,
        '{"step": "search_around", "object_type": "Customer", '
        '"link_field": "transactions", "filter": {"customer_id": "cust_001"}}',
    )

    entry = result.gathered[0]
    assert entry["result"], "the fixture returned no transactions to title"
    assert "titles" not in entry


def test_search_around_titles_the_LINK_TARGET_not_the_step_type(loop_and_user):
    """THE BUG THIS ALMOST SHIPPED WITH.

    search_around("Customer", link_field="transactions") returns
    TRANSACTION ids. Titling them as Customers would look up
    Customer's title_field ("name") and either find nothing or -- far
    worse -- read a field that happens to exist on both types, putting
    one object's value against another object's id.

    ASSERTED ON THE RESOLUTION, NOT THE OUTCOME, and that distinction
    was found by a control rather than by reading. The first version
    of this test checked that no Customer names appeared against
    transaction ids -- and PASSED with the bug deliberately
    reintroduced. It could not fail: titling a transaction id as a
    Customer looks up a Customer that does not exist, the read is
    refused, and "wrong type" is indistinguishable from "no title
    declared" in the result.

    The shipped fixture has no link whose target declares a title, so
    no outcome-based assertion here can see the difference. What is
    actually being claimed is that the TARGET type is resolved, so
    that is what is asserted.
    """
    generation, user = loop_and_user
    asked = []
    real = generation.loop._titles_for
    generation.loop._titles_for = lambda u, t, i, v, c: asked.append(t) or real(u, t, i, v, c)
    try:
        _run(
            generation, user,
            '{"step": "search_around", "object_type": "Customer", '
            '"link_field": "transactions", "filter": {"customer_id": "cust_001"}}',
        )
    finally:
        generation.loop._titles_for = real

    assert asked == ["Transaction"], (
        f"titled as {asked} -- search_around returns the LINK TARGET's ids, "
        f"so titling them as the step's own object_type reads the wrong "
        f"type's title_field"
    )


def test_a_title_the_caller_cannot_see_is_not_read(loop_and_user):
    """DECLARED IS NOT VISIBLE.

    A type can name a title field the caller has no grant to read.
    Reading it anyway would be a disclosure dressed as a convenience:
    the model would be handed a value the mediator would have refused
    it, and the user would see it in the answer.
    """
    generation, user = loop_and_user
    visible_schema = generation.mediator.visible_schema(user)
    # Same schema, minus the grant to read the title field itself.
    without_name = {
        "Customer": {
            **visible_schema["Customer"],
            "fields": {
                field: spec
                for field, spec in visible_schema["Customer"]["fields"].items()
                if field != "name"
            },
        }
    }

    titles = generation.loop._titles_for(
        user, "Customer", ["cust_001"], without_name, None
    )

    assert titles == {}


def test_titles_are_bounded_by_the_same_cap_as_the_ids(loop_and_user):
    """Each title is a real read with its own audit entry, so an
    unbounded list would let one hop read arbitrarily much -- the
    reason MAX_OBJECT_IDS exists in the first place."""
    generation, user = loop_and_user
    visible_schema = generation.mediator.visible_schema(user)
    many = ["cust_001"] * (MAX_OBJECT_IDS + 50)

    reads = []
    real_get_field = generation.mediator.get_field

    def counting(*args, **kwargs):
        reads.append(args)
        return real_get_field(*args, **kwargs)

    generation.mediator.get_field = counting
    try:
        generation.loop._titles_for(user, "Customer", many, visible_schema, None)
    finally:
        generation.mediator.get_field = real_get_field

    assert len(reads) == MAX_OBJECT_IDS
