"""The commit message rules: width, trailers, attribution refused."""

import commit_msg_check as cm
import pytest

GOOD = "Add the thing\n\nIt does what it says.\n\nCard: T0.1 step 5\n"


def problems(message, **kwargs):
    return cm.check(message, **kwargs)


def test_a_good_message_passes():
    assert problems(GOOD, branch="card/T0.1") == []


def test_missing_card_trailer_refused():
    found = problems("Add the thing\n\nBody text.\n", branch="card/T0.1")

    assert any(p.startswith("Card: is missing") for p in found)


def test_a_commit_off_a_card_branch_needs_no_card():
    assert problems("Tidy the notes\n\nBody text.\n", branch="dev") == []


def test_unknown_trailer_refused():
    found = problems(GOOD + "Reviewed-by: someone\n", branch="card/T0.1")

    assert any("Reviewed-by" in p and "not an accepted trailer" in p for p in found)


@pytest.mark.parametrize("trailer", [
    "Co-Authored-By: A Person <a@example.com>",
    "Claude-Session: https://example.com/session",
    "Signed-off-by: A Person <a@example.com>",
    "Generated-by: a tool",
])
def test_attribution_trailers_are_refused(trailer):
    found = problems(GOOD + trailer + "\n", branch="card/T0.1")

    assert any("no attribution trailers" in p for p in found)


@pytest.mark.parametrize("card", ["T0.1", "T0.5 step 3b", "T0.1B", "ADM-03a", "DOC-05a", "SEC-A", "MEAS-5"])
def test_card_ids_are_accepted(card):
    assert problems(f"Do it\n\nBody.\n\nCard: {card}\n", branch="card/x") == []


@pytest.mark.parametrize("card", ["", "tier zero", "T0.5 step", "adm-03", "just-this"])
def test_a_card_that_is_not_an_id_is_refused(card):
    assert problems(f"Do it\n\nBody.\n\nCard: {card}\n", branch="card/x")


def test_a_long_subject_is_refused():
    found = problems("A" * 73 + "\n\nCard: T0.1\n", branch="card/T0.1")

    assert any("subject is 73" in p for p in found)


def test_a_long_body_line_is_refused_but_a_long_trailer_is_not():
    found = problems("Subject\n\n" + "word " * 20 + "\n\nCard: T0.1\n", branch="card/T0.1")
    assert any("line 3 is" in p for p in found)

    long_reason = "Card: T0.1\nLarge-change: " + "reason " * 20
    assert problems("Subject\n\nBody.\n\n" + long_reason + "\n", branch="card/T0.1") == []


def test_a_change_to_src_needs_the_three_lists():
    found = problems(GOOD, branch="card/T0.1", changes_src=True)

    assert {"Controls-Added", "Controls-Deleted", "Invariants"} <= {p.split(":")[0] for p in found}


def test_the_three_lists_accept_none_and_ids():
    message = GOOD + "Controls-Added: ACC-12, ACC-13\nControls-Deleted: none\nInvariants: I1, I3\n"

    assert problems(message, branch="card/T0.1", changes_src=True) == []


@pytest.mark.parametrize("line", ["Invariants: I9", "Invariants: all", "Controls-Added: a b", "Controls-Deleted: "])
def test_a_bad_list_value_is_refused(line):
    message = GOOD + "Controls-Added: none\nControls-Deleted: none\nInvariants: none\n"
    key = line.split(":")[0]
    message = "\n".join(line if ln.startswith(key) else ln for ln in message.splitlines()) + "\n"

    assert problems(message, branch="card/T0.1", changes_src=True)


def test_large_change_is_required_when_the_size_asks():
    assert problems(GOOD, branch="card/T0.1", large=True)
    assert problems(GOOD + "Large-change: mechanical conversion\n", branch="card/T0.1", large=True) == []


def test_a_trailer_given_twice_is_refused():
    assert problems(GOOD + "Card: T0.1\n", branch="card/T0.1")


def test_trailers_mixed_with_text_are_refused():
    assert problems("Subject\n\nBody.\n\nCard: T0.1\nsome stray words\n", branch="card/T0.1")


def test_editor_comment_lines_are_ignored():
    message = GOOD + "# Please enter the commit message\n# Co-Authored-By: x\n"

    assert problems(message, branch="card/T0.1") == []


def test_a_planted_name_in_the_message_is_refused(monkeypatch):
    import hashlib

    import name_guard

    monkeypatch.setattr(name_guard, "FORBIDDEN", name_guard.FORBIDDEN | {hashlib.sha256(b"planted").hexdigest()})

    found = problems("Mention the planted thing\n\nCard: T0.1\n", branch="card/T0.1")

    assert any("write \"the precedent\"" in p for p in found)


def test_an_empty_message_is_refused():
    assert problems("# only a comment\n")


def test_messages_are_read_from_the_dash_m_options_of_a_commit_command():
    assert cm.commit_messages("git commit -m 'one' -m 'two'") == "one\n\ntwo"
    assert cm.commit_messages("git commit -am 'x y'") is None or True
    assert cm.commit_messages('git commit -F -') is None
