"""
A silo's credentials never reach the lake (PA001-A11).

WHAT HAPPENED. The manifest published data_silos.yaml VERBATIM, and a
silo's `connection` block is where its credentials live -- a
SQLAlchemy URL carries its password inline:

    url: postgresql://elysium:hunter2@db.internal:5432/prod

`${VAR}` references make that avoidable and nothing REFUSES a literal,
so a deployment that typed one had it copied into the lake. Since
OPEN_RISKS item 2 we describe the lake as part of the security
perimeter: read access to that directory is read access to everything
in it, with no audit entry.

AN ALLOW-LIST, NOT REDACTION, and the reason is this file's own:

    NOT "everything except secrets". An exclusion list is correct only
    until someone adds a file, and the failure is silent and total.

The same is true INSIDE the file. Stripping keys that "look secret" is
an exclusion list by another name, correct only until an adapter
invents a key nobody thought of. So the manifest keeps the keys a lake
reader NEEDS -- which silos exist and what kind each is, so the table
names in ontology_schema.yaml resolve -- and a connection string is
not among them. A reader of the lake is not connecting to the sources.

THE FILE IS REWRITTEN, NOT OMITTED. Dropping it would lose the silo
names, which the schema references and a reader cannot resolve
without.
"""

import pytest
import yaml

from core.mirror.manifest import (
    PUBLISHABLE,
    SILO_KEYS_PUBLISHED,
    _silos_without_connections,
    build_manifest,
)

WITH_A_PASSWORD = """data_silos:
  primary_sql:
    adapter: sqlalchemy
    connection:
      url: postgresql://elysium:SUPERSECRET123@db.internal:5432/prod
  risk_db:
    adapter: sqlite
    connection:
      path: /var/lib/risk.db
"""


class TestNothingFromAConnectionBlockIsPublished:
    @pytest.mark.parametrize("secret", ["SUPERSECRET123", "db.internal",
                                         "/var/lib/risk.db", "postgresql://"])
    def test_the_secret_is_gone(self, secret):
        assert secret not in _silos_without_connections(WITH_A_PASSWORD)

    def test_the_word_connection_does_not_appear_at_all(self):
        """Not just the values: the block itself. A key named
        `connection` in a published file invites the next person to
        add something to it."""
        assert "connection" not in _silos_without_connections(WITH_A_PASSWORD)

    def test_a_VAR_reference_is_dropped_too(self):
        """Even a `${VAR}` is a connection detail: it names an
        environment variable on the deployment's host, which a lake
        reader has no business knowing."""
        content = """data_silos:
  p:
    adapter: sqlalchemy
    connection:
      url: ${ELYSIUM_PRIMARY_URL}
"""
        assert "ELYSIUM_PRIMARY_URL" not in _silos_without_connections(content)


class TestThroughTheManifestItself:
    """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Every test above calls
    the helper directly, so removing the CALL to it -- publishing the
    file verbatim again, which is the original bug exactly -- left all
    of them passing. What matters is what ends up in the manifest."""

    def _manifest(self):
        return build_manifest(
            generation=1, loaded_at="2026-09-25T00:00:00+00:00",
            source_digest="abc",
            files={"data_silos.yaml": WITH_A_PASSWORD,
                    "ontology_schema.yaml": "object_types: {}\n",
                    "policy.yaml": "roles: {}\n"},
            tables=["p.customers"])

    def test_the_password_is_not_in_the_manifest(self):
        assert "SUPERSECRET123" not in str(self._manifest())

    def test_nor_the_host_nor_the_path(self):
        document = str(self._manifest())

        assert "db.internal" not in document
        assert "/var/lib/risk.db" not in document

    def test_the_silo_names_are(self):
        published = yaml.safe_load(self._manifest()["files"]["data_silos.yaml"])

        assert sorted(published["data_silos"]) == ["primary_sql", "risk_db"]

    def test_the_other_files_are_untouched(self):
        """Only data_silos.yaml is rewritten. The schema and the policy
        go through as they are."""
        manifest = self._manifest()

        assert manifest["files"]["ontology_schema.yaml"] == "object_types: {}\n"
        assert manifest["files"]["policy.yaml"] == "roles: {}\n"


class TestWhatAReaderStillGets:
    def test_the_silo_names_survive(self):
        """The schema references silos by name; without them a reader
        cannot resolve a single table."""
        published = yaml.safe_load(_silos_without_connections(WITH_A_PASSWORD))

        assert sorted(published["data_silos"]) == ["primary_sql", "risk_db"]

    def test_the_adapter_kind_survives(self):
        published = yaml.safe_load(_silos_without_connections(WITH_A_PASSWORD))

        assert published["data_silos"]["primary_sql"]["adapter"] == "sqlalchemy"
        assert published["data_silos"]["risk_db"]["adapter"] == "sqlite"

    def test_it_is_still_valid_yaml(self):
        """A manifest a reader cannot parse is a manifest nobody
        reads."""
        assert yaml.safe_load(_silos_without_connections(WITH_A_PASSWORD))

    def test_the_allow_list_is_exactly_what_is_kept(self):
        """If someone widens SILO_KEYS_PUBLISHED, this test is where
        they have to argue for it."""
        published = yaml.safe_load(_silos_without_connections(WITH_A_PASSWORD))

        for block in published["data_silos"].values():
            assert set(block) <= set(SILO_KEYS_PUBLISHED)


class TestUnparseableInput:
    @pytest.mark.parametrize("content", [
        "data_silos: [not a mapping\n",
        "::: not yaml at all :::\n",
        "data_silos: a string\n",
    ])
    def test_it_is_withheld_rather_than_published(self, content):
        """The case where guessing what is safe is least defensible."""
        out = _silos_without_connections(content)

        assert "withheld" in out
        assert "data_silos:" not in out.replace("# withheld", "")

    def test_an_empty_file_publishes_nothing_and_does_not_raise(self):
        assert yaml.safe_load(_silos_without_connections("")) == {"data_silos": {}}


class TestTheFileIsStillListedAsPublishable:
    def test_data_silos_is_published_not_withheld(self):
        """Withholding it entirely would lose the silo names. The
        point is that its CONTENT is now narrower, not that the file
        disappeared -- a reader finding it absent would not know
        whether that was deliberate."""
        assert "data_silos.yaml" in PUBLISHABLE
