"""apply_status: deprecating (and restoring) a type, a field or a link type
by editing the ontology file's lines (the removal design, 28 October).

Each test reads the result with a plain YAML parser, as the loader does, so
what is asserted is what the deployment would mean, not what the text looks
like.
"""

import datetime
from pathlib import Path

import pytest
import yaml

from core.config_editing import ConfigEditError
from core.config_editing import apply_status as edit
from core.ontology.deprecation import validate_deprecation

FILE = Path(__file__).resolve().parents[1] / "integration" / "fixtures" / "ontology_schema.yaml"
TEXT = FILE.read_text()


def apply_status(text, change):
    return edit(text, change, validate_deprecation)


def meaning(text):
    return yaml.safe_load(text)


def field(**given):
    return {"kind": "field", "object_type": "Customer", "field": "email", "status": "deprecated",
            "reason": "Replaced by name.", **given}


def test_a_field_is_deprecated_with_its_reason_and_nothing_else_changes():
    after = meaning(apply_status(TEXT, field(replaced_by="name", remove_after="2027-03-31")))
    before = meaning(TEXT)

    email = after["object_types"]["Customer"]["fields"]["email"]
    assert email["status"] == "deprecated"
    assert email["deprecation"] == {"reason": "Replaced by name.", "replaced_by": "name",
                                    "remove_after": datetime.date(2027, 3, 31)}
    del email["status"], email["deprecation"]
    assert after == before


def test_a_type_and_a_link_type_are_deprecated_the_same_way():
    typed = meaning(apply_status(TEXT, {"kind": "type", "object_type": "Tag", "status": "deprecated",
                                        "reason": "Not used."}))
    linked = meaning(apply_status(TEXT, {"kind": "link", "link": "CustomerTags", "status": "deprecated",
                                         "reason": "Not used."}))

    assert typed["object_types"]["Tag"]["status"] == "deprecated"
    assert linked["link_types"]["CustomerTags"]["deprecation"] == {"reason": "Not used."}


def test_every_comment_in_the_file_survives():
    after = apply_status(TEXT, field())

    comments = [line for line in TEXT.splitlines() if line.strip().startswith("#")]
    assert all(line in after.splitlines() for line in comments)


def test_a_reason_with_commas_braces_and_colons_is_kept_whole():
    reason = "Old, a {draft}: see #3 -- 'quoted'"

    after = meaning(apply_status(TEXT, field(reason=reason)))

    assert after["object_types"]["Customer"]["fields"]["email"]["deprecation"]["reason"] == reason


def test_making_it_active_again_takes_both_lines_out():
    deprecated = apply_status(TEXT, field())

    restored = apply_status(deprecated, {"kind": "field", "object_type": "Customer", "field": "email",
                                         "status": "active"})

    assert meaning(restored) == meaning(TEXT)


def test_deprecating_again_replaces_the_reason():
    once = apply_status(TEXT, field())
    twice = meaning(apply_status(once, field(reason="A better reason.")))

    assert twice["object_types"]["Customer"]["fields"]["email"]["deprecation"]["reason"] == "A better reason."


def test_a_deprecation_after_a_restore_reuses_the_removed_lines():
    cycle = apply_status(apply_status(apply_status(TEXT, field()), {
        "kind": "field", "object_type": "Customer", "field": "email", "status": "active"}), field())

    assert meaning(cycle) == meaning(apply_status(TEXT, field()))


@pytest.mark.parametrize("given, said", [
    ({"reason": ""}, "Say why"),
    ({"reason": "   "}, "Say why"),
    ({"reason": "x" * 301}, "at most 300"),
    ({"replaced_by": "nobody"}, "not a field that exists"),
    ({"replaced_by": "email"}, "replaced by itself"),
    ({"remove_after": "next spring"}, "a date"),
    ({"object_type": "Nobody"}, "no object type"),
    ({"field": "nope"}, "no field"),
    ({"status": "gone"}, "deprecated, or active"),
    ({"kind": "table"}, "one of type, field, link"),
    ({"surprise": 1}, "cannot be set here"),
])
def test_a_refusal_says_why(given, said):
    with pytest.raises(ConfigEditError, match=said):
        apply_status(TEXT, field(**given))


def test_a_replacement_that_is_itself_deprecated_is_refused():
    once = apply_status(TEXT, field(reason="Gone.", replaced_by=None) | {"field": "name"})

    with pytest.raises(ConfigEditError, match="itself deprecated"):
        apply_status(once, field(replaced_by="name"))


def test_a_field_a_link_made_is_not_in_the_file_so_the_link_type_is_the_thing_to_deprecate():
    with pytest.raises(ConfigEditError, match="deprecating the link type"):
        apply_status(TEXT, field(field="transactions"))


def test_an_unknown_link_type_is_refused():
    with pytest.raises(ConfigEditError, match="no link type"):
        apply_status(TEXT, {"kind": "link", "link": "Nope", "status": "deprecated", "reason": "x"})


def test_a_reason_goes_with_deprecating_not_with_restoring():
    with pytest.raises(ConfigEditError, match="goes with deprecating"):
        apply_status(apply_status(TEXT, field()), {"kind": "field", "object_type": "Customer",
                                                   "field": "email", "status": "active", "reason": "x"})


def test_a_flow_style_body_is_refused_rather_than_breaking_the_file():
    flow = "object_types:\n  Customer:\n    fields:\n      id: {type: string}\n"

    with pytest.raises(ConfigEditError, match="one line"):
        apply_status(flow, {"kind": "field", "object_type": "Customer", "field": "id",
                            "status": "deprecated", "reason": "r"})
