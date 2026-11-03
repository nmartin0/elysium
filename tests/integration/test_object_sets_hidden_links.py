"""
A forward link whose target the caller cannot read behaves as NULL in every
object-set operation, exactly as get_field() answers it (rule NEW-1), and
the request-wide caps that keep a request from costing more than its
budget.

THE DEFECT THIS FILE PINS. Filtering and sorting read the RAW foreign key
of a link. get_field() withholds it when the target row is hidden (MAC) or
the target type unreadable (RBAC), but the batch read used for filtering
did not, so `eq`, `in`, `isNull` and an ordering recovered the hidden ids;
and visible_schema shows a link to a type the caller is not told about as
plain data, so text operators did too, prefix by prefix.

TWO WAYS A TARGET IS HIDDEN, tested separately:
  RBAC   a role that reads Transaction and not Customer: the target TYPE
         is unreadable, the link looks like data, and the field is refused
         in the words for an unknown one.
  MAC    the target TYPE is readable but this row is not: Transaction is
         made `security: unrestricted` for the test (the fixture's own
         Transaction takes its row rule from its customer, so a visible
         transaction never has a hidden customer), so alice reads
         transactions 5-7 whose customers are in other regions.
"""

import json
import types

import pytest

from elysium.core.access.auth import UserRecord, resolve_user_record
from elysium.core.ontology import mediator as mediator_module
from elysium.core.ontology import object_sets as sets
from elysium.core.ontology.object_sets import (
    ObjectSetError,
    OrderTerm,
    SchemaView,
    evaluate,
    metric_fields,
    ordered,
    parse_metrics,
    parse_object_set,
    prepare,
)

TRANSACTIONS = {"type": "base", "objectType": "Transaction"}
CUSTOMERS = {"type": "base", "objectType": "Customer"}
ABSENT = "nonexistent_field"


def where(object_set, condition):
    return {"type": "filter", "objectSet": object_set, "where": condition}


def leaf(kind, field, value):
    return {"type": kind, "field": field, "value": value}


@pytest.fixture
def alice(deployment):
    return resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)


@pytest.fixture
def tx_only(mediator, monkeypatch):
    """A us-west caller whose role reads Transaction and its customer_id
    column and NOT Customer: the link's target type is unreadable."""
    base = dict(mediator.roles["editor"])
    base["allowed_actions"] = frozenset({
        "read:Transaction", "read:Transaction.transaction_id", "read:Transaction.amount",
        "read:Transaction.customer_id"})
    roles = dict(mediator.roles)
    roles["tx_only"] = types.MappingProxyType(base)
    monkeypatch.setattr(mediator, "roles", types.MappingProxyType(roles))
    return UserRecord("user_probe", "us-west", "tx_only")


@pytest.fixture
def open_transactions(mediator, monkeypatch):
    """Transaction with no row rule, so a transaction can be visible while
    its customer is not."""
    monkeypatch.setitem(mediator.schema["Transaction"], "security", {"unrestricted": True})


def prepared(mediator, user, raw):
    view = SchemaView(mediator, user)
    return view, prepare(parse_object_set(raw), view)


def ids(mediator, user, raw):
    view, step = prepared(mediator, user, raw)
    return [str(i) for i in evaluate(mediator, user, step, view).ids]


def refusal(mediator, user, raw):
    with pytest.raises(ObjectSetError) as refused:
        prepared(mediator, user, raw)
    return refused.value


class TestATargetTypeTheCallerCannotReadRBAC:
    def test_the_fixture_is_the_reported_one(self, mediator, tx_only):
        """The link shows as plain data and get_field() says null: the
        premise of the defect, so the tests below cannot pass vacuously."""
        shown = mediator.visible_schema(tx_only)["Transaction"]["fields"]["customer_id"]
        assert shown["type"] == "data"
        assert ids(mediator, tx_only, TRANSACTIONS) == ["1", "2", "3", "4"]
        assert [mediator.get_field(tx_only, "Transaction", i, "customer_id") for i in "1234"] == [None] * 4

    @pytest.mark.parametrize("kind, value", [
        ("startsWith", "cust_001"), ("contains", "001"), ("eq", "cust_001"), ("in", ["cust_001"]),
        ("lt", "cust_999"), ("gt", "a"), ("isNull", False)])
    def test_no_filter_may_name_it(self, mediator, tx_only, kind, value):
        found = refusal(mediator, tx_only, where(TRANSACTIONS, leaf(kind, "customer_id", value)))
        absent = refusal(mediator, tx_only, where(TRANSACTIONS, leaf(kind, ABSENT, value)))

        assert str(found).replace("customer_id", "F") == str(absent).replace(ABSENT, "F")
        assert "Unknown field" in str(found)

    def test_nor_inside_and_or_not(self, mediator, tx_only):
        nested = {"type": "or", "value": [leaf("eq", "amount", 1),
                                          {"type": "not", "value": leaf("startsWith", "customer_id", "c")}]}
        assert "Unknown field" in str(refusal(mediator, tx_only, where(TRANSACTIONS, nested)))

    def test_no_ordering_may_name_it(self, mediator, tx_only):
        view = SchemaView(mediator, tx_only)
        with pytest.raises(ObjectSetError, match="Unknown field 'customer_id'"):
            ordered(mediator, tx_only, view, "Transaction", ["1", "2"], (OrderTerm("customer_id", True),))

    def test_no_grouping_or_metric_may_name_it(self, mediator, tx_only):
        view = SchemaView(mediator, tx_only)
        with pytest.raises(ObjectSetError, match="Unknown field 'customer_id'") as grouped:
            metric_fields(view, "Transaction", parse_metrics([{"type": "count"}]), "customer_id")
        assert "link" not in str(grouped.value)
        with pytest.raises(ObjectSetError, match="Unknown field 'customer_id'"):
            metric_fields(view, "Transaction", parse_metrics([{"type": "sum", "field": "customer_id"}]), None)

    def test_a_readable_data_field_is_unaffected(self, mediator, tx_only):
        assert ids(mediator, tx_only, where(TRANSACTIONS, leaf("gt", "amount", 100))) == ["2"]


class TestARowOfTheTargetTheCallerCannotSeeMAC:
    HIDDEN = {"5", "6", "7"}

    def test_the_fixture_is_the_reported_one(self, mediator, alice, open_transactions):
        assert set(ids(mediator, alice, TRANSACTIONS)) == {str(n) for n in range(1, 8)}
        assert {i: mediator.get_field(alice, "Transaction", i, "customer_id") for i in "1567"} == {
            "1": "cust_001", "5": None, "6": None, "7": None}

    def test_a_hidden_link_matches_no_comparison(self, mediator, alice, open_transactions):
        # cust_003 and cust_004 are in other regions; transactions 5-7 hold them.
        assert ids(mediator, alice, where(TRANSACTIONS, leaf("eq", "customer_id", "cust_003"))) == []
        assert ids(mediator, alice, where(TRANSACTIONS, leaf("in", "customer_id", ["cust_003", "cust_004"]))) == []

    def test_a_hidden_link_is_null_to_isnull_as_it_is_to_get_field(self, mediator, alice, open_transactions):
        assert set(ids(mediator, alice, where(TRANSACTIONS, leaf("isNull", "customer_id", True)))) == self.HIDDEN
        assert set(ids(mediator, alice, where(TRANSACTIONS, {"type": "not", "value": leaf(
            "eq", "customer_id", "cust_003")}))) == {str(n) for n in range(1, 8)}

    def test_a_visible_link_still_filters(self, mediator, alice, open_transactions):
        found = ids(mediator, alice, where(TRANSACTIONS, leaf("eq", "customer_id", "cust_001")))
        assert found and set(found) <= {"1", "2", "3", "4"}

    @pytest.mark.parametrize("descending", [False, True])
    def test_ordering_puts_hidden_links_with_the_nulls(self, mediator, alice, open_transactions, descending):
        view, step = prepared(mediator, alice, TRANSACTIONS)
        everything = evaluate(mediator, alice, step, view).ids

        result = ordered(mediator, alice, view, "Transaction", everything,
                         (OrderTerm("customer_id", descending),))

        assert [str(i) for i in result[-3:]] == ["5", "6", "7"]

    def test_the_search_is_narrowed_only_by_link_targets_the_caller_may_read(
            self, mediator, alice, open_transactions, monkeypatch):
        """eq/in on a link used to be refused pushdown (the raw key would
        make "does this hidden row exist" answerable). It is pushed down
        again, but only the target ids alice may read: a hidden one is null
        on every row, so a set naming only hidden ids is empty with no
        search at all."""
        seen = []
        real = mediator.search_object

        def spy(user, object_type, conditions=None, **kwargs):
            seen.append([(c.field, list(c.value)) for c in (conditions or [])])
            return real(user, object_type, conditions, **kwargs)

        monkeypatch.setattr(mediator, "search_object", spy)
        none_hidden = ids(mediator, alice, where(TRANSACTIONS, leaf("eq", "customer_id", "cust_003")))
        none_in = ids(mediator, alice, where(TRANSACTIONS, leaf("in", "customer_id", ["cust_003", "cust_999"])))
        mixed = ids(mediator, alice, where(TRANSACTIONS, leaf("in", "customer_id", ["cust_001", "cust_003"])))
        ids(mediator, alice, where(TRANSACTIONS, leaf("eq", "category", "refund")))

        assert none_hidden == [] and none_in == [] and mixed
        assert seen == [[("customer_id", ["cust_001"])], [("category", ["refund"])]]

    def test_masking_is_batched_and_logged_as_one_bulk_read(self, mediator, alice, open_transactions,
                                                            isolated_audit_log):
        log = isolated_audit_log / "audit.log"
        before = log.stat().st_size if log.exists() else 0

        mediator.field_values_for_ids(alice, "Transaction", list("1234567"), ["customer_id"])

        with open(log) as handle:
            handle.seek(before)
            entries = [json.loads(line) for line in handle if line.strip()]
        reads = [e for e in entries if e["stage"] == "bulk_read" and e["object_type"] == "Customer"]
        assert len(reads) == 1 and reads[0]["considered"] == 4 and reads[0]["denied"] == 2
        assert reads[0]["action"] == "read:Customer"


@pytest.fixture
def two_storages(mediator, monkeypatch):
    """The fixture mirrors every field into one place, so give Customer a
    field of a second storage the way an MDO deployment declares it."""
    monkeypatch.setitem(mediator.schema["Customer"]["fields"]["risk_score"], "storage", "risk_db")


class TestOneStorageOnly:
    def test_fields_of_two_storages_are_refused_with_one_sentence(self, mediator, alice, two_storages):
        error = refusal(mediator, alice, where(CUSTOMERS, {"type": "and", "value": [
            leaf("eq", "name", "x"), leaf("gt", "risk_score", 1)]}))

        assert str(error) == sets.MULTI_STORAGE_SENTENCE
        assert "risk" not in str(error).lower() and "name" not in str(error)
        assert error.parameters == {"objectType": "Customer"}

    def test_a_single_secondary_storage_is_fine(self, mediator, alice, two_storages):
        refusal_free = prepared(mediator, alice, where(CUSTOMERS, leaf("gt", "risk_score", 1)))
        assert refusal_free

    def test_ordering_and_grouping_across_storages(self, mediator, alice, two_storages):
        view = SchemaView(mediator, alice)
        with pytest.raises(ObjectSetError) as ordering:
            ordered(mediator, alice, view, "Customer", ["cust_001"],
                    (OrderTerm("name"), OrderTerm("risk_score")))
        assert str(ordering.value) == sets.MULTI_STORAGE_SENTENCE
        with pytest.raises(ObjectSetError) as grouping:
            metric_fields(view, "Customer", parse_metrics([{"type": "sum", "field": "risk_score"}]), "name")
        assert str(grouping.value) == sets.MULTI_STORAGE_SENTENCE


class TestOneBudgetForTheWholeRequest:
    @staticmethod
    def a_filter_of(width):
        return where(TRANSACTIONS, {"type": "and", "value": [leaf("eq", "amount", n) for n in range(width)]})

    def test_filter_nodes_are_counted_across_every_filter_set(self):
        one = self.a_filter_of(sets.MAX_FILTER_NODES - 2)  # 'and' + leaves = MAX - 1
        sets.parse_object_set(one)

        with pytest.raises(ObjectSetError, match=f"At most {sets.MAX_FILTER_NODES} filter nodes"):
            sets.parse_object_set({"type": "union", "objectSets": [one, one]})

    def test_in_values_are_counted_across_every_in(self):
        per = sets.MAX_TOTAL_IN_VALUES // 3 + 1
        assert per <= sets.MAX_IN_VALUES

        def one():
            return where(TRANSACTIONS, leaf("in", "amount", list(range(per))))

        sets.parse_object_set({"type": "union", "objectSets": [one(), one()]})
        with pytest.raises(ObjectSetError, match=f"At most {sets.MAX_TOTAL_IN_VALUES} `in` values"):
            sets.parse_object_set({"type": "union", "objectSets": [one(), one(), one()]})

    def test_in_matches_by_lookup_not_by_scanning_every_value(self, mediator, alice, monkeypatch):
        compared = []

        class Counted:
            def __init__(self, value):
                self.value = value

            def __eq__(self, other):
                compared.append(1)
                return isinstance(other, Counted) and self.value == other.value

            def __hash__(self):
                return hash(self.value)

        monkeypatch.setattr(sets, "_typed", lambda value, data_type: Counted(value))
        view = SchemaView(mediator, alice)
        predicate = sets.compile_filter(
            sets.parse_filter(leaf("in", "amount", list(range(1000)))), view, "Transaction", {})

        assert predicate({"amount": 999}) is True
        assert predicate({"amount": 5000}) is False
        assert len(compared) <= 4

    def test_the_budget_is_charged_from_the_shape_before_anything_runs(self, mediator, alice, monkeypatch):
        # A search leaf is worth the scan ceiling (10,000), whatever it finds.
        monkeypatch.setattr(sets, "MAX_SCANNED_ROWS", 15_000)
        both = {"type": "union", "objectSets": [TRANSACTIONS, TRANSACTIONS]}
        searched = []
        real = mediator.search_object
        monkeypatch.setattr(mediator, "search_object",
                            lambda *a, **k: searched.append(1) or real(*a, **k))

        assert len(ids(mediator, alice, TRANSACTIONS)) == 4
        with pytest.raises(ObjectSetError, match="more than 15000 objects"):
            prepared(mediator, alice, both)
        with pytest.raises(ObjectSetError, match="more than 15000 objects"):
            prepared(mediator, alice, {"type": "searchAround", "link": "customer_id", "objectSet": TRANSACTIONS})
        assert searched == [1], "only the first, affordable request searched"

    def test_a_static_leaf_costs_its_keys(self, mediator, alice, monkeypatch):
        monkeypatch.setattr(sets, "MAX_SCANNED_ROWS", 3)
        keys = {"type": "static", "objectType": "Transaction"}

        prepared(mediator, alice, {**keys, "primaryKeys": ["1", "2", "3"]})
        with pytest.raises(ObjectSetError, match="more than 3 objects"):
            prepared(mediator, alice, {**keys, "primaryKeys": ["1", "2", "3", "4"]})

    @pytest.mark.parametrize("cap", [1, 100_000])
    def test_a_guessed_id_never_changes_whether_the_request_is_refused(self, mediator, monkeypatch, cap):
        """THE ORACLE. A budget charged by what each leaf looked at refused
        a request naming an id only if a hidden row had that id: a caller
        who sees nothing could ask about 1, 5, 7 (refused) and 9, 12, 99999
        (served) and learn which exist. Charged from the shape of the set,
        every guess gets the same answer."""
        monkeypatch.setattr(sets, "MAX_SCANNED_ROWS", cap)
        nobody = UserRecord("n", "nowhere", "customer_service")
        outcomes = set()
        for guess in ("1", "5", "7", "9", "12", "99999"):
            raw = {"type": "union", "objectSets": [where(
                TRANSACTIONS, leaf("eq", "transaction_id", guess))] * 2}
            try:
                ids(mediator, nobody, raw)
                outcomes.add("served")
            except ObjectSetError as error:
                outcomes.add(str(error))

        assert len(outcomes) == 1


class TestNeverASilentCut:
    def test_a_cut_of_the_callers_own_answer_is_reported(self, mediator, monkeypatch):
        """Customer's row rule is a column of its own table, so every row the
        search scanned was visible: the cut is a cut of the answer."""
        monkeypatch.setattr(mediator_module, "MAX_SEARCH_SCAN", 1)
        alice = UserRecord("a", "us-west", "customer_service")
        view, step = prepared(mediator, alice, CUSTOMERS)

        evaluated = evaluate(mediator, alice, step, view)

        assert evaluated.scan_truncated is True and len(evaluated.ids) == 1

    @pytest.mark.parametrize("region", ["us-west", "us-east", "nowhere"])
    def test_a_cut_that_may_hide_visible_rows_is_refused_the_same_for_everyone(self, mediator, monkeypatch,
                                                                              region):
        """Transaction's row rule is reached through its customer, so a scan
        cut at the ceiling is a mix of rows the caller can and cannot see.
        Returning the visible part would be an incomplete set marked
        complete (bob, whose rows are 5-6, would get nothing, or one row);
        reporting the mediator's flag would say how many rows exist. The
        same sentence for every caller, whatever they can see."""
        monkeypatch.setattr(mediator_module, "MAX_SEARCH_SCAN", 5)
        user = UserRecord("u", region, "customer_service")

        with pytest.raises(ObjectSetError) as refused:
            ids(mediator, user, TRANSACTIONS)

        assert str(refused.value) == sets.TOO_LARGE_SENTENCE and refused.value.parameters == {}

    def test_below_the_ceiling_nothing_changes(self, mediator, monkeypatch):
        monkeypatch.setattr(mediator_module, "MAX_SEARCH_SCAN", 7)
        bob = UserRecord("b", "us-east", "customer_service")

        assert ids(mediator, bob, TRANSACTIONS) == ["5", "6"]

    def test_search_around_that_reaches_the_ceiling_is_refused_too(self, mediator, monkeypatch):
        monkeypatch.setattr(mediator_module, "MAX_SEARCH_SCAN", 1)
        alice = UserRecord("a", "us-west", "customer_service")

        with pytest.raises(ObjectSetError) as refused:
            ids(mediator, alice, {"type": "searchAround", "link": "transactions", "objectSet": CUSTOMERS})

        assert str(refused.value) == sets.TOO_LARGE_SENTENCE


class TestAForwardSearchAroundIsOneBulkRead:
    def test_sources_are_logged_once_not_once_each(self, mediator, alice, isolated_audit_log):
        log = isolated_audit_log / "audit.log"
        before = log.stat().st_size if log.exists() else 0

        found = ids(mediator, alice, {"type": "searchAround", "link": "customer_id", "objectSet": TRANSACTIONS})

        with open(log) as handle:
            handle.seek(before)
            entries = [json.loads(line) for line in handle if line.strip()]
        assert set(found) == {"cust_001", "cust_002"}
        per_source = [e for e in entries if e["stage"] == "access_check"
                      and e.get("action") == "read:Transaction.customer_id"]
        bulk = [e for e in entries if e["stage"] == "bulk_read" and e["action"] == "read:Transaction.customer_id"]
        assert per_source == [] and len(bulk) == 1 and bulk[0]["considered"] == 4

    def test_a_hidden_target_is_still_dropped(self, mediator, alice, open_transactions):
        assert set(ids(mediator, alice, {"type": "searchAround", "link": "customer_id",
                                         "objectSet": TRANSACTIONS})) == {"cust_001", "cust_002"}

    def test_a_field_the_role_may_not_read_yields_nothing(self, mediator, tx_only):
        assert mediator.search_around_from(tx_only, "Transaction", ["1"], "customer_id") == []


class TestAnOpaqueReferenceIsNotAHiddenOne:
    def test_a_link_to_a_type_that_is_not_declared_can_still_be_filtered(self, mediator, alice, monkeypatch):
        """A target that is not an object type at all (an id into some
        other system) has no row to hide and no rule to enforce; refusing
        it as unknown would remove a field the caller was shown."""
        monkeypatch.setitem(mediator.schema["Transaction"]["fields"], "agent",
                            {"type": "link", "target": "Agent", "cardinality": "one"})
        service = dict(mediator.roles["customer_service"])
        service["allowed_actions"] = service["allowed_actions"] | {"read:Transaction.agent"}
        roles = dict(mediator.roles)
        roles["customer_service"] = types.MappingProxyType(service)
        monkeypatch.setattr(mediator, "roles", types.MappingProxyType(roles))
        view = SchemaView(mediator, alice)

        spec = view.filterable("Transaction", "agent")

        assert spec.name == "agent" and spec.is_link is False

    def test_a_link_to_a_declared_type_the_caller_cannot_see_is_still_refused(self, mediator, tx_only):
        with pytest.raises(ObjectSetError, match="Unknown field 'customer_id'"):
            SchemaView(mediator, tx_only).filterable("Transaction", "customer_id")
