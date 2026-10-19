"""`security: unrestricted` (19 October, with the owner).

An object type everyone may see -- a product catalogue -- with the role
check still standing, and the lowest label for anything written into it.
core/ontology/unrestricted.py has the reasoning and the precedent.

Built on the shared Author/Book fixture with Book declared unrestricted:
authors stay compartmented by org, books become visible to anyone whose
role reads them.
"""

import copy
from types import SimpleNamespace

import pytest

from core.filters import as_equality_conditions
from core.intermediate_layer.auth import UserRecord, resolve_user_record
from core.ontology.object_type_validation import validate_object_types
from core.ontology.unrestricted import (
    UNRESTRICTED,
    as_stored_compartment,
    is_unrestricted,
    normalise_security_blocks,
)
from core.ontology.write_mediator import SubWrite, WriteMediator, _compartment_crossings
from tests.conftest import TEST_SCHEMA, author_book_mediator

USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "bob": {"org_id": "org-b", "role": "reader"},
    "nobody_in_particular": {"role": "reader"},   # no org at all
    "carol": {"org_id": "org-a"},                   # no role
}
ROLES = {"reader": {"allowed_actions": [
    "read:Author", "read:Author.author_id", "read:Author.name",
    "read:Book", "read:Book.book_id", "read:Book.title", "read:Book.year",
    "read:Book.author_id",
]}}


def _schema():
    schema = copy.deepcopy(TEST_SCHEMA)
    schema["Book"]["security"] = "unrestricted"
    return normalise_security_blocks({"object_types": schema})["object_types"]


def _user(name):
    return resolve_user_record(USERS, name, "org_id")


@pytest.fixture
def mediator(test_db_path):
    return author_book_mediator(test_db_path, _schema(), ROLES)


class TestDeclaringIt:
    def test_the_word_becomes_the_block(self):
        assert _schema()["Book"]["security"] == {"unrestricted": True}
        assert is_unrestricted(_schema()["Book"]) and not is_unrestricted(_schema()["Author"])

    def test_it_validates(self):
        validate_object_types(_schema())

    def test_a_missing_block_is_still_an_error(self):
        schema = _schema()
        del schema["Book"]["security"]
        with pytest.raises(ValueError, match="no security block"):
            validate_object_types(schema)

    def test_any_other_word_is_refused(self):
        schema = copy.deepcopy(TEST_SCHEMA)
        schema["Book"]["security"] = "public"
        normalise_security_blocks({"object_types": schema})
        with pytest.raises(ValueError, match="unrestricted"):
            validate_object_types(schema)

    def test_nothing_may_sit_beside_it(self):
        schema = _schema()
        schema["Book"]["security"] = {"unrestricted": True, "field": "title"}
        with pytest.raises(ValueError, match="takes nothing else"):
            validate_object_types(schema)

    def test_a_chain_may_not_end_at_it(self):
        """Otherwise the linking type becomes visible to everyone without
        anyone having written so -- and the error names THAT type."""
        schema = copy.deepcopy(TEST_SCHEMA)
        schema["Author"]["security"] = "unrestricted"
        normalise_security_blocks({"object_types": schema})
        with pytest.raises(ValueError, match="Object type 'Book': its security.via_field chain ends"):
            validate_object_types(schema)


class TestReading:
    def test_everyone_whose_role_reads_it_sees_every_one(self, mediator):
        for name in ("alice", "bob"):
            assert len(mediator.search_object(_user(name), "Book")) == 3, name

    def test_even_someone_with_no_compartment_at_all(self, mediator):
        assert len(mediator.search_object(_user("nobody_in_particular"), "Book")) == 3

    def test_the_role_check_still_stands(self, mediator):
        assert mediator.search_object(_user("carol"), "Book") == []

    def test_a_field_of_another_compartments_record(self, mediator):
        book = mediator.search_object(_user("alice"), "Book",
                                      as_equality_conditions({"title": "A New Glossary"}))[0]

        assert mediator.get_field(_user("alice"), "Book", book, "year") == 1952

    def test_the_restricted_type_beside_it_is_unchanged(self, mediator):
        assert mediator.search_object(_user("alice"), "Author") == ["auth_001"]
        assert mediator.search_object(_user("nobody_in_particular"), "Author") == []

    def test_its_label_is_the_lowest_never_none(self, mediator):
        """None means unresolvable, visible to nobody; this is neither."""
        assert mediator.security_value_of("Book", 1) is UNRESTRICTED


class TestWritingIsNotAWayOut:
    def test_a_labelled_value_written_into_it_is_a_crossing(self):
        assert _compartment_crossings({("Author", "auth_002"): "org-b"},
                                      {("Book", 1): UNRESTRICTED})

    def test_its_values_may_go_anywhere(self):
        assert _compartment_crossings({("Book", 1): UNRESTRICTED},
                                      {("Author", "auth_001"): "org-a"}) == []

    def test_a_new_record_of_it_is_labelled(self, mediator):
        """As None, creating a product from a restricted record's values
        would have been skipped by the crossing check."""
        writer = object.__new__(WriteMediator)
        writer._adapter_mediator = mediator

        label = writer._label_written(SubWrite("Book", None, "create", {"title": "x"}))

        assert label is UNRESTRICTED

    def test_writing_to_it_is_within_everyones_reach(self, mediator):
        writer = object.__new__(WriteMediator)
        writer._adapter_mediator = mediator
        # Only what the check reads: which objects, under which action.
        pending = SimpleNamespace(sub_writes=(SubWrite("Book", 3, "update", {"year": 1953}),),
                                  action_type_name="Fix")

        writer._refuse_writes_outside_current_mac(pending, _user("alice"))


def test_review_stores_record_it_as_shared():
    """The recipe and prediction gates read None as "shared by everyone
    who may review"; the sentinel, or its text, would hide a proposal
    from every reviewer."""
    assert as_stored_compartment(UNRESTRICTED) is None
    assert as_stored_compartment("org-a") == "org-a"


def test_a_user_without_a_compartment_is_still_refused_elsewhere(mediator):
    stranger = UserRecord(user_id="s", security_value=None, role_name="reader")

    assert mediator.search_object(stranger, "Author") == []
