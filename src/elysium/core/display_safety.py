"""What may be shown to a user who has not asked for it.

A STARTER QUESTION CAN LEAK WHAT MAC HIDES, and the example in
`example_queries.yaml` is the shape of it:

    - user_id: user_alice
      query: "What are cust_001's recent transactions?"

Alice may see `cust_001`; Bob may not. Showing Bob that question tells
him a customer called `cust_001` EXISTS. He still cannot read it --
MAC refuses -- but he has learned of its existence from a system built
specifically to refuse that. `get_field` on a hidden object returns
`None`, indistinguishable from "no such object", ON PURPOSE.

THE `user_id` KEY DOES NOT SOLVE IT. That is the deployment author's
assertion about who should see what, not something `check_access`
enforces. An author writing an example under the wrong user, or a
user's grants changing afterwards, produces a quiet leak that nothing
detects.

WHAT THE PRECEDENT SAYS. Suggestion systems that take this seriously
filter per caller -- Google's advanced autocomplete "only suggests
search queries that are related to documents that the searcher has
access to" -- and then DO NOT TRUST THAT ALONE. Google states plainly
that it "can't guarantee that PII won't be returned in autocomplete
suggestions" and layers a denylist and an inspection pass over the
top, reviewing "suggestions before presenting them to the user at
serving time".

So: two mechanisms, not one. This module is the second -- the one that
does not depend on an author getting a `user_id` right.

WHAT IT DOES. A question marked for DISPLAY may not contain a token
shaped like an object id. Not "may not name an object the viewer cannot see", which
would make the check depend on who is looking and put it back on the
serving path; may not name one AT ALL. A question that names nothing
is safe to show anybody, which is the only property that survives a
grant changing later.

WHAT IT DOES NOT DO. It says nothing about the demo runner's queries.
Those execute AS a named user, through the mediator, with MAC applied
-- naming `cust_001` there is a query, not a display, and the
difference is the whole point.
"""

import re

#: Tokens worth testing against real data. Deliberately broad -- a
#: token is cheap to check and a missed one is a leak.
_CANDIDATE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{2,}")

#: Words that appear in every English question and are never an id.
#: Keeping this small matters: the cost of a false candidate is one
#: lookup, and the cost of a missing one is the thing being prevented.
_ORDINARY = frozenset("""
    what which who whom whose when where why how many much the and for
    with from this that these those recent latest last past show list
    find all any are was were has have had does did can could would
    their there here about into over under than then них
""".split())


def candidate_identifiers(question: str) -> list[str]:
    """Tokens in a question that could be an object id."""
    return [token for token in _CANDIDATE.findall(question or "")
            if token.lower() not in _ORDINARY]


def identifier_shaped(question: str) -> "str | None":
    """The first token in `question` that looks like an object id.

    SHAPE, NOT EXISTENCE, and the second design is the right one. My
    first version read the data and asked whether `cust_001` was a real
    customer. That is worse in a way that only shows up later: an
    example naming `cust_999` passes today and becomes a leak the day
    somebody creates that customer. The rule has to hold for the
    deployment's whole life, not for the moment it was written.

    It is also the owner's question answered literally -- whether a
    displayed example must "name no real object AT ALL". At all means
    the check never has to know what exists.

    AND IT NEEDS NO READ. The first version reached through the
    mediator into an adapter for a no-caller existence check, which is
    both awkward and exactly the question MAC refuses to answer. Not
    asking it is better than asking it carefully.

    WHAT COUNTS AS IDENTIFIER-SHAPED: a token holding an underscore or
    a digit, which is how every id in this project's own fixtures is
    written -- `cust_001`, `user_alice`, `txn_0007`. English prose in a
    question does not contain such tokens; a deployment that genuinely
    needs one in a displayed example can rewrite the question around
    it, which is the point.
    """
    for token in candidate_identifiers(question):
        if token.isdigit():
            # A BARE NUMBER IS NOT AN ID. "orders from 2026" and
            # "over 500" are ordinary questions, and refusing them
            # would push authors toward vaguer examples for no gain.
            continue
        if "_" in token:
            return token
        if any(character.isdigit() for character in token):
            # Letters AND digits together: `cust001`, `ORD4471`. A word
            # on its own never looks like this.
            return token
    return None


def refuse_unsafe_display_examples(examples: list) -> None:
    """Raise if an example marked for display names a real object.

    ONLY THOSE MARKED `display: true`. An example without it is the
    demo runner's, executed as a named user through the mediator with
    MAC applied, and naming a real object there is correct.
    """
    for example in examples or []:
        if not isinstance(example, dict) or not example.get("display"):
            continue
        question = example.get("query") or ""
        named = identifier_shaped(question)
        if named is not None:
            raise ValueError(
                f"the example query {question!r} is marked `display: true` "
                f"and names {named!r}, which is shaped like an object id.\n"
                f"\n"
                f"A question shown to someone who did not ask for it tells "
                f"them that object EXISTS, which is what MAC refuses to do: "
                f"a hidden object and a missing one are deliberately "
                f"indistinguishable.\n"
                f"\n"
                f"The `user_id` key does not make this safe -- it is an "
                f"assertion about who should see the example, not a check "
                f"that they may. Write the question without naming an "
                f"object (\"a customer's recent transactions\"), or drop "
                f"`display: true` if it is only for the demo runner."
            )
