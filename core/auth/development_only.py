"""Refusing to create a known-password account outside development.

WHY THIS IS SHARED RATHER THAN COPIED A THIRD TIME (001's F-30).
`create_debug_user.py` and `create_e2e_users.py` each carried their own
copy of this check. `create_colleague_user.py` carried none -- and it
creates `debug` / `a` itself, with every grant the deployment defines,
so the guard on `create_debug_user.py` could be walked around by
running the other script. REPRODUCED before fixing:

    $ python -m scripts.create_debug_user
    REFUSING. This creates 'debug' with password 'a' ...
    $ python -m scripts.create_colleague_user
      created 'debug' / 'a'
      created 'colleague' / 'a'

That is what two copies of a security check drifting looks like: the
guarded path is the one nobody takes. The property at risk -- "a known
password never lands outside development" -- is exactly the kind
PRINCIPLES.md 6 says to extract, because copies quietly stop agreeing.

ONE CALLER TODAY, DELIBERATELY, AND THE REASON IS NOT TASTE.
Converting create_debug_user.py and create_e2e_users.py to this module
is the obvious completion, and it breaks
tests/unit/test_template_is_a_valid_deployment.py, which asserts the
literal strings "--yes-this-is-development" and "REFUSING" appear in
create_debug_user.py's SOURCE. Moving the guard moves the strings. That
file is backend-owned, and 000COORDINATION.md says a failing test
outside your area is reported rather than fixed into passing -- so the
conversion is filed in REQUESTS_security.md and scheduled, not smuggled
into a security fix. See that request for why the test should be
replaced rather than relocated: AGENTS.md already records that a test
asserting a WORD appears in source is satisfied by deleting the
behaviour and leaving the word in a comment.

The durable protection does not depend on the conversion happening.
tests/unit/test_development_guard.py CALLS each script's main() and
asserts it refuses -- so a fourth script, or a regression in either
unconverted copy, fails a test whether or not the code is shared.

WHY A FLAG AND NOT AN ENVIRONMENT VARIABLE. An environment variable
set once in a shell profile stops being a decision; a flag is retyped
every run. The refusal names the exact command to re-run, so the cost
of the guard is one paste, not one lookup.

NOT EVERY ACCOUNT-CREATING SCRIPT NEEDS THIS. `bootstrap_root.py`
generates its password with `secrets.token_urlsafe(24)` and prints it
once -- there is no known password to leak, so guarding it would be
ceremony. The tripwire in tests/unit/test_development_guard.py encodes
exactly that distinction rather than "every script that calls
create_user".
"""

import sys

# The one spelling, so three scripts cannot drift to three spellings.
DEVELOPMENT_FLAG = "--yes-this-is-development"


def refuse_unless_development(command: str, creates: str,
                              argv: list[str] | None = None) -> bool:
    """True when the caller must stop; prints the refusal to stderr.

    `command` is the module path as a person would re-run it
    (``scripts.create_debug_user``). `creates` says what would be made,
    in the caller's own words -- the wording differs per script on
    purpose, because "every grant the deployment defines" and "the two
    users the browser tests log in as" are different warnings and a
    generic one would say less than either.

    Returns a bool rather than raising or calling sys.exit() so the
    caller keeps its own `return 1` shape, and so a test can assert the
    decision without catching SystemExit.
    """
    if DEVELOPMENT_FLAG in (sys.argv if argv is None else argv):
        return False

    print(
        f"REFUSING. This creates {creates}.\n"
        f"That is a back door, not an account. If this really is a "
        f"development machine, re-run with:\n\n"
        f"    python -m {command} {DEVELOPMENT_FLAG}\n",
        file=sys.stderr,
    )
    return True
