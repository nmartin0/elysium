"""Putting an earlier configuration back (DEV_UI 13.7, decided 16 October),
over HTTP against a COPY of the fixture configuration.

A restore is a NEW generation whose files are the old one's -- history
grows, it is never rewound. It applies at once unless anyone could read
more afterwards; then it waits, like a label, for a role manager.
"""

import pytest
import yaml

from api.reload import reload_generation
from core.config_editing import apply_labels
from tests.integration import test_access_labels as labels
from tests.integration.test_api import _csrf_headers

config_dir = labels.config_dir
enforcing = labels.enforcing
FILE = "ontology_schema.yaml"


def _edit_by_hand(client, filename, change):
    """An operator's edit and reload: a new generation, recorded."""
    path = client.app.state.runtime_paths.config_dir / filename
    path.write_text(change(path.read_text()))
    return reload_generation(client.app, requested_by="test").generation


def _preview(client, generation):
    return client.get(f"/api/admin/config-restore/{generation}")


def _restore(client, generation, reason=None, digest=None):
    digest = digest or _preview(client, generation).json()["digest"]
    return client.post(f"/api/admin/config-restore/{generation}", headers=_csrf_headers(client),
                       json={"digest": digest, "reason": reason})


def _with_name_labelled(text):
    return apply_labels(text, [{"object_type": "Customer", "field": "name", "labels": ["pii"]}])


@pytest.fixture
def two_versions(enforcing):
    """Generation `first` as the fixture starts; then name labelled pii by
    hand -- which only closes -- as the generation running now."""
    first = enforcing.app.state.generation.generation
    _edit_by_hand(enforcing, FILE, _with_name_labelled)
    return enforcing, first


class TestWhatItShows:
    def test_the_lines_that_go_back_and_what_that_does(self, two_versions):
        client, first = two_versions

        preview = _preview(client, first).json()

        [changed] = preview["files"]
        assert changed["name"] == FILE
        assert any(line.startswith("-") and "classification: pii" in line for line in changed["diff"])
        # name opens again to every role that reads it without the label.
        gained = {(r["role"], f["field"]) for r in preview["impact"]["roles"] for f in r["fields_gained"]}
        assert ("customer_service", "name") in gained
        assert preview["needs_approval"] is True

    def test_files_that_hold_connections_are_named_not_shown(self, enforcing):
        first = enforcing.app.state.generation.generation
        _edit_by_hand(enforcing, "data_silos.yaml", lambda text: text + "\n# moved somewhere\n")

        preview = _preview(enforcing, first).json()

        [changed] = preview["files"]
        assert changed["name"] == "data_silos.yaml"
        assert changed["diff"] == [
            "data_silos.yaml changes too. Its lines are not shown here: it holds where each "
            "source is and how to reach it."]

    def test_it_says_when_roles_are_not_part_of_it(self, two_versions):
        client, first = two_versions

        assert _preview(client, first).json()["roles_in_store"] is False


class TestPuttingItBack:
    def test_a_restore_that_opens_nothing_applies_as_a_new_generation(self, enforcing, config_dir):
        first = enforcing.app.state.generation.generation
        original = (config_dir / FILE).read_text()
        second = _edit_by_hand(enforcing, FILE, lambda text: text.replace(
            "plural_display_name: Customers", "plural_display_name: Clients"))

        response = _restore(enforcing, first)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "applied"
        assert response.json()["to_generation"] > second
        assert (config_dir / FILE).read_text() == original
        # History grows, it is not rewound: the version restored from is
        # still there to go back to.
        assert enforcing.app.state.config_history.get(second) is not None

    def test_a_widening_restore_waits_with_its_reason_and_the_approver_applies_it(
            self, two_versions, config_dir):
        client, first = two_versions
        before = (config_dir / FILE).read_text()

        waiting = _restore(client, first, reason="the label on name was a mistake")
        assert waiting.json()["status"] == "waiting"
        assert (config_dir / FILE).read_text() == before

        labels._as(client, "rita")
        [proposal] = client.get("/api/admin/config-proposals").json()["proposals"]
        assert proposal["kind"] == "restore"
        assert proposal["reason"] == "the label on name was a mistake"
        approved = client.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/approve",
                               headers=_csrf_headers(client))

        assert approved.status_code == 200, approved.text
        assert (config_dir / FILE).read_text() == client.app.state.config_history.get(first).files[FILE]

    def test_a_widening_restore_without_a_reason_is_refused(self, two_versions):
        client, first = two_versions

        assert _restore(client, first).status_code == 400

    def test_a_file_changed_since_the_preview_is_refused(self, two_versions, config_dir):
        client, first = two_versions
        seen = _preview(client, first).json()["digest"]
        path = config_dir / "config.yaml"
        path.write_text(path.read_text() + "\n# an operator's hand edit\n")

        response = _restore(client, first, reason="x", digest=seen)

        assert response.status_code == 409
        assert "an operator's hand edit" in path.read_text()


class TestWhatItRefuses:
    def test_nothing_to_put_back(self, enforcing):
        now = enforcing.app.state.generation.generation

        response = _preview(enforcing, now)

        assert response.status_code == 400
        assert "nothing to put back" in response.json()["detail"]

    def test_an_unknown_generation(self, enforcing):
        assert _preview(enforcing, 999_999).status_code == 404

    def test_a_data_type_does_not_go_back(self, enforcing, config_dir):
        """Transaction.amount is a number in the fixture. A version where it
        was text cannot be put back over it: the lake cannot follow."""
        first = enforcing.app.state.generation.generation

        def amount_as_text(text):
            schema = yaml.safe_load(text)
            assert schema["object_types"]["Transaction"]["fields"]["amount"]["data_type"] == "number"
            return text.replace("      amount:\n        type: data\n        data_type: number",
                                "      amount:\n        type: data\n        data_type: string")
        _edit_by_hand(enforcing, FILE, amount_as_text)

        response = _preview(enforcing, first)

        assert response.status_code == 400
        assert "Transaction.amount from string to number" in response.json()["detail"]

    def test_a_file_that_comes_or_goes(self, enforcing):
        """A version recorded without data_silos.yaml: putting it back would
        mean deleting the file, which a restore never does. Recorded
        directly, because no loadable configuration lacks that file."""
        history = enforcing.app.state.config_history
        now = history.get(enforcing.app.state.generation.generation)
        files = {name: text for name, text in now.files.items() if name != "data_silos.yaml"}
        history.record(900_000, now.loaded_at, "a-digest", files)

        response = _preview(enforcing, 900_000)

        assert response.status_code == 400
        assert "data_silos.yaml, which is not here now" not in response.json()["detail"]
        assert "no data_silos.yaml" in response.json()["detail"]
        assert "adding or deleting a file" in response.json()["detail"]

    def test_it_is_for_deployment_managers(self, enforcing):
        first = enforcing.app.state.generation.generation
        labels._as(enforcing, "rita")

        assert _preview(enforcing, first).status_code == 403
        assert enforcing.post(f"/api/admin/config-restore/{first}", headers=_csrf_headers(enforcing),
                              json={"digest": "x"}).status_code == 403


def test_an_approved_restore_does_not_return_lines_it_never_showed(enforcing):
    """The approve response carries the change as the interface may show
    it: a data_silos.yaml put back is named, not printed."""
    first = enforcing.app.state.generation.generation
    _edit_by_hand(enforcing, "data_silos.yaml", lambda text: text + "\n# moved somewhere\n")
    _edit_by_hand(enforcing, FILE, _with_name_labelled)
    assert _restore(enforcing, first, reason="both back").json()["status"] == "waiting"
    labels._as(enforcing, "rita")
    [proposal] = enforcing.get("/api/admin/config-proposals").json()["proposals"]

    response = enforcing.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/approve",
                              headers=_csrf_headers(enforcing))

    assert response.status_code == 200, response.text
    assert not any("moved somewhere" in line for line in response.json()["diff"])
    assert not any("moved somewhere" in line for line in proposal["diff"])
