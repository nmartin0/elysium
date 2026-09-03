"""
Tests for api/apps.py's visible_apps_for() -- the registry backing
GET /me/visible-apps.
"""

from api.apps import visible_apps_for
from core.intermediate_layer.auth import resolve_user_record

TEST_USERS = {
    "alice": {"role": "admin"},
    "bob": {"role": "plain_user"},
    "carol": {},  # deliberately no role
}

TEST_ROLES = {
    "admin": {"allowed_actions": ["manage:users"]},
    "plain_user": {"allowed_actions": []},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "security_attribute_unused_here")


def test_apps_with_no_gating_permission_are_always_visible():
    # bob holds no grants at all -- Query/Browse (gating_permission is
    # None) must still be present; only a real, missing grant should
    # ever hide an entry.
    names = {app["name"] for app in visible_apps_for(_record("bob"), TEST_ROLES)}
    assert {"Query", "Browse"}.issubset(names)


def test_gated_app_visible_with_the_real_grant():
    names = {app["name"] for app in visible_apps_for(_record("alice"), TEST_ROLES)}
    assert "Admin" in names


def test_gated_app_hidden_without_the_grant():
    names = {app["name"] for app in visible_apps_for(_record("bob"), TEST_ROLES)}
    assert "Admin" not in names


def test_no_role_at_all_still_sees_the_ungated_apps():
    names = {app["name"] for app in visible_apps_for(_record("carol"), TEST_ROLES)}
    assert {"Query", "Browse"}.issubset(names)
    assert "Admin" not in names


def test_every_entry_has_a_real_path():
    # The one thing added beyond "name + gating_permission" -- without
    # it the frontend has nothing to link to. Confirms this wasn't
    # silently dropped for any entry.
    for app in visible_apps_for(_record("alice"), TEST_ROLES):
        assert app["path"].startswith("/")
