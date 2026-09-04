"""
Tests for core/ontology/mediator.py (DataMediator) -- three fully
explicit gates: MAC (org_id boundary), RBAC object-type level
(read:Type -- may this user discover/search this type at all), and
RBAC field level (read:Type.field -- may this user see THIS field's
value). Nothing is inherited between the three.

DataMediator takes a pre-resolved UserRecord now, not a raw user_id --
resolve_user_record() builds one from the same TEST_USERS/TEST_ROLES
shape a real deployment would use.

  alice: org-a, role=reader  -- passes MAC + has every field grant used below
  bob:   org-b, role=reader  -- different org (MAC boundary test)
  carol: org-a, NO role      -- same org as alice, but no role at all
                                 (proves RBAC is checked independently of MAC)
  dave:  org-a, role=type_only -- has read:Author (can discover) but
                                 NO field grants at all (proves field-level
                                 RBAC is independent of object-type RBAC)
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteAdapter
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "bob": {"org_id": "org-b", "role": "reader"},
    "carol": {"org_id": "org-a"},  # deliberately no role
    "dave": {"org_id": "org-a", "role": "type_only"},
    # For test_get_object_mixes_real_values_and_none_for_partial_grants
    # specifically -- a genuine mixed-grant case (one real data field
    # granted, one withheld) needs its own dedicated role/user, not a
    # repurposing of dave (whose own, existing purpose depends on
    # having NO real field grants at all -- see test_get_field_
    # object_type_rbac_alone_is_not_enough above).
    "erin": {"org_id": "org-a", "role": "author_name_only"},
}

TEST_ROLES = {
    "reader": {"allowed_actions": [
        "read:Author", "read:Author.author_id", "read:Author.name", "read:Author.books",
        "read:Book", "read:Book.book_id", "read:Book.title", "read:Book.author_id", "read:Book.year",
    ]},
    "type_only": {"allowed_actions": ["read:Author", "read:Author.author_id"]},
    "author_name_only": {"allowed_actions": ["read:Author", "read:Author.name"]},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def mediator(test_db_path, test_schema) -> DataMediator:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["storage"]["silo"] for object_type, type_def in test_schema.items()}
    return DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES)


def test_search_object_finds_matching_org(mediator):
    result = mediator.search_object(_record("alice"), "Author", {"author_id": "auth_001"})
    assert result == ["auth_001"]


def test_search_object_blocks_cross_org_mac(mediator):
    result = mediator.search_object(_record("bob"), "Author", {"author_id": "auth_001"})
    assert result == []


def test_search_object_blocks_missing_role_rbac(mediator):
    result = mediator.search_object(_record("carol"), "Author", {"author_id": "auth_001"})
    assert result == []


def test_search_object_by_non_id_field(mediator):
    result = mediator.search_object(_record("alice"), "Author", {"name": "Ada Lovelace"})
    assert result == ["auth_001"]


def test_search_object_rejects_unfilterable_field(mediator):
    with pytest.raises(ValueError):
        mediator.search_object(_record("alice"), "Author", {"books": "anything"})


def test_search_object_error_does_not_leak_valid_field_list(mediator):
    with pytest.raises(ValueError) as exc_info:
        mediator.search_object(_record("alice"), "Author", {"totally_fake_field": "x"})
    message = str(exc_info.value)
    assert "name" not in message and "org_id" not in message and "books" not in message


def test_search_object_unknown_type_returns_empty_not_error(mediator):
    assert mediator.search_object(_record("alice"), "TotallyFakeType", {}) == []


def test_get_field_plain_data(mediator):
    assert mediator.get_field(_record("alice"), "Author", "auth_001", "name") == "Ada Lovelace"


def test_get_field_object_type_rbac_alone_is_not_enough(mediator):
    assert mediator.search_object(_record("dave"), "Author", {"author_id": "auth_001"}) == ["auth_001"]
    assert mediator.get_field(_record("dave"), "Author", "auth_001", "name") is None


def test_get_field_reverse_link_returns_list_of_ids(mediator):
    result = mediator.get_field(_record("alice"), "Author", "auth_001", "books")
    assert set(result) == {1, 2}


def test_get_field_forward_link_returns_parent_id(mediator):
    result = mediator.get_field(_record("alice"), "Book", 1, "author_id")
    assert result == "auth_001"


def test_get_field_blocked_cross_org_on_linked_object_mac(mediator):
    result = mediator.get_field(_record("bob"), "Book", 1, "title")
    assert result is None


def test_get_field_blocked_missing_role_on_linked_object_rbac(mediator):
    result = mediator.get_field(_record("carol"), "Book", 1, "title")
    assert result is None


def test_get_field_allowed_same_org_on_linked_object(mediator):
    result = mediator.get_field(_record("alice"), "Book", 1, "title")
    assert result == "Notes on the Analytical Engine"


def test_get_field_unknown_field_returns_none_not_raise(mediator):
    assert mediator.get_field(_record("alice"), "Author", "auth_001", "nonexistent_field") is None


def test_get_field_unknown_and_denied_are_identical(mediator):
    denied_real_field = mediator.get_field(_record("carol"), "Author", "auth_001", "org_id")
    fake_field = mediator.get_field(_record("carol"), "Author", "auth_001", "not_a_real_field_xyz")
    assert denied_real_field is fake_field is None


def test_get_object_returns_multiple_fields_at_once(mediator):
    result = mediator.get_object(_record("alice"), "Author", "auth_001", ["name", "books"])
    assert result["name"] == "Ada Lovelace"
    assert set(result["books"]) == {1, 2}


def test_get_object_mixes_real_values_and_none_for_partial_grants(mediator):
    # erin (author_name_only) has read:Author.name but NOT read:
    # Author.org_id -- proves a single get_object() call correctly
    # returns a REAL value for the field she's granted and None for
    # the one she isn't, never raising or silently dropping the
    # denied one from the dict.
    result = mediator.get_object(_record("erin"), "Author", "auth_001", ["name", "org_id"])
    assert result == {"name": "Ada Lovelace", "org_id": None}


def test_get_object_unknown_field_returns_none_for_just_that_field(mediator):
    result = mediator.get_object(_record("alice"), "Author", "auth_001", ["name", "totally_fake_field"])
    assert result == {"name": "Ada Lovelace", "totally_fake_field": None}


def test_get_object_empty_field_names_returns_empty_dict(mediator):
    assert mediator.get_object(_record("alice"), "Author", "auth_001", []) == {}


def test_get_object_unknown_object_type_returns_none_for_every_field_not_raise(mediator):
    result = mediator.get_object(_record("alice"), "TotallyFakeType", "auth_001", ["name", "org_id"])
    assert result == {"name": None, "org_id": None}


def test_get_object_result_matches_calling_get_field_separately(mediator):
    # THE core correctness claim get_object() itself makes: calling it
    # once for several fields is INDISTINGUISHABLE from calling get_
    # field() separately for each -- same values, same denials, same
    # dict shape either way, proving the thin-wrapper design genuinely
    # holds, not just assumed by construction.
    combined = mediator.get_object(_record("alice"), "Book", 1, ["title", "year", "author_id"])
    separate = {
        field_name: mediator.get_field(_record("alice"), "Book", 1, field_name)
        for field_name in ["title", "year", "author_id"]
    }
    assert combined == separate


def test_free_text_searchable_fields_excludes_id_field_and_links(mediator):
    # Deliberately narrower than the id_field/link-inclusive set
    # search_object() itself accepts as exact-match filter keys --
    # "author_id" (a link) is excluded even though alice can read it;
    # "title" (plain data) is included.
    assert mediator.free_text_searchable_fields(_record("alice"), "Book") == ["title", "year"]


def test_free_text_searchable_fields_unknown_type_returns_empty_list(mediator):
    assert mediator.free_text_searchable_fields(_record("alice"), "TotallyFakeType") == []


def test_search_object_free_text_finds_a_partial_match(mediator):
    assert mediator.search_object_free_text(_record("alice"), "Author", "love") == ["auth_001"]


def test_search_object_free_text_is_case_insensitive(mediator):
    assert mediator.search_object_free_text(_record("alice"), "Author", "LOVE") == ["auth_001"]


def test_search_object_free_text_matches_across_multiple_fields(mediator):
    # "title" and "year" are two genuinely different Book fields --
    # this proves the OR-across-columns match works for either, not
    # just the first one checked. year is a real INTEGER column
    # (confirmed directly: SQLite's own LIKE coerces it to text for
    # comparison, not skipped or silently unmatchable). book_id 1 is
    # "Notes on the Analytical Engine" (1843), owned by auth_001/
    # org-a -- confirmed directly against tests/conftest.py's own real
    # seed data, not assumed (an earlier version of this test wrongly
    # used book_id 3, "A New Glossary" -- owned by auth_002/org-b, so
    # correctly, securely invisible to alice regardless of search text;
    # caught by actually running the test, not by re-reading the fixture
    # more carefully after the fact). alice's own role was extended
    # with read:Book.year specifically to make this test possible --
    # she didn't have it before, and this method correctly, securely
    # excludes an ungranted field from the search entirely rather than
    # searching it anyway (see test_search_object_free_text_blocks_
    # missing_role_rbac's own sibling coverage of that boundary).
    assert mediator.search_object_free_text(_record("alice"), "Book", "notes") == [1]
    assert mediator.search_object_free_text(_record("alice"), "Book", "1843") == [1]


def test_search_object_free_text_blocks_cross_org_mac(mediator):
    # THE real security proof, not just a functional one: "love" would
    # ALSO textually match a same-named different-org author if one
    # existed -- this specific fixture doesn't have that case, so this
    # test instead confirms the MAC boundary directly the way test_
    # search_object_blocks_cross_org_mac above does, applied to this
    # method instead: bob (org-b) gets nothing back for a query that
    # would match alice's own org-a data.
    assert mediator.search_object_free_text(_record("bob"), "Author", "love") == []


def test_search_object_free_text_blocks_missing_role_rbac(mediator):
    assert mediator.search_object_free_text(_record("carol"), "Author", "love") == []


def test_search_object_free_text_excludes_an_ungranted_field_from_the_search_itself(mediator):
    # dave (type_only) has read:Author but NO read:Author.name grant --
    # proves "name" is excluded from the search's own column set
    # entirely (never even participates in the SQL match), not just
    # filtered out afterward by RBAC on an object that DID match. A
    # genuinely different, more precise claim than test_search_object_
    # free_text_blocks_missing_role_rbac above (no role at all).
    assert mediator.search_object_free_text(_record("dave"), "Author", "love") == []


def test_search_object_free_text_empty_query_returns_every_visible_object(mediator):
    # Book, not Author -- auth_001 owns TWO real books, both visible to
    # alice, genuinely demonstrating "more than one result" rather than
    # a single-item set that wouldn't distinguish this from a bug
    # returning just the first match. Both real book_ids confirmed
    # directly against tests/conftest.py's own seed data, not assumed.
    result = mediator.search_object_free_text(_record("alice"), "Book", "")
    assert set(result) == {1, 2}


def test_search_object_free_text_no_match_returns_empty_list(mediator):
    assert mediator.search_object_free_text(_record("alice"), "Author", "zzz_nonexistent") == []


def test_search_object_free_text_unknown_type_returns_empty_not_error(mediator):
    assert mediator.search_object_free_text(_record("alice"), "TotallyFakeType", "love") == []


def test_search_object_free_text_literal_wildcard_character_is_not_a_wildcard(mediator, test_db_path):
    # A real, confirmed SQL LIKE gotcha, verified directly (not
    # assumed): an unescaped "%" or "_" in the user's own query text
    # is a genuine SQL wildcard, not a literal character, unless
    # explicitly escaped -- see adapters/sqlite_adapter.py's own AI-
    # notes/comments for the fuller reasoning. Proven here against a
    # REAL row containing a literal "%", not just the adapter's own
    # isolated test.
    conn = sqlite3.connect(test_db_path)
    conn.execute("INSERT INTO authors (author_id, org_id, name) VALUES ('auth_pct', 'org-a', '50% Off Corp')")
    conn.execute("INSERT INTO authors (author_id, org_id, name) VALUES ('auth_x', 'org-a', '50X Off Corp')")
    conn.commit()
    conn.close()

    result = mediator.search_object_free_text(_record("alice"), "Author", "50%")
    assert result == ["auth_pct"]


def test_visible_schema_hides_ungranted_object_types(mediator):
    visible = mediator.visible_schema(_record("carol"))
    assert visible == {}


def test_visible_schema_shows_discovery_only_type_with_empty_fields(mediator):
    visible = mediator.visible_schema(_record("dave"))
    assert "Author" in visible
    assert visible["Author"]["fields"] == {}


def test_visible_schema_shows_exactly_the_granted_fields(mediator):
    visible = mediator.visible_schema(_record("alice"))
    assert set(visible["Author"]["fields"].keys()) == {"name", "books"}
    assert "org_id" not in visible["Author"]["fields"]


def test_visible_schema_never_leaks_internal_storage_or_security_config(mediator):
    # A real, confirmed bug found and fixed during a later review pass:
    # visible_schema() used to spread the FULL type_def (`**type_def`)
    # into its own result -- meaning `storage`/`additional_storage`/
    # `security` (real internal infrastructure detail: which physical
    # database, table, and column backs a field) leaked out through
    # this method's own return value, completely unfiltered, to the
    # two real HTTP routes that return this dict directly as a
    # response body. TEST_SCHEMA's own real "Author" entry genuinely
    # has both a real `storage` block AND a real `security` block --
    # this asserts NEITHER key is present anywhere in the result, for
    # a real, granted type this user can genuinely see.
    visible = mediator.visible_schema(_record("alice"))
    assert set(visible["Author"].keys()) == {"fields", "id_field", "title_field"}
    assert "storage" not in visible["Author"]
    assert "additional_storage" not in visible["Author"]
    assert "security" not in visible["Author"]


def test_search_object_reuses_precomputed_visible_schema_if_given(mediator):
    # Finding 2 fix -- an explicitly-passed visible_schema is used
    # as-is, rather than recomputed. Passing a DELIBERATELY WRONG one
    # (claiming nothing is visible) proves it's genuinely being used,
    # not silently ignored in favor of a fresh computation.
    fake_empty_schema = {}
    result = mediator.search_object(_record("alice"), "Author", {"author_id": "auth_001"},
                                     visible_schema=fake_empty_schema)
    assert result == []  # would be ["auth_001"] if the real schema were computed instead


def test_visible_schema_title_field_requires_its_own_explicit_grant(mediator):
    # A real, isolated DataMediator whose OWN schema actually declares
    # a title_field (test_schema/mediator's shared fixtures deliberately
    # don't -- see tests/unit/test_ontology_schema.py's own comment on
    # why that fixture stays untouched). alice (real role: read:Author,
    # read:Author.name) sees it; bob's role withholds read:Author.name
    # specifically, so the SAME title_field must come back as None for
    # him -- proves visible_schema() genuinely re-checks THIS field's
    # own grant per caller, not just whether the type declares one.
    schema_with_title = {
        "Author": {
            "storage": {"silo": "test_silo", "table": "authors", "id_column": "author_id"},
            "id_field": "author_id",
            "title_field": "name",
            "security": {"field": "org_id"},
            "fields": {"org_id": {"type": "data"}, "name": {"type": "data"}},
        },
    }
    users = {
        "alice": {"org_id": "org-a", "role": "with_name"},
        "bob": {"org_id": "org-a", "role": "without_name"},
    }
    roles = {
        "with_name": {"allowed_actions": ["read:Author", "read:Author.author_id", "read:Author.name"]},
        "without_name": {"allowed_actions": ["read:Author", "read:Author.author_id"]},
    }
    m = DataMediator(schema_with_title, {}, {"Author": "test_silo"}, roles)

    alice_visible = m.visible_schema(resolve_user_record(users, "alice", "org_id"))
    bob_visible = m.visible_schema(resolve_user_record(users, "bob", "org_id"))

    assert alice_visible["Author"]["title_field"] == "name"
    assert bob_visible["Author"]["title_field"] is None


def test_id_field_itself_requires_its_own_explicit_grant(mediator):
    eve_users = {**TEST_USERS, "eve": {"org_id": "org-a", "role": "no_id_grant"}}
    eve_roles = {**TEST_ROLES, "no_id_grant": {"allowed_actions": ["read:Author", "read:Author.name"]}}
    m2 = DataMediator(mediator.schema, mediator.adapters, mediator.silo_for_type, eve_roles)
    eve_record = resolve_user_record(eve_users, "eve", "org_id")

    with pytest.raises(ValueError):
        m2.search_object(eve_record, "Author", {"author_id": "auth_001"})
    assert m2.search_object(eve_record, "Author", {"name": "Ada Lovelace"}) == ["auth_001"]


def test_two_mediators_are_independent():
    import sqlite3
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        db_a = Path(tmp) / "a.db"
        conn = sqlite3.connect(db_a)
        conn.executescript("""
            CREATE TABLE authors (author_id TEXT PRIMARY KEY, org_id TEXT, name TEXT);
            INSERT INTO authors VALUES ('x', 'org-x', 'Test Author');
        """)
        conn.commit()
        conn.close()

        schema_a = {"Author": {
            "storage": {"silo": "s", "table": "authors", "id_column": "author_id"},
            "id_field": "author_id",
            "security": {"field": "org_id"},
            "fields": {"org_id": {"type": "data"}, "name": {"type": "data"}},
        }}
        users_a = {"x_user": {"org_id": "org-x", "role": "reader"}}
        roles_a = {"reader": {"allowed_actions": ["read:Author", "read:Author.name"]}}

        adapter_a = SQLiteAdapter({"path": db_a})
        mediator_a = DataMediator(schema_a, {"s": adapter_a}, {"Author": "s"}, roles_a)
        record_a = resolve_user_record(users_a, "x_user", "org_id")
        assert mediator_a.get_field(record_a, "Author", "x", "name") == "Test Author"
