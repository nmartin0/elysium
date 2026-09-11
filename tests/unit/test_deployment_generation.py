"""
Which configuration is this? -- step 1a of HOT_RELOAD_PLAN.md.

Elysium reads its four config files once at startup, and until now
nothing could say WHICH configuration was in force for a given audit
entry or pending write, because there had only ever been one. That
stops being true when configuration can be reloaded while running, and
it is already not quite true: a restart with edited files produces a
second configuration the log cannot distinguish from the first.

Identity only. Nothing reloads yet.
"""

from datetime import UTC, datetime
from pathlib import Path

from core.deployment_loader import CONFIG_FILENAMES, _source_digest, load_deployment

DEPLOYMENT = Path(__file__).resolve().parent.parent.parent / "deployment" / "etc"


def test_the_same_files_produce_the_same_digest(tmp_path):
    # The property the whole mechanism rests on: unchanged files are
    # recognisably unchanged. Without this, every reload would look
    # like a change.
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text(f"# {name}\nkey: value\n")

    assert _source_digest(tmp_path, CONFIG_FILENAMES) == _source_digest(tmp_path, CONFIG_FILENAMES)


def test_changing_any_one_file_changes_the_digest(tmp_path):
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text("key: value\n")
    before = _source_digest(tmp_path, CONFIG_FILENAMES)

    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text("key: CHANGED\n")
        assert _source_digest(tmp_path, CONFIG_FILENAMES) != before, f"{name} went unnoticed"
        (tmp_path / name).write_text("key: value\n")


def test_a_comment_change_changes_the_digest(tmp_path):
    # Over the RAW BYTES, not the parsed structures, deliberately. The
    # question is "are these the same files", not "do they mean the
    # same thing" -- comparing parsed dicts would call a comment change
    # identical, and a key reordering different, both backwards here.
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text("key: value\n")
    before = _source_digest(tmp_path, CONFIG_FILENAMES)
    (tmp_path / CONFIG_FILENAMES[0]).write_text("# a note\nkey: value\n")

    assert _source_digest(tmp_path, CONFIG_FILENAMES) != before


def test_moving_text_between_files_changes_the_digest(tmp_path):
    # Each file's NAME is fed in alongside its content for this reason.
    # Hashing concatenated content alone would call these identical.
    (tmp_path / CONFIG_FILENAMES[0]).write_text("a: 1\nb: 2\n")
    (tmp_path / CONFIG_FILENAMES[1]).write_text("")
    before = _source_digest(tmp_path, CONFIG_FILENAMES)

    (tmp_path / CONFIG_FILENAMES[0]).write_text("a: 1\n")
    (tmp_path / CONFIG_FILENAMES[1]).write_text("b: 2\n")

    assert _source_digest(tmp_path, CONFIG_FILENAMES) != before


def test_a_missing_file_does_not_raise(tmp_path):
    # load_deployment() reports a missing file far better than a hash
    # function could. This must not become a second, worse place that
    # error surfaces.
    _source_digest(tmp_path, CONFIG_FILENAMES)


def test_each_load_gets_its_own_generation_number():
    # Assigned by the loader, never by a caller, so two callers cannot
    # mint the same number.
    first = load_deployment(DEPLOYMENT)
    second = load_deployment(DEPLOYMENT)

    assert second.generation > first.generation


def test_two_loads_of_unchanged_files_share_a_digest_but_not_a_generation():
    # The distinction that matters: the digest says WHAT was read, the
    # generation says WHICH READ it was. A reload of unchanged files is
    # a new generation of the same configuration, and conflating the
    # two would make "did anything change?" unanswerable.
    first = load_deployment(DEPLOYMENT)
    second = load_deployment(DEPLOYMENT)

    assert first.source_digest == second.source_digest
    assert first.generation != second.generation


def test_loaded_at_is_an_aware_utc_instant():
    # Aware, not naive: this timestamp is compared against audit entries
    # across a deployment, and a naive one silently means "whatever the
    # server's local zone was".
    before = datetime.now(UTC)
    config = load_deployment(DEPLOYMENT)

    assert config.loaded_at.tzinfo is not None
    assert before <= config.loaded_at <= datetime.now(UTC)
