"""
A confirmed write reaches only the silos a deployment named.

WHAT WAS TRUE BEFORE THIS. `write_adapters` were built from the SAME
silo entries the readers use, with no toggle anywhere:

    write_adapters are always built live, against the customer's real
    database -- a confirmed write must never land in a copy that the
    next sync would simply overwrite.

That reasoning is right and it is about WHERE a write lands, not about
WHETHER one may. The consequence was that a deployment installed to
LOOK at data could be made to CHANGE it, and nothing in the
configuration said so or prevented it.

A SEPARATE BLOCK, NOT A FLAG ON EACH SILO. The owner's decision, and
the stronger shape: a silo you only meant to read cannot become
writable by someone editing the entry you read it through. A write
target is named on purpose, in its own place.

THREE STATES, AND THE THIRD IS THE ONE THE PRECEDENT DEMANDS.
Secure-by-default flips are applied to NEW installations while
existing ones keep their behaviour until an operator changes it --
that is what projects shipping this kind of change actually do, and
flipping it silently would break a working deployment to make a point
it had not been told about.

    absent        keeps writing everywhere, and warns at startup
    `[]`          refuses every external write
    named silos   those and no others

THE REFUSAL IS AN ABSENCE, NOT A CHECK. A silo with no write adapter
cannot be written to by any path, because the WriteMediator looks one
up by silo name and there is nothing to find. A check somewhere could
be forgotten; a missing adapter cannot.
"""

import pytest

from core.deployment_loader import _resolve_write_targets, _writable_silo_configs


class _Config:
    def __init__(self, write_targets):
        self.write_targets = write_targets


SILOS = {"primary_sql": {"adapter": "sqlite"},
         "warehouse": {"adapter": "sqlite"}}


class TestWhatTheConfigMeans:
    def test_an_absent_key_is_not_an_empty_list(self):
        """The distinction the whole upgrade path rests on."""
        assert _resolve_write_targets({}) is None

    def test_a_declared_empty_list_is_empty(self):
        assert _resolve_write_targets({"write_targets": []}) == ()

    def test_named_silos_come_back_in_order(self):
        assert _resolve_write_targets(
            {"write_targets": ["a", "b"]}) == ("a", "b")

    def test_a_bare_string_is_refused_rather_than_iterated(self):
        """`write_targets: primary_sql` without a dash is the obvious
        typo, and treating a string as a list of characters would make
        every single-letter silo name writable."""
        with pytest.raises(ValueError, match="not a string"):
            _resolve_write_targets({"write_targets": "primary_sql"})


class TestWhichSilosGetAWriteAdapter:
    def test_absent_keeps_every_silo_writable(self):
        """THE UPGRADE PATH. An existing deployment keeps its behaviour
        rather than breaking on upgrade."""
        assert _writable_silo_configs(_Config(None), SILOS) == SILOS

    def test_absent_warns_and_names_a_real_silo(self, caplog):
        """A warning that says 'configure it' without saying what to
        write is a warning somebody ignores."""
        with caplog.at_level("WARNING"):
            _writable_silo_configs(_Config(None), SILOS)

        assert "write_targets" in caplog.text
        assert "primary_sql" in caplog.text

    def test_declared_empty_leaves_nothing_writable(self):
        """THE NEW DEFAULT. No adapter exists, so no path can write."""
        assert _writable_silo_configs(_Config(()), SILOS) == {}

    def test_only_the_named_silo_is_writable(self):
        writable = _writable_silo_configs(_Config(("primary_sql",)), SILOS)

        assert list(writable) == ["primary_sql"]
        assert "warehouse" not in writable

    def test_a_name_that_is_not_a_silo_is_an_error(self):
        """Silently writing nowhere because of a typo is this feature's
        own failure mode, inverted: the operator believes writes are
        enabled and they are not."""
        with pytest.raises(ValueError, match="not a configured silo"):
            _writable_silo_configs(_Config(("primry_sql",)), SILOS)

    def test_the_error_lists_what_was_available(self):
        with pytest.raises(ValueError, match="warehouse"):
            _writable_silo_configs(_Config(("nope",)), SILOS)


class TestTheDefaultShipped:
    def test_the_template_config_declares_it(self):
        """A new deployment must start OFF, which means the key is in
        the template rather than merely documented."""
        from pathlib import Path

        config = Path("deployment/etc/config.yaml").read_text()

        assert "write_targets" in config


class TestTheGateIsActuallyWired:
    """The regression test. A gate nothing calls is the shape this
    codebase has produced six times: a retention property nothing acted
    on, an adapter nothing constructed, an atomic method the route
    ignored, a repair tool the failure never mentioned, a manifest
    nothing opened, a history nothing read.
    """

    def test_the_write_adapters_are_built_from_the_filtered_set(self):
        from pathlib import Path

        source = Path("core/deployment_loader.py").read_text()
        i = source.index("write_adapters = cast(")
        window = source[i - 400:i + 300]

        assert "_writable_silo_configs(config, resolved_silo_configs)" in window
        assert "_build_adapters(writable, _WRITE_ADAPTER_REGISTRY)" in window

    def test_the_readers_are_not_filtered_by_it(self):
        """Declaring no write target must not stop the deployment
        READING. The whole point is that a read-only install is a
        normal install."""
        from pathlib import Path

        source = Path("core/deployment_loader.py").read_text()
        i = source.index("def _build_read_adapters")
        body = source[i:source.index("\ndef ", i + 10)]

        assert "_writable_silo_configs" not in body

