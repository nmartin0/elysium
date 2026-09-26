"""A handle names a result the planner cannot read.

AL-4, first commit. The planner writes `$a` and the executor
substitutes the value, so a planted instruction in a field value
cannot change WHICH steps run -- the steps were fixed before any
value was read.

NO MODEL IS INVOLVED, which is why this is first. Handle resolution
is pure, and getting `$a` wrong SILENTLY is how a plan reads the wrong
object. Silence is exactly what a test can catch when there is no
model in the way.

MOST OF THIS FILE IS ABOUT REFUSING THINGS, because every way a
handle can go wrong ends with a confident answer about data that was
never read.
"""

import pytest

from core.agent.plan import (
    PlanError,
    resolve_handles,
    resolve_step,
    validate_plan,
)


def _step(step_id, **rest):
    return {"id": step_id, "step": "get_field", **rest}


# ------------------------------------------------------------ what resolves


def test_a_handle_becomes_the_value_itself_not_a_string_of_it():
    """`$a` resolving to a list becomes the LIST.

    A step handed `'["1", "2"]'` would search for an object whose id
    is literally a JSON array -- which finds nothing, quietly.
    """
    resolved = resolve_handles({"object_id": "$a"}, {"a": ["1", "2"]})

    assert resolved == {"object_id": ["1", "2"]}


def test_handles_resolve_at_any_depth():
    """A plan puts them inside filters and lists, not only at the top."""
    value = {"filter": {"customer_id": "$a"}, "object_ids": ["$b", "literal"]}

    resolved = resolve_handles(value, {"a": "cust_001", "b": "t_1"})

    assert resolved == {
        "filter": {"customer_id": "cust_001"},
        "object_ids": ["t_1", "literal"],
    }


def test_the_id_is_dropped_from_a_resolved_step():
    """It names the step for other steps and means nothing to a
    handler. Leaving it in would put an extra key in every gathered
    entry -- prompt tokens on every later hop, for a value the model
    chose itself."""
    resolved = resolve_step(_step("a", object_id="$b"), {"b": "cust_001"})

    assert "id" not in resolved
    assert resolved == {"step": "get_field", "object_id": "cust_001"}


def test_values_that_are_not_strings_pass_through():
    value = {"limit": 5, "exact": True, "missing": None, "rate": 1.5}

    assert resolve_handles(value, {}) == value


# ------------------------------------------- what is NOT a handle, and why


def test_a_price_is_not_a_handle():
    """`$100` IS NOT A HANDLE. It is a price, and a customer really can
    be called "$100 Store". Identifiers must start with a letter, so a
    leading digit settles it and nobody has to escape anything."""
    assert resolve_handles("$100", {}) == "$100"
    assert resolve_handles({"name": "$100 Store"}, {}) == {"name": "$100 Store"}


def test_a_handle_must_be_the_whole_value():
    """Not a prefix, not a substring, not interpolation. `"$a and $b"`
    is a string a person wrote, and rewriting parts of it would be
    templating -- a different feature with different failure modes."""
    assert resolve_handles("$a and $b", {"a": "x", "b": "y"}) == "$a and $b"
    assert resolve_handles("prefix$a", {"a": "x"}) == "prefix$a"
    assert resolve_handles("$a ", {"a": "x"}) == "$a "


def test_dict_keys_are_never_resolved():
    """ONLY VALUES. A key here is a field name, not data. Resolving
    one would let a plan choose which FIELD to read based on something
    it read earlier -- turning a data value back into control flow,
    which is the one thing this design exists to prevent.
    """
    resolved = resolve_handles({"$a": "value"}, {"a": "region"})

    assert resolved == {"$a": "value"}


# ---------------------------------------------------------- what is refused


def test_an_unknown_handle_raises_rather_than_passing_through():
    """THE QUIET FAILURE THIS PREVENTS.

    `$custmer` -- a typo -- treated as the literal string "$custmer"
    would be used as a filter value, match nothing, and let the plan
    carry on producing a confident answer about no data. Refusing is
    the only outcome that cannot be mistaken for a result.
    """
    with pytest.raises(PlanError, match=r"\$custmer"):
        resolve_handles({"filter": {"name": "$custmer"}}, {"customer": "x"})


def test_a_forward_reference_is_refused():
    """A plan is a list; a step may use any step BEFORE it. Refusing
    forward references makes cycles impossible without a cycle check."""
    with pytest.raises(PlanError, match="before them"):
        validate_plan([_step("a", object_id="$b"), _step("b")])


def test_a_step_cannot_use_its_own_result():
    with pytest.raises(PlanError, match="its own result"):
        validate_plan([_step("a", object_id="$a")])


def test_a_duplicate_id_is_refused():
    """Two steps with one name makes a handle to it ambiguous, and the
    ambiguity would be resolved silently by whichever won."""
    with pytest.raises(PlanError, match="more than once"):
        validate_plan([_step("a"), _step("a")])


@pytest.mark.parametrize("bad_id", ["1a", "", "a-b", "a b", "$a", None, 7])
def test_an_id_that_is_not_identifier_shaped_is_refused(bad_id):
    """The id and the handle share one shape, so an id a handle could
    never name is a step nothing can refer to."""
    with pytest.raises(PlanError):
        validate_plan([{"id": bad_id, "step": "get_field"}])


@pytest.mark.parametrize("not_a_plan", [None, {}, "a plan", 7])
def test_something_that_is_not_a_list_of_steps_is_refused(not_a_plan):
    with pytest.raises(PlanError):
        validate_plan(not_a_plan)


def test_an_empty_plan_is_refused():
    """Nothing to execute is not a plan, and returning success for one
    would report an answer nobody gathered."""
    with pytest.raises(PlanError, match="at least one step"):
        validate_plan([])


def test_a_step_that_is_not_an_object_is_refused():
    with pytest.raises(PlanError, match="not an object"):
        validate_plan(["search everything"])


def test_plan_errors_are_ValueErrors():
    """THE CONTRACT THE LOOP DEPENDS ON.

    _execute_step catches (ValueError, TypeError, PermissionError) and
    turns them into a recoverable mistake the model can be told about.
    A new exception type would sail past that handler and out of the
    loop -- AL-1's shape, a model-written value crashing /query
    outside the error handling.
    """
    assert issubclass(PlanError, ValueError)


# ---------------------------------------------------------------- together


def test_a_realistic_plan_validates_and_resolves():
    """The worked example from the proposal: find a customer, follow
    the link, read a field. Three steps, one model call, and the
    planner never sees `cust_001`.
    """
    plan = [
        {"id": "a", "step": "search_object", "object_type": "Customer",
         "filter": {"name": "Ada Okafor"}},
        {"id": "b", "step": "search_around", "object_type": "Customer",
         "link_field": "transactions", "of": "$a"},
        {"id": "c", "step": "get_field", "object_type": "Transaction",
         "object_id": "$b", "field_name": "amount"},
    ]

    validate_plan(plan)

    results: dict = {}
    results["a"] = ["cust_001"]
    assert resolve_step(plan[1], results)["of"] == ["cust_001"]
    results["b"] = ["t_1", "t_2"]
    assert resolve_step(plan[2], results)["object_id"] == ["t_1", "t_2"]


def test_validation_runs_before_anything_executes():
    """A plan whose third step names a handle that does not exist is
    broken whether or not the first two would have succeeded --
    and finding out after two real reads means two audit entries for a
    query that was never going to work."""
    plan = [_step("a"), _step("b"), _step("c", object_id="$nowhere")]

    with pytest.raises(PlanError, match=r"\$nowhere"):
        validate_plan(plan)
