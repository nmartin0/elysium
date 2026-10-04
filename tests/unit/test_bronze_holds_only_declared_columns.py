"""
Bronze keeps only declared columns, unless the deployment says
otherwise.

WHAT IT USED TO DO: hold every column the source has, declared or not.
That is deliberate and documented -- keeping everything is what makes
a column declared NEXT YEAR re-derivable from history instead of
starting empty.

THE COST, which is `NEW-5`: an undeclared SSN sits in Parquet with no
field grant and no read path, and nothing says so.

HOW EXPOSED IT ACTUALLY IS, checked rather than asserted. NOT through
Elysium: the mediator reads from the silo a type names in
`storage.silo`, which is silver or gold, and `bronze_` is a RESERVED
prefix no silo may be named with. It is exposed to anyone with access
to the lake's files.

That matters because it changed the answer. The first recommendation
here was "opt out per silo, defaulting to today's behaviour", and the
owner's question -- "so the SSN would indeed still be secure?" -- is
the one that broke it: a deployment that does not know to opt out
keeps the SSN, which is the exact failure `NEW-6` was fixed to avoid
four days earlier.

SO THE DEFAULT IS MINIMISATION, and the precedent is on that side.
Schema-on-read "directly undermines the GDPR principles of data
minimization and purpose limitation", and the consistent advice is to
"control data before it lands", because "doing this at ingestion time
is dramatically easier than remediating sensitive data later across
petabytes".

THE TRADE IS REAL AND THE OWNER MADE IT. Minimisation costs
recoverability: a field declared later starts empty rather than
carrying history. An existing deployment keeps that history, because
an absent key means "written before this existed" and silently
narrowing what it holds would destroy exactly what the old default
was for.
"""

import pytest

from core.deployment_loader import _resolve_undeclared_columns


class TestThePolicy:
    def test_absent_means_the_old_behaviour(self):
        """The upgrade path. An existing deployment keeps its history
        and is warned, rather than quietly stopping."""
        assert _resolve_undeclared_columns({}) is None

    @pytest.mark.parametrize("declared,expected", [
        (True, True), (False, False),
        ("yes", True), ("", False), (1, True), (0, False),
    ])
    def test_a_declared_value_is_taken_as_a_boolean(self, declared, expected):
        assert _resolve_undeclared_columns(
            {"ingest_undeclared_columns": declared}) is expected

    def test_the_three_states_are_distinct(self):
        """None is not False. The whole upgrade path rests on the
        difference between "said no" and "never said"."""
        absent = _resolve_undeclared_columns({})
        said_no = _resolve_undeclared_columns(
            {"ingest_undeclared_columns": False})

        assert absent is None
        assert said_no is False
        assert absent is not said_no


class TestTheShippedDefault:
    def test_the_template_says_false(self):
        """A new deployment must minimise by DEFAULT -- the whole
        point. A key that is only documented protects the deployments
        that already knew to ask."""
        from pathlib import Path

        config = Path("deployment/etc/config.yaml").read_text()

        assert "ingest_undeclared_columns: false" in config

    def test_the_template_explains_the_trade(self):
        """Somebody turning this on deserves to know why they might,
        not just that they can."""
        from pathlib import Path

        config = Path("deployment/etc/config.yaml").read_text()
        i = config.index("ingest_undeclared_columns")
        window = config[max(0, i - 1200):i]

        assert "re-derivable" in window or "NEXT YEAR" in window


class TestItIsActuallyWired:
    """Nine times this codebase has built something and connected it
    to nothing."""

    def test_the_sync_takes_it(self):
        import inspect

        from core.mirror.iceberg_sync import IcebergMirrorSync

        parameters = inspect.signature(IcebergMirrorSync.__init__).parameters

        assert "ingest_undeclared_columns" in parameters

    def test_the_real_sync_script_passes_it(self):
        from pathlib import Path

        source = Path("scripts/run_sync.py").read_text()

        assert ("ingest_undeclared_columns=config.ingest_undeclared_columns"
                in source)

    def test_the_column_list_is_actually_narrowed(self):
        from pathlib import Path

        source = Path("core/mirror/iceberg_sync.py").read_text()
        i = source.index("undeclared = [column for column in columns")
        branch = source[i:i + 900]

        assert "self._ingest_undeclared_columns is False" in branch
        assert "columns = [column for column in columns if column in declared]" \
            in branch

    def test_an_absent_key_warns_rather_than_narrowing(self):
        from pathlib import Path

        source = Path("core/mirror/iceberg_sync.py").read_text()
        i = source.index("undeclared = [column for column in columns")
        branch = source[i:i + 1600]

        assert "is None" in branch
        assert "never declared" in branch


class TestWhatTheWarningSays:
    def test_it_names_the_columns(self):
        """"Some columns" is a warning nobody acts on."""
        from pathlib import Path

        source = Path("core/mirror/iceberg_sync.py").read_text()
        i = source.index("never declared")
        window = source[i:i + 700]

        assert "join(sorted(undeclared)" in window

    def test_it_says_where_the_exposure_is(self):
        """Not "this is insecure" -- which file, which reader. The
        columns are unreachable through Elysium and readable by
        anyone with the lake's files, and those are different
        audiences."""
        from pathlib import Path

        source = Path("core/mirror/iceberg_sync.py").read_text()
        i = source.index("never declared")
        window = source[i:i + 700]

        assert "lake's files" in window
        assert "no field grant" in window
