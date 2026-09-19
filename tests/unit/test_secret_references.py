"""
Credentials come from the environment, not the config file.

THE PROBLEM, NOW CONCRETE. A SQLAlchemy silo is declared with a URL,
and a real one carries a password. That file is read by anyone who can
read the config directory, lands in every backup, and goes into
version control if a deployment tracks its own configuration -- which
is the ordinary thing to do.

`${VAR}`, DELIBERATELY, AND NOTHING CLEVERER. It is the notation
operators already know from shell, docker-compose, Kubernetes and CI,
and it needs no new vocabulary in a file that has plenty.

WHAT THIS IS NOT: a secret store, rotation, or an audit of who read
what. It moves a credential into the process environment, where
systemd's EnvironmentFile=, a container's secret mount and every CI
system already put them. A smaller claim than "secret management" and
the one worth making first.
"""

import pytest

from core.secret_references import MissingSecret, expand_secrets


class TestItSubstitutes:
    def test_a_lone_reference(self, monkeypatch):
        monkeypatch.setenv("ELYSIUM_TEST_PW", "hunter2")

        assert expand_secrets("${ELYSIUM_TEST_PW}") == "hunter2"

    def test_one_embedded_in_a_url(self, monkeypatch):
        """THE SHAPE THAT MATTERS. A connection URL carries the
        credential in the middle of other text, so substituting only
        whole-string references would miss the case this exists for."""
        monkeypatch.setenv("ELYSIUM_TEST_PW", "hunter2")

        assert expand_secrets(
            "postgresql+psycopg://elysium:${ELYSIUM_TEST_PW}@db/warehouse",
        ) == "postgresql+psycopg://elysium:hunter2@db/warehouse"

    def test_several_in_one_string(self, monkeypatch):
        monkeypatch.setenv("ELYSIUM_TEST_USER", "elysium")
        monkeypatch.setenv("ELYSIUM_TEST_PW", "hunter2")

        assert expand_secrets(
            "${ELYSIUM_TEST_USER}:${ELYSIUM_TEST_PW}",
        ) == "elysium:hunter2"

    def test_it_reaches_into_dicts(self, monkeypatch):
        # A connection block IS a dict, and nothing guarantees the
        # credential sits at the top level.
        monkeypatch.setenv("ELYSIUM_TEST_PW", "hunter2")

        assert expand_secrets({"connection": {"url": "${ELYSIUM_TEST_PW}"}}) == {
            "connection": {"url": "hunter2"},
        }

    def test_it_reaches_into_lists(self, monkeypatch):
        monkeypatch.setenv("ELYSIUM_TEST_PW", "hunter2")

        assert expand_secrets(["${ELYSIUM_TEST_PW}"]) == ["hunter2"]


class TestItLeavesEverythingElseAlone:
    def test_a_plain_string_is_unchanged(self):
        assert expand_secrets("dev_fixtures/mediator.db") == (
            "dev_fixtures/mediator.db"
        )

    def test_non_strings_keep_their_type(self):
        """A PORT NUMBER IS AN int AND MUST STAY ONE. Calling str() on
        it to run a regex would silently change its type, and the
        driver would get text where it expected a number."""
        assert expand_secrets({"port": 5432, "ssl": True}) == {
            "port": 5432, "ssl": True,
        }

    def test_a_dollar_without_braces_is_not_a_reference(self):
        # Passwords contain $ more often than they contain ${.
        assert expand_secrets("pa$$word") == "pa$$word"


class TestAMissingVariableIsFatal:
    def test_it_raises_rather_than_substituting_nothing(self, monkeypatch):
        """SUBSTITUTING AN EMPTY STRING would produce a URL that looks
        complete and connects as nobody, and the resulting error would
        name the DATABASE rather than the configuration."""
        monkeypatch.delenv("ELYSIUM_TEST_ABSENT", raising=False)

        with pytest.raises(MissingSecret):
            expand_secrets("${ELYSIUM_TEST_ABSENT}")

    def test_the_message_names_the_variable(self, monkeypatch):
        monkeypatch.delenv("ELYSIUM_TEST_ABSENT", raising=False)

        with pytest.raises(MissingSecret, match="ELYSIUM_TEST_ABSENT"):
            expand_secrets("${ELYSIUM_TEST_ABSENT}")

    def test_and_where_it_was_found(self, monkeypatch):
        """A DEPLOYMENT HAS SEVERAL SILOS. Naming the variable without
        naming the field leaves an operator grepping."""
        monkeypatch.delenv("ELYSIUM_TEST_ABSENT", raising=False)

        with pytest.raises(MissingSecret, match=r"primary_sql\.connection\.url"):
            expand_secrets(
                {"url": "${ELYSIUM_TEST_ABSENT}"},
                where="primary_sql.connection",
            )


class TestAgainstARealDeployment:
    def test_a_silo_path_can_come_from_the_environment(self, monkeypatch, tmp_path):
        """END TO END, because the function working says nothing about
        whether the loader calls it."""
        import shutil

        from core.deployment_loader import build_generation, resolve_runtime_paths

        paths = resolve_runtime_paths()
        config = tmp_path / "etc"
        shutil.copytree(paths.config_dir, config)
        silos = config / "data_silos.yaml"
        silos.write_text(
            silos.read_text().replace(
                'path: "dev_fixtures/mediator.db"', 'path: "${ELYSIUM_TEST_DB}"',
            ),
        )

        monkeypatch.delenv("ELYSIUM_TEST_DB", raising=False)
        with pytest.raises(MissingSecret, match="ELYSIUM_TEST_DB"):
            build_generation(config, paths.data_dir, tmp_path / "log")

        monkeypatch.setenv("ELYSIUM_TEST_DB", "dev_fixtures/mediator.db")
        assert build_generation(config, paths.data_dir, tmp_path / "log")
