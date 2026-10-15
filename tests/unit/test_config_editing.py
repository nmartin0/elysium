"""Editing config.yaml: only the lines asked for, never a comment lost.

Run against the SHIPPED deployment/etc/config.yaml as well as small
files, because the shipped file is mostly comments -- the case that
broke editing through ruamel's data model.
"""

from pathlib import Path

import pytest
import yaml

from core.config_editing import (
    EDITABLE,
    REMOVED_MARK,
    ConfigEditError,
    apply_changes,
    current_settings,
    diff,
)

SHIPPED = Path(__file__).resolve().parents[2] / "deployment" / "etc" / "config.yaml"

SMALL = """\
# The agent's limits.
agent:
  max_hops: 8  # enough for a two-step lookup
  # Repeats before stopping.
  max_consecutive_duplicates: 2
  max_consecutive_invalid_steps: 2

# Tools the agent may call.
tools:
  enabled:
    - calculator
"""


def _comments(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip().startswith("#")]


class TestOnlyTheLinesAskedFor:
    def test_a_value_change_is_one_line_and_keeps_its_inline_comment(self):
        after = apply_changes(SMALL, {"agent.max_hops": 12})
        changed = [line for line in diff(SMALL, after) if line[:1] in "+-" and line[:3] not in ("+++", "---")]
        assert changed == ["-  max_hops: 8  # enough for a two-step lookup",
                           "+  max_hops: 12  # enough for a two-step lookup"]

    def test_a_new_setting_goes_inside_its_block_not_under_the_next_ones_comment(self):
        after = apply_changes(SMALL, {"agent.filter_operators": True})
        lines = after.splitlines()
        assert lines.index("  filter_operators: true") == lines.index("  max_consecutive_invalid_steps: 2") + 1
        assert yaml.safe_load(after)["tools"] == {"enabled": ["calculator"]}

    def test_a_new_top_level_setting_goes_at_the_end(self):
        after = apply_changes(SMALL, {"on_type_mismatch": "quarantine"})
        assert after.endswith("on_type_mismatch: quarantine\n")

    def test_removing_comments_the_line_out_and_keeps_every_comment_around_it(self):
        after = apply_changes(SMALL, {"agent.max_consecutive_duplicates": None})
        assert "max_consecutive_duplicates" not in yaml.safe_load(after)["agent"]
        assert f"  # max_consecutive_duplicates: 2  {REMOVED_MARK}" in after
        assert set(_comments(SMALL)) <= set(_comments(after))

    def test_putting_it_back_restores_that_line_rather_than_adding_a_second(self):
        removed = apply_changes(SMALL, {"agent.max_consecutive_duplicates": None})
        restored = apply_changes(removed, {"agent.max_consecutive_duplicates": 3})
        assert restored == SMALL.replace("max_consecutive_duplicates: 2", "max_consecutive_duplicates: 3")


class TestTheShippedFile:
    """The file that broke the data-model approach: removing one key
    there deleted three comment blocks."""

    def test_every_comment_survives_every_kind_of_edit(self):
        text = SHIPPED.read_text()
        after = apply_changes(text, {"agent.max_hops": 9, "agent.filter_operators": True,
                                     "on_type_mismatch": None, "ingest_undeclared_columns": True})
        assert set(_comments(text)) <= set(_comments(after))

    def test_the_diff_is_the_change_and_nothing_else(self):
        text = SHIPPED.read_text()
        after = apply_changes(text, {"agent.max_hops": 9})
        removed = [line for line in diff(text, after) if line.startswith("-") and not line.startswith("---")]
        assert removed == ["-  max_hops: 8"]


class TestWhatItRefuses:
    def test_a_key_not_on_the_list_whether_or_not_it_exists(self):
        """llm.connection is not editable, and neither is a key that is not
        there -- the same answer, so this does not say what else exists."""
        for key in ("llm.connection", "llm.connection.base_url", "no.such.key"):
            with pytest.raises(ConfigEditError, match="cannot be edited here"):
                apply_changes(SMALL, {key: 1})

    @pytest.mark.parametrize(("key", "value"), [
        ("agent.max_hops", 0), ("agent.max_hops", "8"), ("agent.max_hops", True),
        ("agent.filter_operators", "yes"), ("on_type_mismatch", "ignore"),
    ])
    def test_a_value_of_the_wrong_kind(self, key, value):
        with pytest.raises(ConfigEditError):
            apply_changes(SMALL, {key: value})

    def test_nothing_to_change(self):
        with pytest.raises(ConfigEditError):
            apply_changes(SMALL, {})

    def test_no_editable_setting_can_hold_a_secret(self):
        """Structural, not promised: every setting is a number, a switch or
        a fixed choice, so no request can write free text into the file."""
        assert {setting.kind for setting in EDITABLE} <= {"int", "bool", "choice"}
        assert not any("connection" in setting.key or "key" in setting.key.split(".")[-1]
                       for setting in EDITABLE)


def test_the_form_sees_present_and_absent_apart():
    settings = {setting["key"]: setting for setting in current_settings(SMALL)}
    assert settings["agent.max_hops"]["present"] is True
    assert settings["agent.max_hops"]["value"] == 8
    assert settings["on_type_mismatch"]["present"] is False
    assert settings["on_type_mismatch"]["when_absent"]
