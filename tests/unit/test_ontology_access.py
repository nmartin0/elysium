"""
Point 15: Functions with ontology access, via a caller-bound capability.

FOUNDRY'S FUNCTIONS ARE DEFINED BY ONTOLOGY ACCESS -- "first-class
support for reading the properties of various object types, traversing
links, and flexibly making Ontology edits", which is what makes them
"go far beyond commonly used Functions-as-a-Service platforms". Elysium
had pure computation only.

WHY A CAPABILITY, NOT A MEDIATOR. These functions are invoked by an
LLM that chooses their arguments, so ambient ontology access would let
the model aim a function at data the caller cannot see. Foundry's own
Q&A gives away how they avoid the equivalent: "there is no way to get
the executing user's ID within a function without passing it as a
parameter" -- their function authors do not write permission checks
because they cannot know who is calling. The platform enforces it
beneath them. OntologyAccess is that layer here.

TWO INDEPENDENT RESTRICTIONS, tested separately below because either
alone would be insufficient:
  - the caller's own MAC and RBAC, unchanged
  - the object types the function DECLARED, which bounds what a buggy
    or compromised function can reach to what its author said
"""

import sqlite3

import pytest
import yaml

from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.functions.ontology_access import OntologyAccess
from core.intermediate_layer.auth import UserRecord
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator

FIXTURES = "tests/integration/fixtures/"
WEST = UserRecord(user_id="a", security_value="us-west", role_name="customer_service")
EAST = UserRecord(user_id="b", security_value="us-east", role_name="customer_service")


@pytest.fixture
def mediator(tmp_path):
    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    # Link fields are GENERATED from link_types at load; the raw
    # YAML no longer declares them (see core/ontology/link_types.py).
    schema["object_types"] = expand_link_types(
        schema.get("link_types", {}), schema["object_types"]
    )
    policy = yaml.safe_load(open(FIXTURES + "policy.yaml"))

    db_path = tmp_path / "business.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(open(FIXTURES + "schema.sql").read())
    conn.commit()
    conn.close()

    adapters = _build_adapters(
        {"primary_sql": {"adapter": "sqlite", "connection": {"path": db_path}}},
        _WRITE_ADAPTER_REGISTRY,
    )
    object_types = {
        name: type_def
        for name, type_def in schema["object_types"].items()
        if name in ("Customer", "Transaction")
    }
    return DataMediator(
        object_types, adapters, dict.fromkeys(object_types, "primary_sql"), policy["roles"]
    )


def _access(mediator, user=WEST, types=("Customer", "Transaction")):
    return OntologyAccess(mediator, user, list(types))


# --- The capability works ----------------------------------------------


def test_a_function_can_search(mediator):
    assert _access(mediator).search("Customer", {}) == ["cust_001", "cust_002"]


def test_a_function_can_read_object_fields(mediator):
    fields = _access(mediator).get_object("Customer", "cust_001", ["name", "region"])

    assert fields["name"] == "Ada Okafor"


def test_a_function_can_count_and_aggregate(mediator):
    access = _access(mediator)

    assert access.count("Transaction", {}) == 4
    assert access.aggregate("Transaction", "sum", "amount", "category")["hardware"] == 199.0


def test_a_function_can_traverse_links(mediator):
    # Foundry's search-around, reachable from a function.
    assert _access(mediator).search_around("Customer", "transactions") == [1, 2, 3, 4]


def test_dynamic_selection_works(mediator):
    # THE case that ruled out passing pre-resolved data only: a filter
    # derived from an argument the function received, resolved at run
    # time rather than declared in advance.
    access = _access(mediator)

    matching = access.search("Customer", {"region": "us-west"})
    linked = access.search_around("Customer", "transactions", {"region": "us-west"})

    assert matching
    assert linked


# --- Restriction one: the caller's own permissions ----------------------


def test_the_capability_is_bound_to_one_caller(mediator):
    # The same function, run by two users, sees genuinely different
    # data -- because every call goes through the caller's own MAC.
    west = _access(mediator, WEST).search("Customer", {})
    east = _access(mediator, EAST).search("Customer", {})

    assert west and east
    assert not (set(west) & set(east))


def test_a_function_cannot_read_an_object_outside_the_callers_boundary(mediator):
    # Reading by id directly, not via search -- the path that would
    # bypass a filter-only check.
    fields = _access(mediator, EAST).get_object("Customer", "cust_001", ["name"])

    assert fields["name"] is None


def test_aggregates_respect_the_callers_boundary(mediator):
    # An aggregate that ignored MAC would let a function infer values
    # over rows its caller cannot read.
    west = _access(mediator, WEST).count("Transaction", {})
    east = _access(mediator, EAST).count("Transaction", {})

    assert west != east


# --- Restriction two: the declared object types -------------------------


def test_an_undeclared_object_type_is_refused(mediator):
    # Defence in depth beyond Foundry: a function that declared
    # Customer cannot read Account, even if its caller could.
    access = _access(mediator, WEST, types=("Customer",))

    with pytest.raises(ValueError, match="did not declare"):
        access.search("Transaction", {})


def test_every_method_enforces_the_declaration(mediator):
    # One unchecked method would make the whole restriction pointless.
    access = _access(mediator, WEST, types=("Customer",))

    for call in (
        lambda: access.search("Transaction", {}),
        lambda: access.get_object("Transaction", 1, ["amount"]),
        lambda: access.count("Transaction", {}),
        lambda: access.aggregate("Transaction", "count"),
        lambda: access.search_around("Transaction", "customer_id"),
    ):
        with pytest.raises(ValueError, match="did not declare"):
            call()


def test_a_link_cannot_reach_an_undeclared_target_type(mediator):
    # Traversing a link must not become a way to read a type the
    # function never declared -- the target is checked too.
    access = _access(mediator, WEST, types=("Customer",))

    with pytest.raises(ValueError, match="did not declare"):
        access.search_around("Customer", "transactions")


def test_an_undeclared_type_RAISES_rather_than_returning_empty(mediator):
    # Deliberately different from a permission denial, which returns
    # empty. Reaching for an undeclared type is an AUTHORING error --
    # the declaration and the code disagree -- and returning nothing
    # would hide the bug behind plausible-looking empty results.
    access = _access(mediator, WEST, types=("Customer",))

    with pytest.raises(ValueError):
        access.search("Transaction", {})


# --- Load-time validation -----------------------------------------------


def test_a_function_declaring_an_unknown_object_type_fails_at_load():
    # Foundry runs compatibility checks before publishing a function.
    # Elysium has no versioning to protect (see ROADMAP.md), but the
    # same class of mistake is worth catching at LOAD rather than
    # mid-conversation, after a user has already asked a question.
    from core.functions.registry import _FUNCTION_REGISTRY, validate_function_declarations

    class BadFunction:
        name = "bad"
        description = "declares a type the ontology does not have"
        parameters: dict = {}
        max_concurrent_calls = None
        reads_object_types = ["NoSuchType"]

        def run(self, **kwargs):
            return None

    _FUNCTION_REGISTRY["bad"] = BadFunction
    try:
        with pytest.raises(ValueError, match="not a declared object type"):
            validate_function_declarations(["bad"], {"Customer": {}})
    finally:
        del _FUNCTION_REGISTRY["bad"]


def test_a_function_declaring_a_known_object_type_validates():
    from core.functions.registry import _FUNCTION_REGISTRY, validate_function_declarations

    class GoodFunction:
        name = "good"
        description = "declares a real type"
        parameters: dict = {}
        max_concurrent_calls = None
        reads_object_types = ["Customer"]

        def run(self, **kwargs):
            return None

    _FUNCTION_REGISTRY["good"] = GoodFunction
    try:
        validate_function_declarations(["good"], {"Customer": {}})
    finally:
        del _FUNCTION_REGISTRY["good"]


def test_a_purely_computational_function_declares_nothing_and_validates():
    # The existing linear_regression, unchanged by this work: it
    # declares no object types, so it receives no capability and
    # provably cannot reach the ontology.
    from core.functions.registry import get_enabled_functions, validate_function_declarations

    validate_function_declarations(["linear_regression"], {})
    assert get_enabled_functions(["linear_regression"])[0].reads_object_types == []


# --- The capability surface, pinned ---------------------------------------
#
# Three roadmap entries rest on one property: a function reaches only
# what its declared object types allow, under the caller's own
# permissions. If OntologyAccess grows a method that hands back
# something wider, or the agent loop starts passing more than the
# capability, those entries become wrong and nothing else would say
# so.


def test_the_capability_exposes_only_scoped_reads():
    public = sorted(name for name in dir(OntologyAccess) if not name.startswith("_"))

    assert public == ["aggregate", "count", "get_object", "search", "search_around"]


def test_the_capability_does_not_hand_back_the_mediator():
    # It holds one privately -- it has to, to do anything at all -- but
    # exposing it would let a function reach every object type, every
    # adapter, and the write log.
    mediator = object()
    access = OntologyAccess(mediator, WEST, ["Customer"])

    exposed = [
        name for name in dir(access)
        if not name.startswith("_") and getattr(access, name, None) is mediator
    ]
    assert exposed == []


def test_the_agent_loop_passes_nothing_but_the_capability():
    # A function receives its own declared arguments plus `ontology`.
    # Adding a UserRecord, an adapter or the mediator here would
    # silently undo the scoping, since a function author would simply
    # use whatever arrived.
    import inspect

    from core.agent import agentic_loop

    source = inspect.getsource(agentic_loop)

    assert source.count('call_args["') == 1
    assert 'call_args["ontology"]' in source
