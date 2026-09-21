"""
The password policy -- NIST SP 800-63B Revision 4.

"When a password is the only authenticator, systems must enforce a
minimum length of 15 characters" -- Elysium has no second factor.
No composition rules. A blocklist of "commonly used, expected, or
compromised values", offline: a self-hosted deployment may have no
internet to ask Have I Been Pwned.
"""

import pytest

from core.auth.password_policy import MAX_LENGTH, MIN_LENGTH, password_problem


class TestLength:
    def test_fifteen_is_the_minimum(self):
        assert MIN_LENGTH == 15
        assert password_problem("fourteen-chars", "alice")

    def test_fifteen_is_enough(self):
        assert password_problem("quiet river lamp", "alice") is None

    def test_a_long_passphrase_is_welcome(self):
        """ACCEPT AT LEAST 64 -- passphrases and password managers."""
        assert password_problem("walk " * 13 + "home at last", "alice") is None
        assert MAX_LENGTH >= 64

    def test_but_not_without_limit(self):
        """ARGON2 HASHES WHATEVER IT IS GIVEN; an unbounded password is a
        cheap way to make the server work hard."""
        assert password_problem("x" * (MAX_LENGTH + 1) + "yz", "alice")


class TestNoCompositionRules:
    def test_lower_case_and_spaces_are_fine(self):
        """NO "one uppercase, one symbol" -- that produces Spring2025!."""
        assert password_problem("the long walk home tonight", "alice") is None

    def test_unicode_is_fine(self):
        assert password_problem("the long café walk home", "alice") is None


class TestTheBlocklist:
    def test_a_common_long_password(self):
        assert "too common" in password_problem("passwordpassword", "alice")

    def test_separators_do_not_make_it_uncommon(self):
        """THE MOST FAMOUS PASSWORD THERE IS, which a first version
        accepted because the list held it without spaces."""
        assert password_problem("correct horse battery staple", "alice")
        assert password_problem("Correct-Horse-Battery-Staple", "alice")

    def test_the_username(self):
        assert "username" in password_problem("alice-has-a-long-secret", "alice")

    def test_the_service_name(self):
        assert "elysium" in password_problem("my-elysium-password", "alice")

    def test_a_repeated_pattern(self):
        assert password_problem("abcabcabcabcabcabc", "alice")

    def test_a_simple_sequence(self):
        assert password_problem("abcdefghijklmnop", "alice")

    def test_digit_rollover_is_caught_by_the_list_not_the_sequence(self):
        """"123456789012345" ROLLS 9 TO 0, which is not one step -- the
        sequence check does not claim it; the common list does."""
        assert "too common" in password_problem("123456789012345", "alice")


def test_a_message_never_repeats_the_password():
    secret = "alice-long-secret-value"
    assert secret not in (password_problem(secret, "alice") or "")


@pytest.mark.parametrize("value", [None, 12345])
def test_a_password_must_be_text(value):
    assert password_problem(value, "alice")
