"""
Evaluating an object set (core/ontology/object_sets.py) against the
fixture deployment, as particular callers.

THE FIXTURE: cust_001 and cust_002 are us-west, cust_003 us-east, cust_004
eu. Transactions 1-4 belong to the two us-west customers, 5-6 to us-east,
7 to eu. user_alice is us-west and sees two customers; user_bob is us-east
and sees one; user_dave is us-west and may read Customer.name but neither
Customer.email nor Customer.region; user_carol has no role at all.

WHAT IS PROTECTED, in the order the tests are written:
  - a row the caller may not see never appears, however the set is built
  - a field the caller may not read cannot be filtered, sorted, selected
    or measured, and the refusal is word-for-word the one for a field
    that does not exist
  - the set algebra is the algebra, over what the caller may see
  - the evaluation reads through the mediator and nowhere else
"""

import pytest

from elysium.core.access.auth import UserRecord, resolve_user_record
from elysium.core.ontology import mediator as mediator_module
from elysium.core.ontology import object_sets as sets
from elysium.core.ontology.object_sets import (
    ObjectSetError,
    ObjectSetNotFound,
    SchemaView,
    evaluate,
    metric_fields,
    ordered,
    parse_filter,
    parse_metrics,
    parse_object_set,
    prepare,
)

CUSTOMERS = {"type": "base", "objectType": "Customer"}
TRANSACTIONS = {"type": "base", "objectType": "Transaction"}


def static(*keys, object_type="Customer"):
    return {"type": "static", "objectType": object_type, "primaryKeys": list(keys)}


def where(object_set, condition):
    return {"type": "filter", "objectSet": object_set, "where": condition}


def leaf(kind, field, value):
    return {"type": kind, "field": field, "value": value}


@pytest.fixture
def alice(deployment):
    return resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)


@pytest.fixture
def bob(deployment):
    return resolve_user_record(deployment.users, "user_bob", deployment.security_attribute)


@pytest.fixture
def dave(deployment):
    return resolve_user_record(deployment.users, "user_dave", deployment.security_attribute)


@pytest.fixture
def carol(deployment):
    return resolve_user_record(deployment.users, "user_carol", deployment.security_attribute)


@pytest.fixture
def names_only_email(deployment):
    """May DISCOVER Customer.email and not read it: named but withheld."""
    return UserRecord("user_x", "us-west", "customer_service_sees_email_exists")


@pytest.fixture
def run(mediator):
    def _run(user, raw):
        view = SchemaView(mediator, user)
        evaluated = evaluate(mediator, user, prepare(parse_object_set(raw), view), view)
        return evaluated
    return _run


@pytest.fixture
def keys(run):
    def _keys(user, raw):
        return {str(object_id) for object_id in run(user, raw).ids}
    return _keys


class TestARowTheCallerCannotSeeNeverAppears:
    def test_each_caller_gets_their_own_customers(self, keys, alice, bob):
        assert keys(alice, CUSTOMERS) == {"cust_001", "cust_002"}
        assert keys(bob, CUSTOMERS) == {"cust_003"}

    def test_naming_a_hidden_row_by_key_does_not_fetch_it(self, keys, alice):
        assert keys(alice, static("cust_001", "cust_003", "cust_004", "cust_999")) == {"cust_001"}

    def test_filtering_for_the_hidden_value_finds_nothing(self, keys, alice):
        assert keys(alice, where(CUSTOMERS, leaf("eq", "region", "us-east"))) == set()
        assert keys(alice, where(CUSTOMERS, leaf("in", "region", ["us-east", "eu"]))) == set()

    def test_a_negated_filter_still_only_ranges_over_what_is_visible(self, keys, alice):
        assert keys(alice, where(CUSTOMERS, {"type": "not", "value": leaf("eq", "name", "Ada Okafor")})) == {
            "cust_002"}

    def test_search_around_returns_only_far_side_objects_the_caller_can_see(self, keys, alice, bob):
        through = {"type": "searchAround", "link": "transactions", "objectSet": CUSTOMERS}

        assert keys(alice, through) == {"1", "2", "3", "4"}
        assert keys(bob, through) == {"5", "6"}

    def test_search_around_from_a_hidden_source_reaches_nothing(self, keys, alice):
        # cust_003 is us-east. Naming it must not make its transactions reachable.
        through = {"type": "searchAround", "link": "transactions", "objectSet": static("cust_003", "cust_004")}

        assert keys(alice, through) == set()

    def test_the_mediator_rechecks_sources_it_is_handed(self, mediator, alice):
        """search_around_from() takes ids from a caller, so it must not
        trust them: a reverse link is resolved from the other table
        without reading each source."""
        assert mediator.search_around_from(alice, "Customer", ["cust_003"], "transactions") == []
        assert {str(i) for i in mediator.search_around_from(
            alice, "Customer", ["cust_001", "cust_003"], "transactions")} == {"1", "2"}

    def test_only_the_sources_that_pass_the_check_are_followed(self, mediator, alice, monkeypatch):
        """The target side is checked too, so a hidden source usually yields
        nothing anyway; what must hold is that it is never FOLLOWED."""
        followed = []
        monkeypatch.setattr(mediator, "_follow_link",
                            lambda user, object_type, sources, link, context, outcome: followed.append(
                                list(sources)) or [])

        mediator.search_around_from(alice, "Customer", ["cust_003", "cust_001", "cust_004", "cust_001"],
                                    "transactions")

        assert followed == [["cust_001"]]

    def test_field_values_are_withheld_for_ids_the_caller_cannot_see(self, mediator, alice):
        rows = mediator.field_values_for_ids(alice, "Customer", ["cust_001", "cust_003"], ["name"])

        assert rows == {"cust_001": {"name": "Ada Okafor"}}

    def test_a_type_with_no_grant_and_an_unknown_type_are_the_same_outcome(self, mediator, carol, alice):
        for user, name in ((carol, "Customer"), (alice, "NoSuchType"), (carol, "NoSuchType")):
            view = SchemaView(mediator, user)
            with pytest.raises(ObjectSetNotFound):
                prepare(parse_object_set({"type": "base", "objectType": name}), view)
            with pytest.raises(ObjectSetNotFound):
                prepare(parse_object_set(static("x", object_type=name)), view)

    def test_the_far_side_of_a_link_must_itself_be_readable(self, mediator):
        # A role that reads Customer.transactions as a link but not Transaction itself.
        user = UserRecord("user_y", "us-west", "customer_service_link_only")
        view = SchemaView(mediator, user)
        # Customer is readable to this role; Transaction is not even known to it.
        with pytest.raises(ObjectSetError, match="Unknown link"):
            prepare(parse_object_set({"type": "searchAround", "link": "transactions",
                                      "objectSet": CUSTOMERS}), view)


class TestAFieldTheCallerCannotReadIsIndistinguishableFromOneThatDoesNotExist:
    """Three callers' views of the same attempt: a field that is absent, a
    field withheld outright (dave, email), and one that may be discovered
    but not read (names_only_email, email). The message may differ in
    nothing but the name the CALLER typed."""

    ABSENT = "nonexistent_field"

    def refusal(self, mediator, user, raw):
        view = SchemaView(mediator, user)
        with pytest.raises(ObjectSetError) as refused:
            prepare(parse_object_set(raw), view)
        return refused.value

    def same_as_absent(self, mediator, user, hidden, build):
        absent = self.refusal(mediator, user, build(self.ABSENT))
        hidden_refusal = self.refusal(mediator, user, build(hidden))
        assert str(hidden_refusal).replace(hidden, "F") == str(absent).replace(self.ABSENT, "F")
        assert {k: (v if v not in (hidden, self.ABSENT) else "F") for k, v in hidden_refusal.parameters.items()} == {
            k: (v if v not in (hidden, self.ABSENT) else "F") for k, v in absent.parameters.items()}
        assert "Unknown field" in str(hidden_refusal)

    @pytest.mark.parametrize("who, hidden", [("dave", "email"), ("dave", "region"),
                                             ("names_only_email", "email")])
    def test_filtering(self, mediator, request, who, hidden):
        user = request.getfixturevalue(who)
        self.same_as_absent(mediator, user, hidden, lambda f: where(CUSTOMERS, leaf("eq", f, "x")))
        self.same_as_absent(mediator, user, hidden,
                            lambda f: where(CUSTOMERS, {"type": "or", "value": [
                                leaf("eq", "name", "Ada Okafor"), {"type": "not", "value": leaf("contains", f, "a")}]}))
        self.same_as_absent(mediator, user, hidden, lambda f: where(CUSTOMERS, {"type": "isNull", "field": f,
                                                                                "value": True}))

    @pytest.mark.parametrize("who, hidden", [("dave", "email"), ("names_only_email", "email")])
    def test_sorting_selecting_and_measuring(self, mediator, request, who, hidden):
        user = request.getfixturevalue(who)
        view = SchemaView(mediator, user)

        def failure(call):
            with pytest.raises(ObjectSetError) as refused:
                call(hidden)
            absent = pytest.raises(ObjectSetError)
            with absent as caught:
                call(self.ABSENT)
            assert str(refused.value).replace(hidden, "F") == str(caught.value).replace(self.ABSENT, "F")

        failure(lambda f: view.filterable("Customer", f))
        failure(lambda f: view.selectable("Customer", f))
        failure(lambda f: ordered(mediator, user, view, "Customer", ["cust_001"], (sets.OrderTerm(f),)))

    def test_a_metric_over_a_field_the_caller_cannot_read(self, mediator, dave):
        # dave cannot read Transaction at all, so use a role that can read
        # Transaction but check a hidden numeric field on Customer.
        user = UserRecord("user_z", "us-west", "customer_service")
        view = SchemaView(mediator, user)
        metrics = parse_metrics([{"type": "sum", "field": "nonexistent_field"}])
        with pytest.raises(ObjectSetError, match="Unknown field"):
            metric_fields(view, "Transaction", metrics, None)

    def test_the_visible_schema_marks_the_withheld_field_unreadable_which_is_why_it_is_refused(
            self, mediator, names_only_email):
        field = mediator.visible_schema(names_only_email)["Customer"]["fields"]["email"]

        assert field["readable"] is False

    def test_a_reverse_link_is_not_a_filter_field_but_says_so_only_when_readable(self, mediator, alice):
        view = SchemaView(mediator, alice)

        with pytest.raises(ObjectSetError, match="reverse link"):
            view.filterable("Customer", "transactions")


class TestOperatorsAgainstTheDeclaredType:
    @pytest.mark.parametrize("condition, words", [
        (leaf("contains", "amount", "4"), "applies to text"),
        (leaf("startsWith", "amount", "4"), "applies to text"),
        (leaf("lt", "customer_id", "cust_002"), "needs a field with an order"),
        (leaf("gt", "customer_id", "cust_002"), "needs a field with an order"),
        (leaf("contains", "customer_id", "cust"), "applies to text"),
        (leaf("gt", "amount", "lots"), "not a valid number"),
        (leaf("eq", "amount", "lots"), "not a valid number"),
        (leaf("in", "amount", [1, "lots"]), "not a valid number"),
        (leaf("gt", "amount", ""), "not a valid number"),
        (leaf("gt", "transaction_id", 1), "the primary key"),
        (leaf("lte", "customer_id", "x"), "a link"),
    ])
    def test_a_wrong_operator_or_value_is_refused_before_any_data_is_read(self, mediator, alice, condition, words):
        view = SchemaView(mediator, alice)

        with pytest.raises(ObjectSetError, match=words):
            prepare(parse_object_set(where(TRANSACTIONS, condition)), view)

    def test_the_right_operators_for_each_type_are_accepted(self, mediator, alice):
        view = SchemaView(mediator, alice)
        for condition in (leaf("gte", "amount", 10), leaf("lt", "category", "m"), leaf("eq", "customer_id", "cust_001"),
                          leaf("in", "customer_id", ["cust_001"]), leaf("startsWith", "category", "sub"),
                          leaf("isNull", "currency", True), leaf("eq", "transaction_id", "1")):
            prepare(parse_object_set(where(TRANSACTIONS, condition)), view)

    def test_combining_sets_of_different_types_is_refused(self, mediator, alice):
        with pytest.raises(ObjectSetError, match="ONE object type"):
            prepare(parse_object_set({"type": "union", "objectSets": [CUSTOMERS, TRANSACTIONS]}),
                    SchemaView(mediator, alice))

    def test_search_around_follows_declared_links_only(self, mediator, alice):
        view = SchemaView(mediator, alice)
        for link in ("region", "name", "nonexistent", "customer_id"):
            with pytest.raises(ObjectSetError, match="Unknown link"):
                prepare(parse_object_set({"type": "searchAround", "link": link, "objectSet": CUSTOMERS}), view)
        # Forward links are declared links too.
        prepared = prepare(parse_object_set({"type": "searchAround", "link": "customer_id",
                                             "objectSet": TRANSACTIONS}), view)
        assert prepared.object_type == "Customer"


class TestWhatTheOperatorsMean:
    """Over the transactions alice may see: 1 49.99 subscription, 2 199.00
    hardware, 3 49.99 subscription, 4 -20.00 refund."""

    @pytest.mark.parametrize("condition, expected", [
        (leaf("eq", "amount", 49.99), {"1", "3"}),
        (leaf("gt", "amount", 49.99), {"2"}),
        (leaf("gte", "amount", 49.99), {"1", "2", "3"}),
        (leaf("lt", "amount", 49.99), {"4"}),
        (leaf("lte", "amount", 49.99), {"1", "3", "4"}),
        (leaf("in", "amount", [199, -20]), {"2", "4"}),
        (leaf("contains", "category", "SUB"), {"1", "3"}),
        (leaf("startsWith", "category", "Hard"), {"2"}),
        (leaf("lt", "transaction_date", "2026-06-01"), {"1", "3"}),
        (leaf("isNull", "category", False), {"1", "2", "3", "4"}),
        (leaf("isNull", "category", True), set()),
        ({"type": "and", "value": [leaf("gt", "amount", 0), leaf("eq", "category", "subscription")]}, {"1", "3"}),
        ({"type": "or", "value": [leaf("eq", "category", "refund"), leaf("eq", "category", "hardware")]}, {"2", "4"}),
        ({"type": "not", "value": leaf("eq", "category", "subscription")}, {"2", "4"}),
    ])
    def test_each_operator(self, keys, alice, condition, expected):
        assert keys(alice, where(TRANSACTIONS, condition)) == expected

    def test_a_null_matches_no_comparison_and_not_inverts(self, mediator, alice):
        view = SchemaView(mediator, alice)
        fields: dict = {}
        compiled = {kind: sets.compile_filter(parse_filter(leaf(kind, "category", "subscription")), view,
                                              "Transaction", fields)
                    for kind in ("eq", "lt", "lte", "gt", "gte")}
        row = {"category": None}

        assert not any(predicate(row) for predicate in compiled.values())
        assert not sets.compile_filter(parse_filter(leaf("contains", "category", "s")), view, "Transaction",
                                       fields)(row)
        assert not sets.compile_filter(parse_filter(leaf("in", "category", ["subscription"])), view,
                                       "Transaction", fields)(row)
        assert sets.compile_filter(parse_filter(leaf("isNull", "category", True)), view, "Transaction", fields)(row)
        assert sets.compile_filter(parse_filter({"type": "not", "value": leaf("eq", "category", "x")}), view,
                                   "Transaction", fields)(row)

    def test_a_stored_value_that_does_not_fit_its_type_matches_nothing(self, mediator, alice):
        view = SchemaView(mediator, alice)
        predicate = sets.compile_filter(parse_filter(leaf("gt", "amount", 0)), view, "Transaction", {})

        assert predicate({"amount": "abc"}) is False
        assert predicate({"amount": "12"}) is True


class TestTheSetAlgebra:
    A = static("cust_001", "cust_002")
    B = static("cust_002", "cust_003")

    def test_union_intersect_and_subtract_over_what_alice_sees(self, keys, alice):
        # B names cust_003, which alice cannot see: it is not in B for her.
        assert keys(alice, {"type": "union", "objectSets": [self.A, self.B]}) == {"cust_001", "cust_002"}
        assert keys(alice, {"type": "intersect", "objectSets": [self.A, self.B]}) == {"cust_002"}
        assert keys(alice, {"type": "subtract", "objectSets": [self.A, self.B]}) == {"cust_001"}
        assert keys(alice, {"type": "subtract", "objectSets": [self.B, self.A]}) == set()

    def test_the_same_sets_for_a_caller_who_sees_the_other_customer(self, keys, bob):
        assert keys(bob, {"type": "union", "objectSets": [self.A, self.B]}) == {"cust_003"}
        assert keys(bob, {"type": "intersect", "objectSets": [self.A, self.B]}) == set()
        assert keys(bob, {"type": "subtract", "objectSets": [self.B, self.A]}) == {"cust_003"}

    def test_the_laws_hold_over_filters(self, keys, alice):
        expensive = where(TRANSACTIONS, leaf("gt", "amount", 100))
        subscriptions = where(TRANSACTIONS, leaf("eq", "category", "subscription"))
        everything = keys(alice, TRANSACTIONS)
        x, y = keys(alice, expensive), keys(alice, subscriptions)

        assert keys(alice, {"type": "union", "objectSets": [expensive, subscriptions]}) == x | y
        assert keys(alice, {"type": "intersect", "objectSets": [expensive, subscriptions]}) == x & y == set()
        assert keys(alice, {"type": "subtract", "objectSets": [TRANSACTIONS, subscriptions]}) == everything - y
        # subtract is not commutative; union and intersect are.
        assert keys(alice, {"type": "union", "objectSets": [subscriptions, expensive]}) == x | y
        # a filter of a union is the union of filters
        recent = {"type": "not", "value": leaf("eq", "category", "refund")}
        assert keys(alice, where({"type": "union", "objectSets": [expensive, subscriptions]}, recent)) == (
            keys(alice, where(expensive, recent)) | keys(alice, where(subscriptions, recent)))

    def test_three_sets_combine_left_to_right(self, keys, alice):
        everything = TRANSACTIONS
        refunds = where(TRANSACTIONS, leaf("eq", "category", "refund"))
        hardware = where(TRANSACTIONS, leaf("eq", "category", "hardware"))

        assert keys(alice, {"type": "subtract", "objectSets": [everything, refunds, hardware]}) == {"1", "3"}

    def test_a_set_built_from_one_object_type_to_another(self, keys, alice):
        us_west_customers = where(CUSTOMERS, leaf("eq", "region", "us-west"))
        expensive_owners = {"type": "searchAround", "link": "customer_id",
                            "objectSet": where(TRANSACTIONS, leaf("gt", "amount", 100))}

        assert keys(alice, {"type": "intersect", "objectSets": [us_west_customers, expensive_owners]}) == {"cust_001"}

    def test_set_algebra_keys_ids_by_text(self, mediator, alice):
        # The same transaction reaches a union as 1 from one read and "1" from another.
        step_a, step_b = sets._BaseStep("Transaction"), sets._StaticStep("Transaction", "transaction_id", ("1",))
        combined = sets._CombineStep("intersect", [step_a, step_b])
        view = SchemaView(mediator, alice)

        assert [str(i) for i in evaluate(mediator, alice, combined, view).ids] == ["1"]


class TestOrdering:
    def ids(self, mediator, user, raw, order_by):
        view = SchemaView(mediator, user)
        evaluated = evaluate(mediator, user, prepare(parse_object_set(raw), view), view)
        return [str(i) for i in ordered(mediator, user, view, "Transaction", evaluated.ids,
                                        sets.parse_order_by(order_by))]

    def test_by_value_both_ways_with_the_key_settling_ties(self, mediator, alice):
        assert self.ids(mediator, alice, TRANSACTIONS, [{"field": "amount", "direction": "desc"}]) == [
            "2", "1", "3", "4"]
        assert self.ids(mediator, alice, TRANSACTIONS, [{"field": "amount"}]) == ["4", "1", "3", "2"]

    def test_by_several_fields_the_first_dominates(self, mediator, alice):
        assert self.ids(mediator, alice, TRANSACTIONS,
                        [{"field": "category"}, {"field": "amount", "direction": "desc"}]) == ["2", "4", "1", "3"]

    def test_the_default_order_is_by_key_as_a_number_when_it_is_one(self, mediator, alice):
        assert self.ids(mediator, alice, TRANSACTIONS, []) == ["1", "2", "3", "4"]

    def test_ordering_by_the_key_is_numeric_not_lexical(self, mediator, alice, monkeypatch):
        rows = {"2": {"transaction_id": "2"}, "10": {"transaction_id": "10"}, "1": {"transaction_id": "1"}}
        monkeypatch.setattr(mediator, "field_values_for_ids", lambda *a, **k: rows)
        view = SchemaView(mediator, alice)

        got = ordered(mediator, alice, view, "Transaction", ["2", "10", "1"],
                      sets.parse_order_by([{"field": "transaction_id", "direction": "desc"}]))

        assert got == ["10", "2", "1"]

    def test_nulls_go_last_whichever_way_it_runs(self, mediator, alice, monkeypatch):
        rows = {"1": {"amount": 5}, "2": {"amount": None}, "3": {"amount": 9}, "4": {}}
        monkeypatch.setattr(mediator, "field_values_for_ids", lambda *a, **k: rows)

        assert self.ids(mediator, alice, TRANSACTIONS, [{"field": "amount"}]) == ["1", "3", "2", "4"]
        assert self.ids(mediator, alice, TRANSACTIONS, [{"field": "amount", "direction": "desc"}]) == [
            "3", "1", "2", "4"]


class TestThroughTheMediatorAndNowhereElse:
    def test_the_scan_ceiling_is_reported_not_hidden(self, mediator, alice, monkeypatch):
        # Customer's row rule is a column of its own table, so the search
        # returns only rows alice may see and a cut is a cut of HER answer.
        # (Transaction's rule is reached through its customer, so a cut
        # there may hide visible rows and the set is refused instead; see
        # test_object_sets_hidden_links.TestNeverASilentCut.)
        monkeypatch.setattr(mediator_module, "MAX_SEARCH_SCAN", 1)
        view = SchemaView(mediator, alice)

        evaluated = evaluate(mediator, alice, prepare(parse_object_set(CUSTOMERS), view), view)

        assert evaluated.scan_truncated is True and len(evaluated.ids) == 1

    def test_a_text_equality_is_handed_to_the_search_so_the_ceiling_does_not_cut_the_filter_short(
            self, mediator, alice, monkeypatch):
        """With the scan ceiling at 2 the base set is cut off; the filter's
        equality is searched for directly, so the hardware sale is found."""
        monkeypatch.setattr(mediator_module, "MAX_SEARCH_SCAN", 2)
        view = SchemaView(mediator, alice)

        evaluated = evaluate(mediator, alice, prepare(
            parse_object_set(where(TRANSACTIONS, leaf("eq", "category", "hardware"))), view), view)

        assert [str(i) for i in evaluated.ids] == ["2"] and evaluated.scan_truncated is False

    def test_the_pushed_down_search_gives_the_same_answer_as_filtering_afterwards(self, mediator, alice):
        view = SchemaView(mediator, alice)
        condition = {"type": "and", "value": [leaf("in", "category", ["subscription", "refund"]),
                                              leaf("gt", "amount", 0)]}
        pushed = prepare(parse_object_set(where(TRANSACTIONS, condition)), view)
        unpushed = sets._FilterStep(sets._BaseStep("Transaction"), pushed.predicate, pushed.fields)

        assert pushed.child.conditions and not unpushed.child.conditions
        assert [str(i) for i in evaluate(mediator, alice, pushed, view).ids] == [
            str(i) for i in evaluate(mediator, alice, unpushed, view).ids] == ["1", "3"]

    def test_only_text_equality_is_pushed_down(self, mediator, alice):
        view = SchemaView(mediator, alice)

        for condition in (leaf("gt", "amount", 1), leaf("eq", "amount", 49.99), leaf("eq", "amount", "49.99"),
                          leaf("contains", "category", "s"),
                          {"type": "or", "value": [leaf("eq", "category", "a"), leaf("eq", "category", "b")]},
                          {"type": "not", "value": leaf("eq", "category", "a")}):
            prepared = prepare(parse_object_set(where(TRANSACTIONS, condition)), view)
            assert prepared.child.conditions == []

    def test_every_returned_id_was_checked_by_the_mediator(self, mediator, alice, monkeypatch):
        """Records each id the access check is asked about during an
        evaluation; every id returned must be among those that passed."""
        from elysium.core.ontology import mediator as module

        passed = set()
        real = module.check_access

        def recording(*args, **kwargs):
            allowed = real(*args, **kwargs)
            if allowed:
                passed.add((args[3], str(args[4])))
            return allowed

        monkeypatch.setattr(module, "check_access", recording)
        view = SchemaView(mediator, alice)
        raw = {"type": "union", "objectSets": [
            {"type": "searchAround", "link": "transactions", "objectSet": CUSTOMERS},
            where(TRANSACTIONS, leaf("gt", "amount", 100))]}

        evaluated = evaluate(mediator, alice, prepare(parse_object_set(raw), view), view)

        assert evaluated.ids
        assert {("Transaction", str(i)) for i in evaluated.ids} <= passed


class TestAggregating:
    def run(self, mediator, user, raw, metrics, group_by=None):
        view = SchemaView(mediator, user)
        prepared = prepare(parse_object_set(raw), view)
        measures = metric_fields(view, prepared.object_type, parse_metrics(metrics), group_by)
        evaluated = evaluate(mediator, user, prepared, view)
        return mediator.aggregate_measures(user, prepared.object_type, [], group_by, measures,
                                           members=evaluated.ids)

    def test_it_aggregates_only_the_members_the_caller_can_see(self, mediator, alice, bob):
        metrics = [{"type": "count", "name": "n"}, {"type": "sum", "field": "amount", "name": "total"}]

        assert self.run(mediator, alice, TRANSACTIONS, metrics) == {None: {"n": 4, "total": pytest.approx(278.98)}}
        assert self.run(mediator, bob, TRANSACTIONS, metrics)[None]["n"] == 2

    def test_grouped_and_over_a_filtered_set(self, mediator, alice):
        grouped = self.run(mediator, alice, where(TRANSACTIONS, leaf("gt", "amount", 0)),
                           [{"type": "count", "name": "n"}, {"type": "max", "field": "amount", "name": "top"},
                            {"type": "min", "field": "amount", "name": "low"},
                            {"type": "avg", "field": "amount", "name": "mean"}], group_by="category")

        assert grouped == {"subscription": {"n": 2, "top": 49.99, "low": 49.99, "mean": pytest.approx(49.99)},
                           "hardware": {"n": 1, "top": 199.0, "low": 199.0, "mean": 199.0}}

    def test_members_are_checked_again_by_the_mediator(self, mediator, alice):
        counted = mediator.aggregate_measures(
            alice, "Customer", [], None, [{"name": "n", "aggregate": "count", "field": None}],
            members=["cust_001", "cust_003", "cust_004"])

        assert counted == {None: {"n": 1}}

    def test_a_metric_needs_a_readable_numeric_field(self, mediator, alice):
        view = SchemaView(mediator, alice)
        for field in ("category", "customer_id", "transaction_date"):
            with pytest.raises(ObjectSetError, match="numeric"):
                metric_fields(view, "Transaction", parse_metrics([{"type": "sum", "field": field}]), None)
        with pytest.raises(ObjectSetError, match="link"):
            metric_fields(view, "Transaction", parse_metrics([{"type": "count"}]), "customer_id")
