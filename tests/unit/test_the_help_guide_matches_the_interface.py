"""The help assistant's screen guide names controls by their on-screen
labels, so it is the one part an interface change can make WRONG
without anything else breaking. This keeps the two together."""

import re
from pathlib import Path

from api.apps import visible_apps_for
from core.agent.help_assistant import SCREEN_GUIDE, SHELL_GUIDE, SHELL_GUIDE_WITH_BROWSE, build_context
from core.intermediate_layer.auth import UserRecord
from core.modules import load_modules

# The packages AND the page's own screens (ui/src): the System pages
# live there, and the Inbox did until it became a package (step 3).
UI_SOURCE = "\n".join(path.read_text() for root in ("ui/packages", "ui/src")
                      for path in Path(root).rglob("*.tsx") if ".test." not in path.name)


def test_every_quoted_label_is_on_screen_somewhere():
    guides = [*SCREEN_GUIDE.values(), SHELL_GUIDE, SHELL_GUIDE_WITH_BROWSE]
    labels = {label for text in guides for label in re.findall(r"'([^']+)'", text)}

    assert labels, "the probe found no labels at all"
    assert sorted(label for label in labels if label not in UI_SOURCE) == []


def test_every_screen_in_the_rail_has_a_guide_entry():
    """A new screen with no entry is one the assistant cannot explain."""
    # Every shipped module, as somebody offered all of them sees the rail.
    everyone = UserRecord(user_id="all", security_value=None, role_name="all")
    roles = {"all": {"allowed_actions": frozenset({"manage:users"})}}
    rail = visible_apps_for(everyone, roles, load_modules(Path("/nonexistent")))
    assert {app["name"] for app in rail} == set(SCREEN_GUIDE)


def test_a_schema_too_large_is_summarised_by_type_not_cut_mid_field():
    schema = {f"Type{n}": {"fields": {f"field_{i}": {"type": "data"} for i in range(200)}}
              for n in range(20)}

    context = build_context([{"name": "Browse"}], schema, ["read:Type0"], None)

    assert "fields omitted, too many to list" in context
    assert "field_" not in context
    assert "Type19" in context


def test_the_palette_is_described_by_what_this_user_has():
    """The palette offers types, views and actions only to someone with
    Browse; the guide must not tell anyone else to use them."""
    with_browse = build_context([{"name": "Browse"}], {}, [], None)
    without = build_context([{"name": "Query"}], {}, [], None)

    assert "Ctrl-K" in with_browse and "Ctrl-K" in without
    assert "saved view" in with_browse
    assert "saved view" not in without
