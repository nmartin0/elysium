"""
Every deployment setting is either shown in `/api/config` or named as
deliberately withheld.

`F-06` recorded that `DeploymentConfigResponse` duplicates
`DeploymentConfig` field-for-field, and was deferred in patch 459
because `api/routes.py` was "a SHARED read-only file under
000COORDINATION, with three agents working". Those agents no longer
exist and that document was consumed, so the reason expired.

IT WAS NOT A TIDINESS COMPLAINT. The harm is DRIFT, and it had already
happened four times -- all four in October, all four mine.
`write_targets`, `trusted_proxies`, `on_type_mismatch` and
`ingest_undeclared_columns` were each added to `DeploymentConfig` and
not to the response, so the panel that exists to answer "why is it
behaving like that" could not answer it for any of them.

THE OMISSION IS SILENT BY CONSTRUCTION. Pydantic drops what the model
does not name, so a route can return a field faithfully and no client
ever sees it -- the same mechanism that nearly swallowed
`disabled_conditions` in the saved-views work.

SO THIS IS A COVERAGE TEST, NOT A DEDUPLICATION. Generating the
response model from the dataclass would expose `users`, `roles`,
`llm_connection` and the silo connection details, which the route's
own docstring says "must never reach a UI". The duplication is the
safe part; the forgetting is the bug.
"""

import dataclasses
import re
from pathlib import Path

import pytest

from core.deployment_loader import DeploymentConfig

#: Settings the config panel deliberately does not show, and why.
#: Adding a field to `DeploymentConfig` means adding it to the response
#: or to this map -- the test below accepts nothing else.
WITHHELD_FROM_CONFIG_RESPONSE = {
    "llm_connection": "hosts, paths and credential references",
    "silo_configs": "connection details -- the material the Silo work "
                     "says must never reach a UI",
    "users": "already served, properly scoped, by /users",
    "roles": "named in `role_names`; the GRANTS would answer "
              "'what could I attack'",
    "schema": "the ontology itself, served by /schema per caller",
    "action_types": "counted in `action_type_count`",
    "declared_triggers": "operational detail with no panel to show it",
    "source_text": "the raw configuration file, including anything "
                    "a deployment put in it",
    "base_path": "a filesystem path on the server",
    "mirror_storage": "warehouse paths and credentials",
    "identity_inference": "a mirror-build setting, not a runtime one",
    "pending_write_ttl_minutes": "not yet surfaced; no panel field",
    "query_deadline_seconds": "not yet surfaced; no panel field",
    "retain_publications": "a mirror-retention setting",
    "security_attribute": "shown -- see the response model",
    "read_from_mirror": "shown -- see the response model",
    "freshness_targets": "the DERIVED per-type windows; the number an "
                          "operator actually declared is shown as "
                          "`sync_interval_hours`. Showing the map would "
                          "put the ontology in a settings panel, and "
                          "every entry in it is that one number times a "
                          "constant",
}


def _response_fields():
    source = Path("api/routes.py").read_text()
    i = source.index("class DeploymentConfigResponse")
    body = source[i:source.index("\n\n\n", i)]
    return set(re.findall(r"^    (\w+):", body, re.M))


def _config_fields():
    return {field.name for field in dataclasses.fields(DeploymentConfig)}


class TestNothingIsSilentlyOmitted:
    def test_every_setting_is_shown_or_withheld_on_purpose(self):
        """THE REGRESSION TEST. Four settings reached production
        invisible to the panel because nothing forced the choice."""
        unaccounted = sorted(
            _config_fields() - _response_fields()
            - set(WITHHELD_FROM_CONFIG_RESPONSE))

        assert unaccounted == [], (
            f"these deployment settings are neither in "
            f"DeploymentConfigResponse nor named in "
            f"WITHHELD_FROM_CONFIG_RESPONSE: {unaccounted}. Add them to "
            f"the response, or to the map with a reason -- a setting the "
            f"panel cannot show is a behaviour nobody can explain.")

    def test_the_withheld_map_has_a_reason_for_each(self):
        """A name with no reason is a list that rots into 'whatever we
        happened to leave out'."""
        empty = sorted(name for name, why in
                       WITHHELD_FROM_CONFIG_RESPONSE.items()
                       if not (why or "").strip())

        assert empty == []

    def test_the_withheld_map_names_no_field_that_vanished(self):
        """A withheld entry for a setting that no longer exists is a
        stale exemption, and the next person reads it as current."""
        stale = sorted(set(WITHHELD_FROM_CONFIG_RESPONSE) - _config_fields())

        assert stale == []


class TestTheFourThatDrifted:
    @pytest.mark.parametrize("setting", [
        "write_targets", "trusted_proxies",
        "on_type_mismatch", "ingest_undeclared_columns",
    ])
    def test_it_is_in_the_response_model(self, setting):
        assert setting in _response_fields()

    @pytest.mark.parametrize("setting", [
        "write_targets", "trusted_proxies",
        "on_type_mismatch", "ingest_undeclared_columns",
    ])
    def test_the_route_actually_returns_it(self, setting):
        """Declared and not returned is the same invisibility, reached
        the other way round."""
        source = Path("api/routes.py").read_text()
        i = source.index("def deployment_config_route")
        body = source[i:source.index("\n@router", i)]

        assert f'"{setting}": config.{setting}' in body


class TestWhySoAndNotGenerated:
    def test_the_secrets_are_withheld(self):
        """Generating the response from the dataclass would expose
        these. The duplication is the safe part."""
        for secret in ("llm_connection", "silo_configs", "users"):
            assert secret in WITHHELD_FROM_CONFIG_RESPONSE
            assert secret not in _response_fields()

