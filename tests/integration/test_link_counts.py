"""
How far a link leads, before following it.

COUNTS BEFORE EXPANSION is the whole design of the link explorer, as
ROADMAP.md records it: show link-type counts BEFORE expansion, so
fan-out is never a surprise. A person deciding whether to follow a link
needs to know it leads to four things or four thousand before they
commit, and an explorer that expands first and apologises later is
unusable on real data.

EVERY COUNT IS WHAT THIS CALLER WOULD RECEIVE. MAC and RBAC apply on
the far side, so the number cannot disagree with the expansion that
follows -- and cannot leak the size of data they may not see, which a
count of what merely EXISTS would do.
"""


from core.intermediate_layer.auth import UserRecord

ALICE = UserRecord("alice", "us-west", "customer_service")


def test_a_one_to_many_link_reports_its_size(mediator):
    counts = mediator.link_counts(ALICE, "Customer", "cust_001")

    assert counts["transactions"]["count"] == 2
    assert counts["transactions"]["target"] == "Transaction"
    assert counts["transactions"]["cardinality"] == "many"


def test_a_many_to_one_link_reports_one(mediator):
    # The reverse direction, which a link explorer needs as much: from
    # a transaction back to its customer.
    counts = mediator.link_counts(ALICE, "Transaction", 1)

    assert counts["customer_id"]["count"] == 1
    assert counts["customer_id"]["target"] == "Customer"


def test_only_link_fields_are_reported(mediator):
    # A data field is not somewhere you can navigate to. Including one
    # would offer an expansion that cannot happen.
    counts = mediator.link_counts(ALICE, "Customer", "cust_001")

    assert "name" not in counts
    assert "email" not in counts


def test_the_count_matches_what_expansion_returns(mediator):
    """THE PROPERTY THAT MAKES THE COUNT WORTH SHOWING.

    A count derived differently from the expansion would eventually
    disagree with it, and a number that turns out wrong is worse than
    no number -- it is the surprise this feature exists to prevent,
    arriving with false confidence attached.
    """
    from core.filters import parse_filters

    counts = mediator.link_counts(ALICE, "Customer", "cust_001")
    expanded = mediator.search_around(
        ALICE, "Customer",
        parse_filters([{"field": "customer_id", "operator": "equals", "value": "cust_001"}]),
        "transactions",
    )

    assert counts["transactions"]["count"] == len(expanded)


def test_an_unknown_object_reports_no_links(mediator):
    # Uniform denial: an id that does not exist and one the caller may
    # not see must answer identically, or this becomes a probe for
    # which objects exist.
    # ASSERTED ON THE COUNTS, not on the whole dict. A first version
    # hard-coded this deployment's link fields and failed because the
    # fixture has three -- pinning the fixture's schema rather than the
    # behaviour under test.
    counts = mediator.link_counts(ALICE, "Customer", "no_such_customer")

    assert counts, "an unknown object should still report its link SHAPE"
    assert all(link["count"] == 0 for link in counts.values())


def test_a_type_the_caller_cannot_see_reports_nothing(mediator):
    stranger = UserRecord("stranger", "us-west", None)

    assert mediator.link_counts(stranger, "Customer", "cust_001") == {}


def test_a_link_to_an_invisible_TYPE_is_omitted(mediator):
    """Not reported as zero -- omitted.

    A link to a type the caller cannot discover is not a link they
    have, and naming it with a count of zero would say the deployment
    holds something they were never told about.
    """
    granted = set(mediator.roles["customer_service"]["allowed_actions"])
    mediator.roles = {
        **mediator.roles,
        "no_transactions": {
            **mediator.roles["customer_service"],
            "allowed_actions": frozenset(
                action for action in granted if not action.startswith(("read:Transaction", "discover:Transaction"))
            ),
        },
    }
    limited = UserRecord("limited", "us-west", "no_transactions")

    assert "transactions" not in mediator.link_counts(limited, "Customer", "cust_001")


def test_a_withheld_link_field_is_omitted(mediator):
    # The middle rung of the grant ladder. A field the caller may know
    # exists but not READ cannot be counted either -- the count would
    # be derived from data they are not permitted to see.
    granted = set(mediator.roles["customer_service"]["allowed_actions"])
    mediator.roles = {
        **mediator.roles,
        "spotter": {
            **mediator.roles["customer_service"],
            "allowed_actions": frozenset(
                (granted - {"read:Customer.transactions"}) | {"discover:Customer.transactions"},
            ),
        },
    }
    spotter = UserRecord("spotter", "us-west", "spotter")

    assert "transactions" not in mediator.link_counts(spotter, "Customer", "cust_001")
