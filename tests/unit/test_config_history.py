"""
What each configuration generation contained.

A generation records WHICH load it was, WHEN, and THAT the files
differed. Until this, it did not record WHAT THEY SAID -- so after a
reload, "what did generation 7 contain", "what changed", and "put it
back" had no answer.

NOT SOLVED BY GIT, and assuming otherwise was a real error in the
reasoning behind HOT_RELOAD_PLAN.md. This project's configuration
happens to live in a repository; a DEPLOYED Elysium has /etc/elysium on
an operator's machine and no relationship to any repository.
"""

import pytest

from core.config_history import ConfigHistory


@pytest.fixture
def history(tmp_path):
    return ConfigHistory(tmp_path / "config_history.db")


FILES_V1 = {"config.yaml": "model: a\n", "policy.yaml": "roles: {}\n"}
FILES_V2 = {"config.yaml": "model: b\n", "policy.yaml": "roles: {}\n"}


def test_a_generation_can_be_read_back(history):
    history.record(7, "2026-09-11T00:00:00+00:00", "abc", FILES_V1)

    recorded = history.get(7)

    assert recorded is not None
    assert recorded.files == FILES_V1
    assert recorded.source_digest == "abc"


def test_an_unrecorded_generation_is_none_not_an_error(history):
    assert history.get(99) is None


def test_the_diff_names_only_the_files_that_changed(history):
    history.record(1, "t", "d1", FILES_V1)
    history.record(2, "t", "d2", FILES_V2)

    changed = history.diff(1, 2)

    assert set(changed) == {"config.yaml"}
    assert changed["config.yaml"] == ("model: a\n", "model: b\n")


def test_a_file_appearing_or_disappearing_is_a_change(history):
    # Present on one side and absent on the other shows with "" for the
    # missing side rather than being skipped. A configuration file
    # APPEARING is a change; one DISAPPEARING is a bigger one.
    history.record(1, "t", "d1", {"config.yaml": "x\n"})
    history.record(2, "t", "d2", {"config.yaml": "x\n", "policy.yaml": "y\n"})

    changed = history.diff(1, 2)

    assert changed == {"policy.yaml": ("", "y\n")}


def test_diffing_an_unknown_generation_raises_rather_than_returning_empty(history):
    # "No differences" and "I have never heard of generation 4" are
    # different answers, and returning the first for the second is how
    # an operator concludes nothing changed.
    history.record(1, "t", "d1", FILES_V1)

    with pytest.raises(ValueError, match="4"):
        history.diff(1, 4)


def test_recording_the_same_generation_twice_is_ignored(history):
    # A generation number is assigned once per load and never reused,
    # so a repeat can only be the same load recorded twice -- a retry.
    # Replacing would rewrite history on a retry; raising would turn a
    # harmless retry into a failed startup.
    history.record(1, "t", "d1", FILES_V1)
    history.record(1, "t", "d1", FILES_V2)

    assert history.get(1).files == FILES_V1


def test_generations_list_most_recent_first(history):
    for n in (1, 2, 3):
        history.record(n, "t", f"d{n}", FILES_V1)

    assert [r.generation for r in history.list_generations()] == [3, 2, 1]


def test_the_listing_is_bounded(history):
    # An operator answering "what happened recently" does not want
    # thousands of rows, and a deployment reloaded on a timer will have
    # them.
    for n in range(1, 11):
        history.record(n, "t", f"d{n}", FILES_V1)

    assert len(history.list_generations(limit=3)) == 3


def test_raw_text_is_preserved_not_reparsed(history):
    # Raw text rather than parsed structures, for the same reason
    # source_digest is over raw bytes: a reparsed dict loses comments,
    # ordering and anything YAML normalised away -- all of which an
    # operator comparing two generations wants to see.
    commented = {"config.yaml": "# why this model\nmodel: a   # and why\n"}
    history.record(1, "t", "d1", commented)

    assert history.get(1).files == commented


def test_recording_never_raises_into_the_caller(tmp_path):
    # A history table that cannot be written is a DEGRADED deployment,
    # not a broken one: reads and writes work, and only the ability to
    # answer "what did 7 contain" is lost. The opposite of the audit
    # log's posture, deliberately -- an access that cannot be recorded
    # must not happen, but a configuration whose text cannot be
    # archived has already been loaded and validated.
    from types import SimpleNamespace

    from core.config_history import record_generation

    unwritable = ConfigHistory(tmp_path / "no_such_dir" / "h.db")
    generation = SimpleNamespace(
        generation=1,
        loaded_at=SimpleNamespace(isoformat=lambda: "t"),
        source_digest="d",
        config=SimpleNamespace(source_text={"config.yaml": "x"}),
    )

    record_generation(unwritable, generation)  # must not raise
