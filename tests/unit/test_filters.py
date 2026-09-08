"""
The filter vocabulary.

Elysium's filter was equality only -- one value per field -- so
selecting two values on a chart could not be expressed at all. This is
the closed set of operators that replaces it.

CLOSED DELIBERATELY. Seven operators, each added because a real
interaction needs it, rather than a general expression language. An
open one would have to be parsed and sanitised, and the thing being
parsed decides which rows a caller sees. Every operator here maps to
one SQL construct with bound parameters, so there is nothing to
sanitise.
"""

from datetime import UTC, datetime

import pytest

from core.filters import (
    FieldFilter,
    FilterError,
    parse_filters,
    resolve_relative_date,
    validate_filter,
)

# --- Parsing -------------------------------------------------------------


def test_only_a_list_of_conditions_is_accepted():
    """One shape, not two.

    An earlier version also read a plain {field: value} dict as
    equality-on-each-key, to spare migrating callers. Nothing had
    called it yet, so it was a bridge built for traffic that did not
    exist -- and two accepted shapes is two things to keep correct, in
    the module that decides which rows a caller sees.
    """
    with pytest.raises(FilterError, match="list of conditions"):
        parse_filters({"region": "us-west"})


def test_an_absent_filter_is_no_filter():
    assert parse_filters(None) == []


def test_an_unknown_operator_names_the_known_ones():
    # An author reaching for one that does not exist needs to see what
    # does, or they will try another spelling of the same wrong thing.
    with pytest.raises(FilterError, match="known operators"):
        parse_filters([{"field": "region", "operator": "regex", "value": ".*"}])


def test_a_condition_missing_its_parts_says_which():
    with pytest.raises(FilterError, match=r"\['operator'\]"):
        parse_filters([{"field": "region"}])


# --- Set operators -------------------------------------------------------


def test_in_takes_a_list():
    condition = parse_filters(
        [{"field": "region", "operator": "in", "value": ["us-west", "us-east"]}]
    )[0]

    validate_filter(condition, "string")


@pytest.mark.parametrize("operator", ["in", "not_in"])
def test_an_empty_set_is_rejected(operator):
    # THE reason this is not tolerated: an empty set means "match
    # nothing" for `in` and "match everything" for `not_in` -- opposite
    # outcomes from the same mistake. Guessing which was intended is
    # how a filter silently widens.
    with pytest.raises(FilterError, match="non-empty list"):
        validate_filter(FieldFilter("region", operator, []), "string")


# --- Ranges --------------------------------------------------------------


def test_a_range_may_be_open_at_either_end():
    validate_filter(FieldFilter("amount", "range", {"min": 10}), "number")
    validate_filter(FieldFilter("amount", "range", {"max": 10}), "number")


def test_a_range_with_neither_bound_is_rejected():
    with pytest.raises(FilterError, match="min, max, or both"):
        validate_filter(FieldFilter("amount", "range", {}), "number")


def test_an_inverted_range_is_rejected():
    # Matches nothing, which is more likely a mistake than an intent --
    # and a filter that silently returns zero rows is hard to debug.
    with pytest.raises(FilterError, match="greater than max"):
        validate_filter(FieldFilter("amount", "range", {"min": 5, "max": 1}), "number")


def test_a_range_on_a_string_field_is_rejected():
    with pytest.raises(FilterError, match="applies to"):
        validate_filter(FieldFilter("name", "range", {"min": 1}), "string")


def test_a_field_with_no_declared_type_is_not_second_guessed():
    # data_type is optional. Without one there is no expectation to
    # violate, and inventing one would reject valid schemas -- the same
    # bargain the mutation-value check makes.
    validate_filter(FieldFilter("mystery", "range", {"min": 1}), None)


# --- Dates ---------------------------------------------------------------


def test_a_date_range_needs_real_iso_dates():
    validate_filter(
        FieldFilter("created", "date_range", {"start": "2026-01-01"}), "string"
    )

    with pytest.raises(FilterError, match="not a valid ISO-8601 date"):
        validate_filter(
            FieldFilter("created", "date_range", {"start": "last tuesday"}), "string"
        )


def test_relative_days_must_be_whole_and_not_negative():
    validate_filter(
        FieldFilter("created", "relative_date", {"since_days_ago": 7}), "string"
    )

    with pytest.raises(FilterError, match="cannot be negative"):
        validate_filter(
            FieldFilter("created", "relative_date", {"since_days_ago": -1}), "string"
        )
    with pytest.raises(FilterError, match="whole number of days"):
        validate_filter(
            FieldFilter("created", "relative_date", {"since_days_ago": 1.5}), "string"
        )


def test_a_boolean_is_not_a_number_of_days():
    # bool is a subclass of int in Python, so `since_days_ago: true`
    # would otherwise pass as 1 -- a value nobody meant to write.
    with pytest.raises(FilterError, match="whole number of days"):
        validate_filter(
            FieldFilter("created", "relative_date", {"since_days_ago": True}), "string"
        )


def test_an_inverted_relative_range_is_rejected():
    with pytest.raises(FilterError, match="matches nothing"):
        validate_filter(
            FieldFilter("created", "relative_date",
                        {"since_days_ago": 3, "until_days_ago": 7}),
            "string",
        )


def test_relative_dates_resolve_in_utc_from_a_fixed_reference():
    # Resolved SERVER-side in UTC, so a saved search means the same
    # thing to everyone who opens it. Browser-local would make "the
    # last 7 days" differ by timezone -- a search saved in Berlin and
    # opened in Denver would quietly return a different set.
    #
    # `now` is pinned rather than read from the clock: computing the
    # expectation from datetime.now() would assert the same arithmetic
    # twice and pass whatever the code did.
    resolved = resolve_relative_date(
        {"since_days_ago": 7, "until_days_ago": 1},
        now=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
    )

    assert resolved["start"].startswith("2026-08-31")
    assert resolved["end"].startswith("2026-09-06")


def test_an_open_ended_relative_range_leaves_the_other_side_none():
    resolved = resolve_relative_date(
        {"since_days_ago": 30}, now=datetime(2026, 9, 7, tzinfo=UTC)
    )

    assert resolved["start"].startswith("2026-08-08")
    assert resolved["end"] is None


# --- Text ----------------------------------------------------------------


def test_contains_needs_a_non_empty_string():
    validate_filter(FieldFilter("name", "contains", "ada"), "string")

    with pytest.raises(FilterError, match="non-empty string"):
        validate_filter(FieldFilter("name", "contains", ""), "string")


# --- The error type ------------------------------------------------------


def test_a_filter_error_is_a_value_error():
    # So callers already catching ValueError -- the API's own 400 path
    # among them -- keep working without change.
    assert issubclass(FilterError, ValueError)


# --- Operators as SQL ----------------------------------------------------
#
# The mapping from operator to SQL is worth testing directly: whether
# `in` produces the right number of placeholders is not observable
# from a query's results when the fixture happens to have one matching
# row.


def test_in_produces_one_placeholder_per_value():
    from adapters.sqlite_adapter import _clause_for

    clause, values = _clause_for(FieldFilter("region", "in", ["a", "b", "c"]))

    assert clause == "region IN (?, ?, ?)"
    assert values == ["a", "b", "c"]


def test_a_value_never_becomes_sql():
    # The whole reason the operator set could be widened safely: every
    # branch binds values separately, so a value cannot be a fragment.
    from adapters.sqlite_adapter import _clause_for

    hostile = "'; DROP TABLE customers; --"
    clause, values = _clause_for(FieldFilter("region", "equals", hostile))

    assert hostile not in clause
    assert values == [hostile]


def test_a_one_sided_range_does_not_bind_a_missing_bound():
    from adapters.sqlite_adapter import _clause_for

    assert _clause_for(FieldFilter("n", "range", {"min": 10})) == ("n >= ?", [10])
    assert _clause_for(FieldFilter("n", "range", {"max": 10})) == ("n <= ?", [10])
    assert _clause_for(FieldFilter("n", "range", {"min": 1, "max": 9})) == (
        "n BETWEEN ? AND ?", [1, 9]
    )


def test_contains_escapes_wildcards_in_the_search_text():
    # Without this, searching for "50%" matches anything starting "50".
    from adapters.sqlite_adapter import _clause_for

    _, values = _clause_for(FieldFilter("name", "contains", "50%"))

    assert values == [r"%50\%%"]


def test_the_mirror_declines_contains_rather_than_approximating_it():
    """Iceberg has In, NotIn and range comparisons but no substring
    predicate. StartsWith is the closest and is NOT the same thing.

    Declining is honest. Translating contains to StartsWith would
    return a subset of the right rows and look like it worked -- a
    wrong answer reporting success, which is the failure this project
    keeps finding.
    """
    from core.filters import UnsupportedFilter
    from core.mirror.mirror_adapter import MirrorReadAdapter

    adapter = MirrorReadAdapter.__new__(MirrorReadAdapter)

    with pytest.raises(UnsupportedFilter):
        adapter._term_for(FieldFilter("name", "contains", "ada"))


# --- The same semantics, in Python ---------------------------------------


@pytest.mark.parametrize(
    "condition,row,expected",
    [
        (FieldFilter("r", "equals", "west"), {"r": "west"}, True),
        (FieldFilter("r", "equals", "west"), {"r": "east"}, False),
        (FieldFilter("r", "in", ["west", "east"]), {"r": "east"}, True),
        (FieldFilter("r", "in", ["west"]), {"r": "east"}, False),
        (FieldFilter("r", "not_in", ["west"]), {"r": "east"}, True),
        (FieldFilter("n", "range", {"min": 1, "max": 9}), {"n": 5}, True),
        (FieldFilter("n", "range", {"min": 1, "max": 9}), {"n": 50}, False),
        (FieldFilter("n", "range", {"min": 1}), {"n": None}, False),
        (FieldFilter("s", "contains", "da"), {"s": "ada"}, True),
        (FieldFilter("s", "contains", "zz"), {"s": "ada"}, False),
        (FieldFilter("s", "contains", "da"), {"s": None}, False),
    ],
)
def test_python_evaluation_matches_the_sql_semantics(condition, row, expected):
    # The fallback path uses these when a storage cannot push an
    # operator down. Two definitions of "what does `in` mean" drifting
    # apart would make results depend on which storage answered.
    from core.filters import row_matches

    assert row_matches(row, condition) is expected


# --- Splitting pushable from not ----------------------------------------


def _mediator_with(rows: int, tmp_path):
    import sqlite3

    import yaml

    from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
    from core.ontology.link_types import expand_link_types
    from core.ontology.mediator import DataMediator

    fixtures = "tests/integration/fixtures/"
    schema = yaml.safe_load(open(fixtures + "ontology_schema.yaml"))
    policy = yaml.safe_load(open(fixtures + "policy.yaml"))
    schema["object_types"] = expand_link_types(
        schema.get("link_types", {}), schema["object_types"]
    )
    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    conn.executescript(open(fixtures + "schema.sql").read())
    conn.executemany(
        "INSERT INTO transactions (customer_id, amount, currency, category, "
        "transaction_date) VALUES (?, ?, ?, ?, ?)",
        [("cust_001", float(i % 100), "USD", f"cat{i % 7}", "2024-01-01")
         for i in range(rows)],
    )
    conn.commit()
    conn.close()
    adapters = _build_adapters(
        {"primary_sql": {"adapter": "sqlite", "connection": {"path": db}}},
        _WRITE_ADAPTER_REGISTRY,
    )
    types = {
        name: t for name, t in schema["object_types"].items()
        if name in ("Customer", "Transaction")
    }
    return DataMediator(types, adapters, dict.fromkeys(types, "primary_sql"),
                        policy["roles"])


def test_only_unpushable_conditions_come_back_to_python(tmp_path):
    """One operator a storage cannot express must not cost the whole
    query.

    An earlier version had adapters raise on refusal and the mediator
    retry with NOTHING pushed: a `contains` alongside a range scanned
    everything, measured at 40x the pushed-down time for the same
    answer. Now the mediator splits against what the adapter DECLARED,
    so the range is pushed and only the substring is evaluated here.
    """
    mediator = _mediator_with(20_000, tmp_path)
    config = mediator.schema["Transaction"]
    real = mediator._adapter_for("Transaction")

    class NoSubstring:
        """A storage like the mirror: everything but contains."""

        pushable_operators = frozenset(
            {"equals", "in", "not_in", "range", "date_range"}
        )

        def __getattr__(self, name):
            return getattr(real, name)

    conditions = [
        FieldFilter("amount", "range", {"min": 10, "max": 20}),
        FieldFilter("category", "contains", "cat3"),
    ]

    storage = NoSubstring()
    received: list[list] = []
    real_find = real.find_ids
    storage.find_ids = lambda t, conds, cfg: (
        received.append(conds), real_find(t, conds, cfg)
    )[1]

    split = mediator._find_ids_with_fallback(
        storage, "Transaction", conditions, config
    )
    everything = mediator._apply_conditions_in_python(
        real, real_find("Transaction", [], config), conditions, config
    )

    # Same answer -- the split must not change it.
    assert sorted(split) == sorted(everything)
    assert split, "the fixture should match something, or this proves nothing"

    # And the RANGE reached the storage. This is what distinguishes
    # partial pushdown from the all-or-nothing version: both return the
    # same rows, so only what the adapter was ASKED for tells them
    # apart. A first version asserted the answer alone and passed
    # against the version it existed to replace.
    assert [c.operator for c in received[0]] == ["range"]


def test_a_storage_that_pushes_everything_reads_nothing_back(tmp_path):
    mediator = _mediator_with(500, tmp_path)
    config = mediator.schema["Transaction"]
    adapter = mediator._adapter_for("Transaction")

    reads = []
    real_read = adapter.read_fields_for_ids
    adapter.read_fields_for_ids = lambda *a, **k: (reads.append(1), real_read(*a, **k))[1]
    try:
        mediator._find_ids_with_fallback(
            adapter, "Transaction",
            [FieldFilter("amount", "range", {"min": 10, "max": 20})], config,
        )
    finally:
        adapter.read_fields_for_ids = real_read

    assert reads == [], "SQL expressed the whole filter, so nothing should be re-read"


# --- The adapters defend themselves --------------------------------------


@pytest.mark.parametrize(
    "condition,label",
    [
        (FieldFilter("n", "range", {}), "a range with no bounds"),
        (FieldFilter("n", "in", []), "an empty set"),
    ],
)
def test_the_sql_mapping_rejects_what_validation_would_have(condition, label):
    """validate_filter() rejects both, and the adapter rejects them
    too.

    Not redundant: `IN ()` is invalid SQL and a bound-less range emits
    `field <= ?` bound to None, which matches NOTHING and reports no
    error. An adapter that produces broken SQL when a caller forgets to
    validate is a worse failure than one that says so -- and both were
    reachable, because validate_filter() was written and called by
    nothing.
    """
    from adapters.sqlite_adapter import _clause_for

    with pytest.raises(FilterError):
        _clause_for(condition)


def test_the_adapter_guards_are_what_actually_fire_today():
    """What protects a real query right now.

    search_object() takes a {field: value} dict and builds equals
    conditions from it, so validate_filter() cannot reject anything
    through that path -- every condition is correct by construction.
    An earlier version of this test called a _validate_conditions_for_test
    seam added to the mediator for the purpose, which is test-only code
    in production and does not exercise the real path either.

    The adapters' own guards DO fire, on any condition however
    constructed, and they are what stops a malformed filter becoming
    SQL that silently matches nothing.

    validate_filter() becomes reachable when search_object accepts a
    caller-supplied condition list. That is a 114-call-site signature
    change and is the next piece of work, not this one.
    """
    from adapters.sqlite_adapter import _clause_for

    with pytest.raises(FilterError):
        _clause_for(FieldFilter("n", "range", {}))
    with pytest.raises(FilterError):
        _clause_for(FieldFilter("n", "in", []))


# --- Reachable from a real caller ---------------------------------------
#
# Until now validate_filter() could not reject anything through
# search_object: it took a {field: value} dict and built the equals
# conditions itself, so every condition was correct by construction.
# The vocabulary existed and no caller could use it.


def test_search_rejects_an_operator_the_field_type_forbids(tmp_path):
    from core.intermediate_layer.auth import UserRecord

    mediator = _mediator_with(20, tmp_path)
    user = UserRecord(user_id="u", security_value="us-west", role_name="customer_service")

    # amount declares data_type number; contains is for strings.
    with pytest.raises(FilterError):
        mediator.search_object(
            user, "Transaction", [FieldFilter("amount", "contains", "x")]
        )


def test_search_rejects_a_malformed_range(tmp_path):
    from core.intermediate_layer.auth import UserRecord

    mediator = _mediator_with(20, tmp_path)
    user = UserRecord(user_id="u", security_value="us-west", role_name="customer_service")

    with pytest.raises(FilterError, match="greater than max"):
        mediator.search_object(
            user, "Transaction", [FieldFilter("amount", "range", {"min": 9, "max": 1})]
        )


def test_search_applies_a_set_filter_end_to_end(tmp_path):
    """The interaction the whole vocabulary exists for: two values
    selected on a chart, which the old dict could not express at all.
    """
    from core.intermediate_layer.auth import UserRecord

    mediator = _mediator_with(60, tmp_path)
    user = UserRecord(user_id="u", security_value="us-west", role_name="customer_service")

    two = mediator.search_object(
        user, "Transaction", [FieldFilter("category", "in", ["cat1", "cat2"])]
    )
    one = mediator.search_object(
        user, "Transaction", [FieldFilter("category", "in", ["cat1"])]
    )
    everything = mediator.search_object(user, "Transaction", [])

    assert one, "the fixture should match something, or this proves nothing"
    assert len(one) < len(two) < len(everything)


def test_search_applies_a_range_end_to_end(tmp_path):
    from core.intermediate_layer.auth import UserRecord

    mediator = _mediator_with(60, tmp_path)
    user = UserRecord(user_id="u", security_value="us-west", role_name="customer_service")

    narrow = mediator.search_object(
        user, "Transaction", [FieldFilter("amount", "range", {"min": 0, "max": 10})]
    )
    wide = mediator.search_object(
        user, "Transaction", [FieldFilter("amount", "range", {"min": 0, "max": 50})]
    )

    assert narrow
    assert len(narrow) < len(wide)


def test_a_filter_on_an_unreadable_field_looks_like_an_unknown_one(tmp_path):
    """Uniform denial. A caller must not learn that a field EXISTS by
    filtering on one they cannot read -- the message is the same as for
    a field that does not exist at all.
    """
    from core.intermediate_layer.auth import UserRecord

    mediator = _mediator_with(20, tmp_path)
    user = UserRecord(user_id="u", security_value="us-west", role_name="customer_service")

    unknown = pytest.raises(ValueError, match="Invalid search criteria")
    with unknown:
        mediator.search_object(
            user, "Transaction", [FieldFilter("no_such_field", "equals", "x")]
        )

    # A REAL column the fixture role has no read grant for.
    with pytest.raises(ValueError, match="Invalid search criteria"):
        mediator.search_object(
            user, "Transaction", [FieldFilter("internal_notes", "equals", "x")]
        )
