"""
A data silo may not be named after a pipeline layer (PA001-G10).

THE PIPELINE WRITES ITS LAYERS AS NAMESPACES. A silo `p` produces `p`
(silver), `bronze_p`, `changelog_p` and `quarantine_p`; gold lives in
`gold`, its history in `gold_history`.

SO A SILO CALLED `gold` HAS ITS SILVER TABLE AT `gold.Thing` -- which
is exactly where the gold publication goes. Measured: silver and gold
became the same table. No error, no warning. The publication simply
overwrote the copy it was derived from, and every read afterwards
served a table that was its own source.

A PREFIX COLLIDES TOO, less obviously: a silo named `bronze_x` keeps
its silver in `bronze_x`, which is where silo `x` keeps its bronze.
Two silos' tables interleaved in one namespace.

REFUSED AT LOAD, with the layer named. This is a CONFIGURATION
mistake, the moment to say so is before any data moves, and it is
unfixable afterwards: by the time the collision shows, the tables have
been written over each other.

NOT A SUBSTRING CHECK. `goldmine` and `my_gold` are perfectly good
silo names and are accepted -- an over-eager check here would refuse
a deployment for no reason, which is its own kind of wrong.
"""

import pytest

from core.deployment_loader import (
    RESERVED_SILO_NAMES,
    RESERVED_SILO_PREFIXES,
    _refuse_reserved_silo_names,
)


def _silos(*names):
    return {"data_silos": {name: {"adapter": "sqlite"} for name in names}}


class TestNamesThatCollide:
    @pytest.mark.parametrize("name", ["gold", "gold_history", "gold_conflicts", "_elysium"])
    def test_a_layer_namespace_is_refused(self, name):
        with pytest.raises(ValueError, match=name):
            _refuse_reserved_silo_names(_silos(name))

    @pytest.mark.parametrize("name", ["bronze_x", "changelog_y", "quarantine_z"])
    def test_a_layer_prefix_is_refused(self, name):
        with pytest.raises(ValueError, match=name):
            _refuse_reserved_silo_names(_silos(name))

    def test_the_message_names_the_layer(self):
        """A refusal an operator cannot act on gets the line deleted
        at random until the load succeeds."""
        with pytest.raises(ValueError, match="Rename the silo"):
            _refuse_reserved_silo_names(_silos("gold"))

    def test_one_bad_silo_among_good_ones_is_caught(self):
        with pytest.raises(ValueError, match="gold"):
            _refuse_reserved_silo_names(_silos("primary_sql", "gold", "risk_db"))


class TestNamesThatAreFine:
    @pytest.mark.parametrize("name", [
        "primary_sql", "risk_db", "support_crm",
        "goldmine", "my_gold", "golden_records", "bronzeware",
        "p", "warehouse2",
    ])
    def test_it_is_accepted(self, name):
        """NOT A SUBSTRING CHECK. Refusing `goldmine` would break a
        deployment for no reason."""
        _refuse_reserved_silo_names(_silos(name))

    def test_an_empty_configuration_is_fine(self):
        _refuse_reserved_silo_names({})
        _refuse_reserved_silo_names({"data_silos": {}})
        _refuse_reserved_silo_names({"data_silos": None})


class TestItIsWiredIntoTheLoad:
    """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Every test above calls
    the function directly, so REMOVING THE CALL to it -- which is the
    whole defect -- left all eighteen passing. What matters is that a
    deployment declaring such a silo cannot load."""

    def test_a_deployment_with_a_silo_called_gold_refuses_to_load(self, tmp_path):
        import shutil
        from pathlib import Path

        from core.deployment_loader import load_deployment

        fixtures = Path("tests/integration/fixtures")
        for name in ("config.yaml", "ontology_schema.yaml", "policy.yaml",
                      "data_silos.yaml"):
            shutil.copy(fixtures / name, tmp_path / name)
        silos = (tmp_path / "data_silos.yaml").read_text()
        # rename the first silo to `gold`, leaving everything else alone
        silos = silos.replace("primary_sql:", "gold:", 1)
        (tmp_path / "data_silos.yaml").write_text(silos)

        with pytest.raises(ValueError, match="gold"):
            load_deployment(tmp_path)

    def test_the_unmodified_fixture_still_loads(self, tmp_path):
        """The other half: the check must not refuse a good
        deployment."""
        import shutil
        from pathlib import Path

        from core.deployment_loader import load_deployment

        fixtures = Path("tests/integration/fixtures")
        for name in ("config.yaml", "ontology_schema.yaml", "policy.yaml",
                      "data_silos.yaml"):
            shutil.copy(fixtures / name, tmp_path / name)

        assert load_deployment(tmp_path) is not None


class TestTheReservedSetItself:
    def test_it_matches_what_the_pipeline_writes(self):
        """If a new layer is added elsewhere, this is where it has to
        be declared too -- and the test says so rather than leaving it
        to be discovered by a collision."""
        from core.mirror.gold_history import CHANGELOG_NAMESPACE
        from core.mirror.quarantine_report import QUARANTINE_PREFIX
        from core.ontology.gold_view import GOLD_NAMESPACE

        assert GOLD_NAMESPACE in RESERVED_SILO_NAMES
        assert CHANGELOG_NAMESPACE in RESERVED_SILO_NAMES
        assert QUARANTINE_PREFIX in RESERVED_SILO_PREFIXES
        assert "bronze_" in RESERVED_SILO_PREFIXES

    def test_the_loader_reads_the_one_declaration(self):
        import core.lake_names as lake_names

        assert RESERVED_SILO_NAMES is lake_names.RESERVED_SILO_NAMES
        assert RESERVED_SILO_PREFIXES is lake_names.RESERVED_SILO_PREFIXES

    def test_every_namespace_constant_the_mirror_declares_is_reserved(self):
        """Derived from the mirror code, not from a list written here:
        every module-level `*_NAMESPACE` or `*_PREFIX` string in
        core/mirror and scripts must be a reserved name or prefix (or be
        on the short list of things that are not lake names)."""
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent
        # Not catalog namespaces: the OpenLineage job namespace and the
        # marker on synthetic evaluation rows.
        not_lake_names = {"DEFAULT_NAMESPACE", "SYNTHETIC_PREFIX"}
        found = {}
        for folder in ("core/mirror", "scripts"):
            for path in (root / folder).glob("*.py"):
                for node in ast.parse(path.read_text()).body:
                    if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                            and isinstance(node.value.value, str)):
                        for target in node.targets:
                            if (isinstance(target, ast.Name)
                                    and target.id.endswith(("_NAMESPACE", "_PREFIX"))
                                    and target.id not in not_lake_names):
                                found[f"{path.name}:{target.id}"] = node.value.value
        # The module-level constants now live in core/lake_names.py, so
        # the mirror declares none of its own: a new one is a new
        # layer, and has to be declared there.
        assert found == {}, f"declare these in core/lake_names.py instead: {found}"

    @staticmethod
    def _undeclared_heads(source: str) -> list[str]:
        """Literal namespace heads handed to a catalog call that are not
        a reserved name or prefix."""
        import ast

        from core.lake_names import RESERVED_SILO_NAMES as names
        from core.lake_names import RESERVED_SILO_PREFIXES as prefixes

        calls = {"create_namespace", "namespace_exists", "load_table", "list_tables",
                 "create_table", "drop_table"}
        undeclared = []
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in calls and node.args):
                continue
            first = node.args[0]
            if isinstance(first, ast.JoinedStr) and first.values \
                    and isinstance(first.values[0], ast.Constant):
                head = first.values[0].value
            elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                head = first.value
            else:
                continue
            namespace = head.split(".")[0]
            if namespace and not (namespace in names or namespace.startswith(prefixes)):
                undeclared.append(f"line {node.lineno}: {head!r}")
        return undeclared

    def test_no_mirror_code_builds_a_namespace_from_an_undeclared_prefix(self):
        """A literal `f"archive_{silo}"` handed to the catalog is a new
        layer nobody reserved."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent
        undeclared = []
        for folder in ("core", "scripts", "api"):
            for path in (root / folder).rglob("*.py"):
                undeclared += [f"{path.relative_to(root)} {u}"
                               for u in self._undeclared_heads(path.read_text())]
        assert undeclared == [], undeclared

    def test_that_scan_notices_an_undeclared_prefix_and_passes_declared_ones(self):
        """Its own control: a scan that found nothing anywhere would
        make the test above pass for ever."""
        assert self._undeclared_heads('catalog.load_table(f"archive_{silo}.{t}")') \
            == ["line 1: 'archive_'"]
        assert self._undeclared_heads('catalog.create_namespace("scratch")') \
            == ["line 1: 'scratch'"]
        assert self._undeclared_heads('catalog.load_table(f"bronze_{silo}.{t}")') == []
        assert self._undeclared_heads('catalog.create_namespace("gold_conflicts")') == []

    def test_a_silo_named_like_a_derived_layer_but_longer_is_still_a_source(self):
        """`goldmine` is accepted as a silo name, so the integrity check
        must treat its tables as source copies; it used to test
        startswith("gold") and skip them."""
        from core.mirror.integrity import _not_a_source_layer

        assert _not_a_source_layer("gold")
        assert _not_a_source_layer("gold_history")
        assert _not_a_source_layer("gold_conflicts")
        assert _not_a_source_layer("changelog_p")
        assert not _not_a_source_layer("goldmine")
        assert not _not_a_source_layer("bronze_p")
