"""
All three development-only scripts use ONE guard
(`core/auth/development_only.py`).

HOW F-30 HAPPENED. Three scripts need this refusal; two carried inline
copies and one had none at all. A guard that is copied is a guard that
can be forgotten, and it was.

THE CONVERSION WAS BLOCKED BY A TEST THAT WAS NOT A TEST.
`test_template_is_a_valid_deployment.py` asserted that the literal
strings "--yes-this-is-development" and "REFUSING" appeared in
`create_debug_user.py`'s SOURCE. Sharing the guard moves those strings
out of that file, so doing the right thing would have failed the
suite. AGENTS.md already records the shape: "a test asserting a WORD
appears in source is not a test", because it is satisfied by deleting
the behaviour and leaving the word in a comment.

That test became behavioural in patch 448, which unblocked this -- and
nobody noticed, because the module that was waiting on it recorded the
blocker in a comment rather than anywhere a person would look. It was
found by consuming `000COORDINATION.md`, which the comment also cited.

THE WORDING STAYS PER-SCRIPT, deliberately. `refuse_unless_development`
takes what the script would create in the caller's own words, because
"every grant the deployment defines" and "the two users the browser
tests log in as" are different warnings and a generic one would say
less than either.
"""

from pathlib import Path

import pytest

SCRIPTS = ["scripts/create_debug_user.py", "scripts/create_e2e_users.py"]


class TestOneGuardNotThree:
    @pytest.mark.parametrize("name", SCRIPTS)
    def test_the_script_calls_the_shared_guard(self, name):
        source = Path(name).read_text()

        assert "refuse_unless_development(" in source

    @pytest.mark.parametrize("name", SCRIPTS)
    def test_it_keeps_no_inline_copy(self, name):
        """THE REGRESSION TEST. Both carried their own `if
        "--yes-this-is-development" not in sys.argv` and their own
        printed refusal."""
        source = Path(name).read_text()
        code = "\n".join(line for line in source.splitlines()
                          if not line.lstrip().startswith("#"))

        assert '"--yes-this-is-development" not in sys.argv' not in code

    @pytest.mark.parametrize("name", SCRIPTS)
    def test_it_still_returns_1_rather_than_exiting(self, name):
        """The guard returns a bool so each caller keeps its own
        `return 1` shape -- a script that calls sys.exit() inside a
        library cannot be tested without catching SystemExit."""
        source = Path(name).read_text()
        call = source[source.index("refuse_unless_development("):]

        assert "return 1" in call[:400]


class TestTheWordingStaysPerScript:
    def test_the_two_scripts_say_different_things(self):
        """A generic warning would say less than either. The debug user
        gets every grant; the e2e users have known passwords."""
        debug = Path("scripts/create_debug_user.py").read_text()
        e2e = Path("scripts/create_e2e_users.py").read_text()

        assert "every grant the " in debug
        assert "browser " in e2e

    def test_each_names_its_own_command(self):
        """The refusal tells the reader how to re-run THIS script."""
        debug = Path("scripts/create_debug_user.py").read_text()
        e2e = Path("scripts/create_e2e_users.py").read_text()

        assert "scripts.create_debug_user" in debug
        assert "scripts.create_e2e_users" in e2e


class TestTheGuardItself:
    def test_it_returns_true_when_the_flag_is_absent(self):
        from core.auth.development_only import refuse_unless_development

        assert refuse_unless_development("m", "x", argv=["prog"]) is True

    def test_it_returns_false_when_the_flag_is_present(self):
        from core.auth.development_only import refuse_unless_development

        assert refuse_unless_development(
            "m", "x", argv=["prog", "--yes-this-is-development"]) is False
