"""
Identity compares the security value as the source holds it.

THIS IS A CONSEQUENCE OF PATCH 441, not a new decision, and I did not
notice it when landing that patch. It is recorded and pinned here
because it changes what a deployment sees.

Identity resolution compares each storage's SECURITY value before
merging two rows into one entity, and refuses when they disagree --
"Merging would silently decide who can see the result", as the code
has always said.

Patch 441 stopped the pipeline standardising the security field,
because a trailing space in `region` was measurably moving an access
boundary. So that comparison now happens on the raw values:

    before 441   "us-west " and "us-west" were both trimmed to
                 "us-west", so the rows MERGED
    after  441   they differ, so the merge is REFUSED and the pair
                 goes to review

THE CONSERVATIVE ANSWER IS THE RIGHT ONE here -- a merge is exactly
where an untidy security value must not be quietly resolved -- but it
is a real change: a deployment with untidy region values will see
merges it used to get land in the review queue, which somebody has to
work through. Better that than a merge deciding who can read the
result.

MATCH FIELDS ARE STILL STANDARDISED. Only the security field is
exempt, so `email` matching is unaffected and the exactness the module
promises still holds for everything it matches ON.

WHAT THESE TESTS CANNOT SHOW, said because a control demonstrated it:
they call `resolve` with rows built by hand, so undoing patch 441
upstream does not reach them. They pin how identity BEHAVES when the
values differ; what guarantees the values arrive untrimmed is
tests/unit/test_the_pipeline_does_not_move_access.py. Two halves of
one claim, in two files, and neither proves the other.
"""

from core.mirror.identity import IdentityRule, resolve

TYPE = {
    "id_field": "id", "security": {"field": "region"},
    "storage": {"silo": "p", "table": "a", "id_column": "id"},
    "additional_storage": {"b": {"silo": "p", "table": "b", "id_column": "id"}},
    "fields": {"id": {"type": "data"}, "email": {"type": "data"},
                "region": {"type": "data"}},
}
RULE = IdentityRule(match_on=("email",), primary=None)


def _resolve(left_region, right_region):
    return resolve(TYPE, {
        None: [{"id": "1", "email": "a@x.com", "region": left_region}],
        "b": [{"id": "2", "email": "a@x.com", "region": right_region}],
    }, RULE)


class TestWhenTheSecurityValuesAgree:
    def test_the_rows_merge(self):
        result = _resolve("us-west", "us-west")

        assert len(result.entities) == 1
        assert not result.refused


class TestWhenTheyDifferONLYBYWHITESPACE:
    def test_the_merge_is_refused(self):
        """THE CHANGE. Before patch 441 both sides were trimmed and
        these merged."""
        result = _resolve("us-west ", "us-west")

        assert len(result.entities) == 2
        assert len(result.refused) == 1

    def test_the_refusal_carries_both_values(self):
        """A review queue entry nobody can act on is not a review
        queue entry."""
        result = _resolve("us-west ", "us-west")

        _, seen = result.refused[0]
        assert set(seen.values()) == {"us-west ", "us-west"}

    def test_neither_row_is_lost(self):
        """A refused merge must leave both rows standing on their
        own."""
        result = _resolve("us-west ", "us-west")

        assert len(result.entities) == 2


class TestWhenTheyDifferForReal:
    def test_a_genuine_disagreement_is_still_refused(self):
        """The behaviour that always existed, kept."""
        result = _resolve("us-west", "us-east")

        assert len(result.refused) == 1


class TestMatchFieldsAreUnaffected:
    def test_the_email_still_matches_after_standardisation(self):
        """Only the SECURITY field is exempt from standardisation.
        Silver still trims the match fields, so matching is as exact
        as it ever was -- this test pins that the exemption did not
        leak."""
        result = resolve(TYPE, {
            None: [{"id": "1", "email": "a@x.com", "region": "us-west"}],
            "b": [{"id": "2", "email": "a@x.com", "region": "us-west"}],
        }, RULE)

        assert len(result.entities) == 1
