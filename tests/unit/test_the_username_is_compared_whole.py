"""
A password is refused for BEING the username, not for containing it.

SEC-22, raised by the security agent and inherited when it was
destroyed: `password_problem` refused any password holding the
username as a substring. Reproduced: for the user `alice`, the
twenty-eight character passphrase `my-alice-in-wonderland-quote` was
rejected.

NIST SP 800-63B SAYS THE OPPOSITE, in normative language:

    When processing a request to establish or change a password,
    verifiers SHALL compare the prospective secret against a blocklist
    that contains known commonly used, expected, or compromised
    passwords. THE ENTIRE PASSWORD SHALL BE SUBJECT TO COMPARISON, NOT
    SUBSTRINGS OR WORDS THAT MIGHT BE CONTAINED THEREIN.

The username belongs on that blocklist -- the standard's own examples
are "the name of the service, the username, and derivatives thereof"
-- but as a value compared WHOLE, not a substring to scan for.

AND THE OVER-STRICT VERSION MAKES PASSWORDS WORSE, by the same
document's reasoning: a blocklist that is too broad "is likely to
frustrate users that attempt to choose a memorable password", and a
frustrated user picks something shorter.

DERIVATIVES ARE STILL REFUSED, which is what "and derivatives thereof"
asks for: strip everything that is not a letter, and if what remains
is the username, the password is the username with padding.
"""

import pytest

from core.auth.password_policy import password_problem


class TestWhatIsStillRefused:
    @pytest.mark.parametrize("password,note", [
        ("alice123456789012345", "digits appended"),
        ("alice!!!!!!!!!!!!!!!!", "symbols appended"),
        ("ALICE2026!!!!!!!!!!!", "cased, with a year"),
        ("...alice............", "padded both sides"),
    ])
    def test_the_username_with_characters_added(self, password, note):
        """Long enough to clear every other rule, so this one decides."""
        problem = password_problem(password, "alice")

        assert problem is not None, note
        assert "username" in problem

    def test_the_bare_username(self):
        assert password_problem("alice", "alice") is not None


class TestWhatIsNoLongerRefused:
    def test_a_passphrase_that_merely_contains_it(self):
        """THE CASE SEC-22 NAMED. Twenty-eight characters, rejected for
        holding five of them in the MIDDLE -- which is the distinction:
        a password that BEGINS with the username is still refused."""
        assert password_problem("my-alice-in-wonderland-quote", "alice") is None

    @pytest.mark.parametrize("password", [
        "malice-in-the-palace-tonight",
        "chalice-of-the-wandering-sea",
        "specialised-alice-blue-paint",
    ])
    def test_words_that_happen_to_contain_the_username(self, password):
        """`malice` and `chalice` contain `alice`. Under a substring
        rule a user called alice could not use either, and neither is
        guessable from knowing her username."""
        assert password_problem(password, "alice") is None

    def test_an_unrelated_passphrase_is_still_fine(self):
        assert password_problem("the-quick-brown-fox-jumped", "alice") is None


class TestTheComparisonItself:
    def test_it_does_not_scan_for_a_substring(self):
        """The regression test for the rule's SHAPE. A containment
        check would reappear as `username in lowered`, which is what
        SEC-22 found and what the standard forbids."""
        import inspect

        from core.auth.password_policy import _is_the_username_or_a_derivative

        source = inspect.getsource(_is_the_username_or_a_derivative)
        code = source[source.index('"""', source.index('"""') + 3):]

        assert "username in lowered" not in code
        assert "startswith" in code

    def test_a_different_username_is_not_matched(self):
        """Stripping non-letters must not make every short password
        look like every short username."""
        assert password_problem("bob123456789012345", "alice") is None


class TestAPasswordBeginningWithTheUsername:
    """The half I nearly removed.

    Two tests in this project already asserted that
    `alice-has-a-long-secret` and `cyrus-and-a-long-tail` are refused.
    My first attempt at SEC-22 loosened the rule to "equals or padded"
    and broke both, and I was about to edit them before reading why
    they were there.

    They are right: a password BEGINNING with the username is what
    somebody types when asked to make a password out of their name,
    and the standard's own list says "the username, AND DERIVATIVES
    THEREOF". Containing it in the middle is not derivation -- it is
    English.
    """

    def test_the_existing_unit_case_still_refuses(self):
        assert password_problem("alice-has-a-long-secret", "alice") is not None

    def test_the_existing_integration_case_still_refuses(self):
        assert password_problem("cyrus-and-a-long-tail", "cyrus") is not None

    def test_punctuation_woven_through_it_still_refuses(self):
        assert password_problem("a.l.i.c.e!!!!!!!!!!!", "alice") is not None

