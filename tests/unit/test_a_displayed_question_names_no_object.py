"""
A starter question shown to somebody who did not ask for it may not
name an object.

THE LEAK, in the shipped example file's own words:

    - user_id: user_alice
      query: "What are cust_001's recent transactions?"

Alice may see `cust_001`; Bob may not. Showing Bob that question tells
him a customer called `cust_001` EXISTS. He still cannot read it --
MAC refuses -- but he has learned of its existence from a system built
specifically to refuse that. `get_field` on a hidden object returns
`None`, indistinguishable from "no such object", ON PURPOSE.

THE `user_id` KEY DOES NOT SOLVE IT. That is the deployment author's
assertion about who should see the example, not something
`check_access` enforces. An author writing one under the wrong user,
or a user's grants changing afterwards, produces a quiet leak that
nothing detects -- which is why this is a check rather than a note.

THE PRECEDENT USES TWO MECHANISMS, NOT ONE. Google's advanced
autocomplete "only suggests search queries that are related to
documents that the searcher has access to" -- and then says plainly
that it "can't guarantee that PII won't be returned", layering a
denylist and an inspection pass that reviews "suggestions before
presenting them to the user at serving time". Per-caller filtering is
the first mechanism. This is the second, and it does not depend on an
author getting a `user_id` right.

SHAPE, NOT EXISTENCE, and the first version got this wrong. It read
the data and asked whether `cust_001` was a real customer. That is
worse in a way that only appears later: an example naming `cust_999`
passes today and becomes a leak the day somebody creates that
customer. The rule has to hold for the deployment's whole life.

Not asking is also better than asking carefully: "does this object
exist" is exactly the question MAC refuses to answer, and the first
version reached through the mediator into an adapter to ask it.
"""

import pytest

from core.display_safety import identifier_shaped, refuse_unsafe_display_examples


class TestWhatCountsAsNamingAnObject:
    @pytest.mark.parametrize("question,named", [
        ("What are cust_001's recent transactions?", "cust_001"),
        ("Show transactions for user_alice", "user_alice"),
        ("Which orders mention ORD4471?", "ORD4471"),
        ("Anything about txn_0007", "txn_0007"),
    ])
    def test_an_identifier_shaped_token_is_found(self, question, named):
        assert identifier_shaped(question) == named

    @pytest.mark.parametrize("question", [
        "Which customers have the largest balances?",
        "What are a customer recent transactions?",
        "Show me transactions from last month",
        "",
    ])
    def test_ordinary_prose_names_nothing(self, question):
        assert identifier_shaped(question) is None


class TestWhatIsDeliberatelyAllowed:
    """Refusing these would push authors toward vaguer examples for no
    gain, which makes the rule less likely to be kept."""

    @pytest.mark.parametrize("question", [
        "List orders from 2026",
        "Transactions over 500 last month",
        "The top 10 customers",
    ])
    def test_a_bare_number_is_not_an_identifier(self, question):
        assert identifier_shaped(question) is None


class TestOnlyDisplayedExamplesAreChecked:
    def test_an_example_without_the_marker_is_left_alone(self):
        """The demo runner's queries execute AS a named user through
        the mediator with MAC applied. Naming a real object there is a
        query, not a disclosure, and the difference is the point."""
        examples = [{"user_id": "user_alice",
                      "query": "What are cust_001's transactions?"}]

        refuse_unsafe_display_examples(examples)

    def test_a_displayed_example_naming_an_object_is_refused(self):
        examples = [{"user_id": "user_alice", "display": True,
                      "query": "What are cust_001's transactions?"}]

        with pytest.raises(ValueError, match="cust_001"):
            refuse_unsafe_display_examples(examples)

    def test_a_displayed_example_naming_nothing_is_fine(self):
        examples = [{"display": True,
                      "query": "What are a customer recent transactions?"}]

        refuse_unsafe_display_examples(examples)

    def test_no_examples_at_all_is_fine(self):
        refuse_unsafe_display_examples([])
        refuse_unsafe_display_examples(None)

    def test_a_malformed_entry_is_skipped_rather_than_crashing(self):
        """A config error should surface as a config error elsewhere,
        not as a traceback from the safety check."""
        refuse_unsafe_display_examples(["not a dict", {"display": True}])


class TestTheRefusalExplainsItself:
    def test_it_says_why_the_user_id_does_not_help(self):
        """The author's most likely next thought is "but I set
        user_id", so the message answers it before it is asked."""
        examples = [{"display": True, "query": "about cust_001"}]

        with pytest.raises(ValueError) as caught:
            refuse_unsafe_display_examples(examples)

        assert "user_id" in str(caught.value)
        assert "assertion about who should see" in str(caught.value)

    def test_it_offers_the_rewrite(self):
        examples = [{"display": True, "query": "about cust_001"}]

        with pytest.raises(ValueError, match="without naming an object"):
            refuse_unsafe_display_examples(examples)


class TestItIsActuallyCalled:
    def test_building_a_generation_runs_the_check(self):
        from pathlib import Path

        source = Path("core/deployment_loader.py").read_text()
        i = source.index("def build_generation")
        body = source[i:i + 4000]

        assert "refuse_unsafe_display_examples(examples)" in body

    def test_it_takes_no_mediator(self):
        """The first version reached through the mediator into an
        adapter to ask whether an object existed. Taking no mediator is
        how that stays gone."""
        import inspect

        parameters = inspect.signature(refuse_unsafe_display_examples).parameters

        assert list(parameters) == ["examples"]
