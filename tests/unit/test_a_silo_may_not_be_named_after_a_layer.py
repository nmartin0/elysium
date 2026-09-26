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
    @pytest.mark.parametrize("name", ["gold", "gold_history"])
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
