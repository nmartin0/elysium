"""
INSTALL.md and pyproject.toml agree about which Python this needs
(the unified roadmap's item 1d).

WHAT THEY SAID. INSTALL.md: "Python 3.10 or later". pyproject.toml:
`requires-python = ">=3.12"`. The roadmap recorded the disagreement
and the reason it mattered -- "the locks were generated on 3.12 and
nothing has ever run on 3.10. Test it (a CI matrix, with locks valid
for both) or say 3.12."

IT IS NOT A MATTER OF OPINION, which is what settles it: TWENTY-SIX
modules import `datetime.UTC`, added in 3.11. On 3.10 the package
cannot be imported at all. The floor was never 3.10 and no test ever
could have passed there.

SO THE ROADMAP'S SECOND OPTION IS THE HONEST ONE. 3.12 is what the
locks are generated on, 3.13 is what this is developed against daily,
and a CI matrix proving 3.10 would be proving something false.

WHY A TEST AND NOT JUST AN EDIT. The two files drifted apart for long
enough that an audit had to notice, and nothing connected them. This
is the cheapest possible connection: if somebody changes one, this
asks them to change the other.
"""

import re
import tomllib
from pathlib import Path

PYPROJECT = tomllib.loads(Path("pyproject.toml").read_text())
INSTALL = Path("INSTALL.md").read_text()


def _declared_floor() -> str:
    """The minimum Python pyproject requires, as `major.minor`."""
    requires = PYPROJECT["project"]["requires-python"]
    match = re.search(r">=\s*(\d+\.\d+)", requires)
    assert match, f"cannot read a floor from {requires!r}"
    return match.group(1)


class TestTheTwoFilesAgree:
    def test_install_names_the_version_pyproject_requires(self):
        """THE REGRESSION TEST. INSTALL.md said 3.10 while pyproject
        said 3.12, and both were read as authoritative."""
        assert f"Python {_declared_floor()}" in INSTALL

    def test_install_does_not_still_say_3_10(self):
        """Named explicitly because it is the wrong value that was
        there, and a reader who sees it will believe it."""
        assert "Python 3.10 or later" not in INSTALL


class TestTheFloorIsReal:
    def test_the_code_needs_at_least_3_11(self):
        """`datetime.UTC` is 3.11 and later. A floor below that is not
        a preference, it is an import error."""
        users = [
            path for path in Path(".").glob("core/**/*.py")
            if "from datetime import" in path.read_text()
            and "UTC" in path.read_text().split("from datetime import")[1][:60]
        ]

        assert users, "if this is empty the reason for the floor has changed"
        assert float(_declared_floor()) >= 3.11

    def test_the_floor_is_not_below_what_is_tested(self):
        """The locks are generated on 3.12 and carry markers computed
        from it, so a floor below that would promise an environment
        nobody has resolved."""
        assert _declared_floor() == "3.12"
