"""The help assistant's screen guide names controls by their on-screen
labels, so it is the one part an interface change can make WRONG
without anything else breaking. This keeps the two together."""

import re
from pathlib import Path

from api.apps import VISIBLE_APPS
from core.agent.help_assistant import SCREEN_GUIDE, build_context

UI_SOURCE = "\n".join(path.read_text() for path in Path("ui/packages").rglob("*.tsx")
                      if ".test." not in path.name)


def test_every_quoted_label_is_on_screen_somewhere():
    labels = {label for text in SCREEN_GUIDE.values() for label in re.findall(r"'([^']+)'", text)}

    assert labels, "the probe found no labels at all"
    assert sorted(label for label in labels if label not in UI_SOURCE) == []


def test_every_screen_in_the_rail_has_a_guide_entry():
    """A new screen with no entry is one the assistant cannot explain."""
    assert {app["name"] for app in VISIBLE_APPS} == set(SCREEN_GUIDE)


def test_a_schema_too_large_is_summarised_by_type_not_cut_mid_field():
    schema = {f"Type{n}": {"fields": {f"field_{i}": {"type": "data"} for i in range(200)}}
              for n in range(20)}

    context = build_context([{"name": "Browse"}], schema, ["read:Type0"], None)

    assert "fields omitted, too many to list" in context
    assert "field_" not in context
    assert "Type19" in context
