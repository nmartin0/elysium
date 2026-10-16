"""Access labels from the UI, and the second person a widening waits for
(DEV_UI 13.7, decided 16 October), over HTTP against a COPY of the
fixture configuration -- these tests write the files.

The rule under test: a label change waits for a holder of manage:roles
who did not propose it EXACTLY WHEN someone could read more afterwards,
as the permission code answers it. Not by the edit's direction: with
enforcement on, adding a label can open a field.
"""

import pytest
import yaml

from core.config_editing import apply_labels
from tests.conftest import read_audit_log
from tests.integration import test_editing_config_from_the_ui as editing
from tests.integration.test_api import _csrf_headers, _login

config_dir = editing.config_dir
FILE = "ontology_schema.yaml"


def _roles(config_dir, **roles):
    """Adds roles to the copy's policy.yaml. IN THE FILE, not in memory:
    a candidate configuration is loaded from the files, and roles that
    exist only in memory would differ from it in every comparison."""
    path = config_dir / "policy.yaml"
    policy = yaml.safe_load(path.read_text())
    policy["roles"].update({name: {"allowed_actions": grants} for name, grants in roles.items()})
    path.write_text(yaml.safe_dump(policy, sort_keys=False))


def _deployment(config_dir, request, *, enforcing):
    if enforcing:
        (config_dir / "config.yaml").write_text(
            (config_dir / "config.yaml").read_text() + "\naccess:\n  label_enforcement: true\n")
    # Customer.email and risk_score carry pii, so a role's read:label:pii
    # names a label some field carries (the loader refuses one naming
    # none) whichever one a test takes it off.
    ontology = config_dir / FILE
    ontology.write_text(apply_labels(ontology.read_text(), [
        {"object_type": "Customer", "field": "email", "labels": ["pii"]},
        {"object_type": "Customer", "field": "risk_score", "labels": ["pii"]}]))
    _roles(config_dir,
           deployer=["manage:deployment"],
           approver=["manage:roles"],
           second_approver=["manage:roles"],
           # Reads Customer and whatever carries pii -- and no field by name.
           labelled_reader=["read:Customer", "read:label:pii"])
    client = request.getfixturevalue("client")
    assert client.app.state.runtime_paths.config_dir == config_dir
    directory = client.app.state.user_directory
    for name, role in (("ops", "deployer"), ("rita", "approver"), ("sam", "second_approver")):
        directory.create_user(name, "correct-pw", "us-west", role)
    _login(client, "ops", "correct-pw")
    return client


@pytest.fixture
def enforcing(config_dir, request):
    return _deployment(config_dir, request, enforcing=True)


@pytest.fixture
def describing_only(config_dir, request):
    return _deployment(config_dir, request, enforcing=False)


def _digest(client):
    return client.get("/api/admin/ontology/descriptions").json()["digest"]


def _labels(client, changes, reason=None, preview=False):
    body = {"digest": _digest(client), "changes": changes, "reason": reason}
    if preview:
        return client.post("/api/admin/ontology/labels/preview", headers=_csrf_headers(client), json=body)
    return client.put("/api/admin/ontology/labels", headers=_csrf_headers(client), json=body)


def _as(client, name):
    client.cookies.clear()
    _login(client, name, "correct-pw")


EMAIL_OFF = [{"object_type": "Customer", "field": "email", "labels": []}]
NAME_PII = [{"object_type": "Customer", "field": "name", "labels": ["pii"]}]


class TestWhatItReads:
    def test_each_field_says_its_labels_and_whether_they_decide_access(self, enforcing):
        body = enforcing.get("/api/admin/ontology/descriptions").json()

        assert body["types"]["Customer"]["fields"]["email"]["labels"] == ["pii"]
        assert body["types"]["Customer"]["fields"]["name"]["labels"] == []
        assert body["label_enforcement"] is True


class TestWhenLabelsDecideNothing:
    def test_every_change_applies_at_once(self, describing_only, config_dir):
        response = _labels(describing_only, EMAIL_OFF)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "applied"
        assert "classification" not in yaml.safe_load((config_dir / FILE).read_text())[
            "object_types"]["Customer"]["fields"]["email"]

    def test_the_preview_says_so(self, describing_only):
        preview = _labels(describing_only, EMAIL_OFF, preview=True).json()

        assert preview == {**preview, "needs_approval": False, "label_enforcement": False}
        assert preview["impact"]["roles"] == []


class TestWhenLabelsDecideAccess:
    def test_removing_a_label_opens_the_field_and_waits(self, enforcing, config_dir):
        before = (config_dir / FILE).read_text()

        preview = _labels(enforcing, EMAIL_OFF, preview=True).json()
        response = _labels(enforcing, EMAIL_OFF, reason="email is not personal here")

        assert preview["needs_approval"] is True
        # customer_service holds read:Customer.email; pii demoted it.
        gained = {(r["role"], f["field"]) for r in preview["impact"]["roles"] for f in r["fields_gained"]}
        assert ("customer_service", "email") in gained
        assert response.json()["status"] == "waiting"
        assert (config_dir / FILE).read_text() == before

    def test_adding_a_label_can_open_a_field_too(self, enforcing):
        """labelled_reader holds read:label:pii and no field by name: a
        field newly labelled pii becomes readable to it. A rule keyed on
        "was a label removed" would let this through."""
        preview = _labels(enforcing, NAME_PII, preview=True).json()

        gained = {(r["role"], f["field"]) for r in preview["impact"]["roles"] for f in r["fields_gained"]}
        assert ("labelled_reader", "name") in gained
        assert preview["needs_approval"] is True

    def test_a_label_that_only_closes_applies_at_once(self, enforcing):
        """Taking labelled_reader out of the picture, pii on name only
        demotes roles that read name without the label."""
        enforcing.cookies.clear()
        _roles_without_reader(enforcing)
        _login(enforcing, "ops", "correct-pw")

        preview = _labels(enforcing, NAME_PII, preview=True).json()
        response = _labels(enforcing, NAME_PII)

        assert preview["impact"]["widens"] is False and preview["impact"]["roles"]
        assert response.json()["status"] == "applied"

    def test_a_widening_without_a_reason_is_refused(self, enforcing, config_dir):
        response = _labels(enforcing, EMAIL_OFF)

        assert response.status_code == 400
        assert "Say why" in response.json()["detail"]


def _roles_without_reader(client):
    """Drops labelled_reader from the files and reloads, as an operator
    would."""
    config_dir = client.app.state.runtime_paths.config_dir
    path = config_dir / "policy.yaml"
    policy = yaml.safe_load(path.read_text())
    del policy["roles"]["labelled_reader"]
    path.write_text(yaml.safe_dump(policy, sort_keys=False))
    from api.reload import reload_generation

    reload_generation(client.app, requested_by="test")


class TestTheSecondPerson:
    def _waiting(self, client):
        assert _labels(client, EMAIL_OFF, reason="not personal here").json()["status"] == "waiting"
        _as(client, "rita")
        [proposal] = client.get("/api/admin/config-proposals").json()["proposals"]
        return proposal

    def test_the_approver_sees_what_why_and_what_it_does(self, enforcing):
        proposal = self._waiting(enforcing)

        assert proposal["reason"] == "not personal here"
        assert proposal["summary"] == "Customer.email: pii → none"
        assert proposal["impact"]["widens"] is True
        assert proposal["stale"] is False
        assert any(line.startswith("-") and "classification: pii" in line for line in proposal["diff"])

    def test_approving_writes_it_and_reloads(self, enforcing, config_dir):
        proposal = self._waiting(enforcing)
        before = enforcing.app.state.generation.generation

        response = enforcing.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/approve",
                                  headers=_csrf_headers(enforcing))

        assert response.status_code == 200, response.text
        assert enforcing.app.state.generation.generation > before
        assert "classification" not in yaml.safe_load((config_dir / FILE).read_text())[
            "object_types"]["Customer"]["fields"]["email"]
        assert enforcing.get("/api/admin/config-proposals").json()["proposals"] == []

    def test_the_proposer_cannot_approve_their_own(self, enforcing, config_dir):
        """ops holds manage:deployment; given manage:roles too, they are
        still the proposer."""
        _roles(config_dir, deployer=["manage:deployment", "manage:roles"])
        from api.reload import reload_generation

        reload_generation(enforcing.app, requested_by="test")
        assert _labels(enforcing, EMAIL_OFF, reason="x").json()["status"] == "waiting"
        [proposal] = enforcing.get("/api/admin/config-proposals").json()["proposals"]

        response = enforcing.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/approve",
                                  headers=_csrf_headers(enforcing))

        assert response.status_code == 409
        assert "someone else" in response.json()["detail"]

    def test_a_deployment_manager_cannot_approve(self, enforcing):
        assert _labels(enforcing, EMAIL_OFF, reason="x").json()["status"] == "waiting"
        _as(enforcing, "rita")
        [proposal] = enforcing.get("/api/admin/config-proposals").json()["proposals"]
        _as(enforcing, "ops")

        response = enforcing.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/approve",
                                  headers=_csrf_headers(enforcing))

        assert response.status_code == 403

    def test_a_file_changed_since_is_stale_not_merged(self, enforcing, config_dir):
        proposal = self._waiting(enforcing)
        path = config_dir / FILE
        path.write_text(path.read_text() + "\n# an operator's hand edit\n")

        listed = enforcing.get("/api/admin/config-proposals").json()["proposals"][0]
        response = enforcing.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/approve",
                                  headers=_csrf_headers(enforcing))

        assert listed["stale"] is True
        assert response.status_code == 409
        assert "an operator's hand edit" in path.read_text()
        assert "classification: pii" in path.read_text()

    def test_rejecting_and_withdrawing(self, enforcing):
        proposal = self._waiting(enforcing)

        assert enforcing.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/reject",
                              headers=_csrf_headers(enforcing)).json() == {"status": "rejected"}

        _as(enforcing, "ops")
        assert _labels(enforcing, EMAIL_OFF, reason="again").json()["status"] == "waiting"
        [mine] = enforcing.get("/api/admin/config-proposals").json()["proposals"]
        assert enforcing.post(f"/api/admin/config-proposals/{mine['proposal_id']}/reject",
                              headers=_csrf_headers(enforcing)).json() == {"status": "withdrawn"}

    def test_only_role_managers_reject_someone_elses(self, enforcing, config_dir):
        """A second deployment manager may see the queue, not decide it."""
        _roles(config_dir, other_deployer=["manage:deployment"])
        from api.reload import reload_generation

        reload_generation(enforcing.app, requested_by="test")
        enforcing.app.state.user_directory.create_user("olly", "correct-pw", "us-west", "other_deployer")
        assert _labels(enforcing, EMAIL_OFF, reason="x").json()["status"] == "waiting"
        [proposal] = enforcing.get("/api/admin/config-proposals").json()["proposals"]
        _as(enforcing, "olly")

        response = enforcing.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/reject",
                                  headers=_csrf_headers(enforcing))

        assert response.status_code == 403

    def test_it_is_audited_when_proposed_and_when_applied(self, enforcing):
        proposal = self._waiting(enforcing)
        enforcing.post(f"/api/admin/config-proposals/{proposal['proposal_id']}/approve",
                       headers=_csrf_headers(enforcing))

        entries = [e for e in read_audit_log(enforcing.app.state.runtime_paths.log_dir)
                   if e.get("stage") == "config_edit" and e.get("file") == FILE]
        assert [e["outcome"] for e in entries][-2:] == ["proposed", "applied"]
        assert entries[-2]["user_id"] == "ops" and entries[-1]["user_id"] == "rita"


class TestRefusals:
    def test_a_label_that_is_not_one(self, enforcing):
        response = _labels(enforcing, [{"object_type": "Customer", "field": "name", "labels": ["PII"]}])

        assert response.status_code == 400
        assert "not a label" in response.json()["detail"]

    def test_removing_the_last_field_a_grant_names_would_not_load(self, enforcing, config_dir):
        """labelled_reader's read:label:pii names pii; taking it off both
        fields that carry it leaves a grant naming nothing -- the loader
        refuses that, and the preview says so before anything is saved."""
        before = (config_dir / FILE).read_text()

        response = _labels(enforcing, [*EMAIL_OFF, {"object_type": "Customer", "field": "risk_score",
                                                     "labels": []}], preview=True)

        assert response.status_code == 400
        assert "would not load" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before
