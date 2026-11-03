"""Removing a stored field or a link type from the UI (the removal design,
agreed 28 October), over HTTP against a COPY of the fixture configuration --
these tests write the files.

The rules under test: the sequence is deprecate, wait, remove, so only a
deprecated name goes; it is refused while anything names it, and the reply
says what (judged again on apply, not trusted from the preview); a link
follows its types; a binding goes with its field; a name a person cannot
discover answers as one that does not exist; and only a manager of the
deployment may.

WHAT THE REMOVAL LEAVES BEHIND IN STORED DATA is the last class here, run
against a real sync: the dialog's sentences about bronze, silver and gold
are pinned by what those layers hold afterwards.
"""

import contextlib
import io
import shutil
import sqlite3

import pytest
import yaml
from fastapi.testclient import TestClient

import tests.integration.conftest as integration_conftest
from elysium.core.ontology.bindings import split_bindings
from elysium.core.ontology.write_log import WriteLogWriter
from tests.conftest import read_audit_log, with_roles
from tests.integration import test_editing_config_from_the_ui as editing
from tests.integration.test_api import _csrf_headers, _login

config_dir = editing.config_dir
FILE = "ontology_schema.yaml"
BINDINGS = "source_bindings.yaml"

#: Nothing names Account.currency (test_used_by_from_the_ui says so), so it
#: can go as the fixture stands; the tags link needs its grants taken out.
FIELD = {"kind": "field", "object_type": "Account", "field": "currency"}
LINK = {"kind": "link", "link": "CustomerTags"}

def _without_grants_naming(policy, *names):
    for role in policy["roles"].values():
        role["allowed_actions"] = [grant for grant in role["allowed_actions"]
                                   if grant.partition(":")[2] not in names]


def _prepared(config_dir):
    """The copy of the configuration with a role that manages the
    deployment and holds NO grant on any name (a grant naming a field is
    what blocks its removal, so a manager who needed one to remove it could
    never), and the tags link's grants taken out. In the FILE, not in memory:
    every applied edit reloads from disk and would wipe a role added to the
    running copy."""
    policy = yaml.safe_load((config_dir / "policy.yaml").read_text())
    _without_grants_naming(policy, "Customer.tags", "Tag.customers")
    policy["roles"]["remover"] = {"allowed_actions": ["manage:deployment"]}
    (config_dir / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))


def _login_as(client, name, role):
    client.cookies.clear()
    with contextlib.suppress(ValueError):
        client.app.state.user_directory.create_user(name, "correct-pw", "us-west", role)
    _login(client, name, "correct-pw")


@pytest.fixture
def remover(config_dir, request):
    _prepared(config_dir)
    client = request.getfixturevalue("client")
    assert client.app.state.runtime_paths.config_dir == config_dir
    _login_as(client, "ops", "remover")
    return client


@pytest.fixture
def two_files(config_dir, request):
    """The same deployment with its bindings in source_bindings.yaml, Account.currency bound."""
    _prepared(config_dir)
    schema = yaml.safe_load((config_dir / FILE).read_text())
    declaration, bindings = split_bindings(schema["object_types"])
    bindings["Account"].setdefault("fields", {})["currency"] = {"column": "currency"}
    (config_dir / FILE).write_text(yaml.safe_dump({**schema, "object_types": declaration}, sort_keys=False))
    (config_dir / BINDINGS).write_text(yaml.safe_dump({"object_types": bindings}, sort_keys=False))
    client = request.getfixturevalue("client")
    _login_as(client, "ops", "remover")
    return client


def _digest(client):
    return client.get("/api/admin/ontology/descriptions").json()["digest"]


def _deprecate(client, what=FIELD, **given):
    response = client.put("/api/admin/ontology/status", headers=_csrf_headers(client),
                          json={"digest": _digest(client), "status": "deprecated", "reason": "Not used any more.",
                                **what, **given})
    assert response.status_code == 200, response.text


def _remove(client, what=FIELD, preview=False, **given):
    body = {**what, "digest": given.pop("digest", None) or _digest(client), **given}
    send = client.post if preview else client.put
    return send("/api/admin/ontology/removal" + ("/preview" if preview else ""),
                headers=_csrf_headers(client), json=body)


def _file(config_dir, name=FILE):
    return yaml.safe_load((config_dir / name).read_text())


def _generation(client):
    return client.app.state.generation.generation


class TestRemoving:
    def test_a_deprecated_field_nothing_names_is_deleted_and_the_deployment_reloaded(self, remover, config_dir):
        _deprecate(remover)
        before = _generation(remover)

        response = _remove(remover)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "applied" and response.json()["to_generation"] == before + 1
        fields = _file(config_dir)["object_types"]["Account"]["fields"]
        assert "currency" not in fields and "balance" in fields
        assert "currency" not in remover.app.state.generation.config.schema["Account"]["fields"]

    def test_nothing_else_in_the_file_changes(self, remover, config_dir):
        _deprecate(remover)
        was = _file(config_dir)

        _remove(remover)

        del was["object_types"]["Account"]["fields"]["currency"]
        assert _file(config_dir) == was

    def test_a_deprecated_link_type_goes_with_both_of_its_ends(self, remover, config_dir):
        _deprecate(remover, LINK)

        response = _remove(remover, LINK)

        assert response.status_code == 200, response.text
        assert "CustomerTags" not in _file(config_dir)["link_types"]
        assert "CustomerTransactions" in _file(config_dir)["link_types"]
        schema = remover.app.state.generation.config.schema
        assert "tags" not in schema["Customer"]["fields"] and "customers" not in schema["Tag"]["fields"]

    def test_a_link_follows_its_types_so_a_deprecated_type_lets_it_go_without_a_status_of_its_own(
            self, remover, config_dir):
        _deprecate(remover, {"kind": "type", "object_type": "Tag"})
        assert "status" not in _file(config_dir)["link_types"]["CustomerTags"]

        response = _remove(remover, LINK)

        assert response.status_code == 200, response.text
        assert "CustomerTags" not in _file(config_dir)["link_types"]

    def test_the_change_is_audited_under_the_name_removed(self, remover):
        _deprecate(remover)
        _remove(remover)

        entries = [e for e in read_audit_log(remover.app.state.runtime_paths.log_dir)
                   if e.get("stage") == "config_edit" and e.get("file") == FILE]
        assert entries[-1]["outcome"] == "applied" and entries[-1]["user_id"] == "ops"
        assert entries[-1]["changes"] == {"Account.currency": "removed"}

    def test_a_stale_view_is_refused_and_nothing_is_removed(self, remover, config_dir):
        _deprecate(remover)
        digest = _digest(remover)
        path = config_dir / FILE
        path.write_text(path.read_text() + "\n# an operator was here\n")

        assert _remove(remover, digest=digest).status_code == 409
        assert "currency" in _file(config_dir)["object_types"]["Account"]["fields"]

    def test_the_loader_has_the_last_word(self, remover, config_dir, monkeypatch):
        _deprecate(remover)
        before = (config_dir / FILE).read_text()
        broken = before.replace("  Customer:\n", "  Customer:\n    not_a_known_key_at_all: [\n", 1)
        monkeypatch.setattr("elysium.core.config_editing.apply_removal", lambda *given: (broken, None))

        response = _remove(remover)

        assert response.status_code == 409 and "unable to load" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_if_the_permission_code_says_it_would_widen_access_nothing_is_written(
            self, remover, config_dir, monkeypatch):
        _deprecate(remover)
        before = (config_dir / FILE).read_text()
        monkeypatch.setattr("elysium.api.routes._access_impact", lambda request, replacements: (None, {"widens": True}))

        response = _remove(remover)

        assert response.status_code == 409 and "read more" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_a_field_a_link_made_is_refused_with_the_way_out(self, remover):
        response = _remove(remover, {"kind": "field", "object_type": "Customer", "field": "tags"})

        assert response.status_code == 400 and "removing the link type" in response.json()["detail"]

    def test_a_type_is_named_by_its_name_alone(self, remover):
        response = _remove(remover, {"kind": "type", "object_type": "Tag", "field": "label"})

        assert response.status_code == 400


class TestItsBindingGoesWithIt:
    def test_the_binding_is_taken_out_of_source_bindings_too(self, two_files, config_dir):
        assert _file(config_dir, BINDINGS)["object_types"]["Account"]["fields"]["currency"] == {"column": "currency"}
        _deprecate(two_files)

        response = _remove(two_files)

        assert response.status_code == 200, response.text
        assert "fields" not in _file(config_dir, BINDINGS)["object_types"]["Account"]
        assert "currency" not in _file(config_dir)["object_types"]["Account"]["fields"]

    def test_the_preview_does_not_show_the_bindings_lines(self, two_files):
        _deprecate(two_files)

        diff = _remove(two_files, preview=True).json()["diff"]

        assert any("source_bindings.yaml changes too" in line for line in diff)
        assert not any("column: currency" in line for line in diff)


class TestOnlyWhatIsDeprecated:
    def test_an_active_field_is_refused_and_told_what_to_do_first(self, remover, config_dir):
        before = (config_dir / FILE).read_text()

        response = _remove(remover)

        assert response.status_code == 409
        assert "Deprecate it first" in response.json()["detail"] and response.json()["deprecated"] is False
        assert (config_dir / FILE).read_text() == before

    def test_the_preview_says_the_same_without_refusing(self, remover):
        preview = _remove(remover, preview=True)

        assert preview.status_code == 200
        assert preview.json()["can_remove"] is False and preview.json()["deprecated"] is False

    def test_a_link_nobody_deprecated_is_refused_too(self, remover):
        assert _remove(remover, LINK).status_code == 409

    def test_putting_it_back_to_active_makes_it_refused_again(self, remover):
        _deprecate(remover)
        remover.put("/api/admin/ontology/status", headers=_csrf_headers(remover),
                    json={"digest": _digest(remover), "status": "active", **FIELD})
        _login_as(remover, "ops", "remover")

        assert _remove(remover).status_code == 409

    def test_the_planned_date_is_passed_on_for_the_dialog(self, remover):
        _deprecate(remover, remove_after="2027-03-31")

        assert _remove(remover, preview=True).json()["remove_after"] == "2027-03-31"


class TestWhatBlocks:
    EMAIL = {"kind": "field", "object_type": "Customer", "field": "email"}

    def test_a_name_still_used_is_refused_with_what_uses_it(self, remover, config_dir):
        _deprecate(remover, self.EMAIL)
        before = (config_dir / FILE).read_text()

        response = _remove(remover, self.EMAIL)

        assert response.status_code == 409
        body = response.json()
        rows = {(row["kind"], row["place"]) for row in body["blockers"]}
        assert ("action", "action CreateCustomer") in rows and ("grant", "role customer_service") in rows
        assert body["hidden_blockers"] == 0
        assert (config_dir / FILE).read_text() == before

    def test_the_preview_lists_the_same_and_says_it_cannot_go(self, remover):
        _deprecate(remover, self.EMAIL)

        preview = _remove(remover, self.EMAIL, preview=True).json()

        assert preview["can_remove"] is False and preview["impact"] is None
        assert ("action", "action CreateCustomer") in {(row["kind"], row["place"]) for row in preview["blockers"]}
        assert "Saved views" in preview["not_listed"]

    def test_the_list_is_the_used_by_report_not_a_second_one(self, remover):
        _deprecate(remover, self.EMAIL)
        reported = remover.get("/api/admin/ontology/used-by",
                               params={"object_type": "Customer", "field": "email"}).json()["referrers"]

        shown = _remove(remover, self.EMAIL, preview=True).json()["blockers"]

        assert shown == reported

    def test_a_link_lists_what_names_either_end(self, remover):
        _deprecate(remover, {"kind": "link", "link": "CustomerAccounts"})

        preview = _remove(remover, {"kind": "link", "link": "CustomerAccounts"}, preview=True).json()

        assert ("security", "type Account, row rule") in {(row["kind"], row["place"]) for row in preview["blockers"]}

    def test_a_reference_made_after_the_preview_is_found_when_it_is_applied(self, remover, config_dir):
        _deprecate(remover)
        assert _remove(remover, preview=True).json()["can_remove"] is True
        policy = yaml.safe_load((config_dir / "policy.yaml").read_text())
        policy["roles"]["editor"]["allowed_actions"] += ["discover:Account", "read:Account.currency"]
        (config_dir / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))

        response = _remove(remover)

        assert response.status_code == 409, response.text
        assert ("grant", "role editor") in {(row["kind"], row["place"]) for row in response.json()["blockers"]}
        assert "currency" in _file(config_dir)["object_types"]["Account"]["fields"]

    def test_a_proposed_write_waiting_on_it_blocks_and_an_applied_one_does_not(self, remover):
        _deprecate(remover)
        log = WriteLogWriter(remover.app.state.runtime_paths.data_dir / "write_log.db")
        applied = log.log_pending_update("Account", "a1", {"currency": "EUR"}, {}, "ops", "set it")
        log.mark_applied(applied)

        preview = _remove(remover, preview=True).json()

        assert preview["can_remove"] is True
        assert any("1 edit(s) already applied" in line for line in preview["stored_data"])

        log.log_pending_update("Account", "a2", {"currency": "GBP"}, {}, "ops", "set it too")
        preview = _remove(remover, preview=True).json()

        assert preview["can_remove"] is False
        assert [(row["kind"], row["place"]) for row in preview["blockers"]] == [("pending write", "Account.currency")]
        assert _remove(remover).status_code == 409


class TestNothingIsLeakedToSomeoneWhoCannotDiscoverTheName:
    """A manager of the deployment reads every name in the declaration (the
    descriptions route says so), so the name asked about is not hidden from
    them. What would be NEW to them is what else names it: another type's
    row rule, a rule over a field they cannot discover. Those blockers are
    counted, not named, until they could find the name in Schema.

    ONE ANSWER for a name the deployment does not have, whoever asks and
    whatever the state of the file."""

    REGION = {"kind": "field", "object_type": "Customer", "field": "region"}

    def _as(self, client, *discovered):
        with_roles(client.app, narrow={"allowed_actions": frozenset(["manage:deployment", *discovered])})
        _login_as(client, "nar", "narrow")

    @pytest.mark.parametrize("what", [
        {"kind": "field", "object_type": "Account", "field": "nope"},
        {"kind": "field", "object_type": "Nobody", "field": "currency"},
        {"kind": "link", "link": "NoSuchLink"},
    ])
    def test_a_name_the_deployment_does_not_have_is_not_found_on_preview_and_apply(self, remover, what):
        for preview in (True, False):
            response = _remove(remover, what, preview=preview)
            assert response.status_code == 404, response.text
            assert response.json() == {"detail": "Not found"}

    def test_blockers_naming_what_they_cannot_discover_are_counted_not_named(self, remover):
        _deprecate(remover, self.REGION)
        digest = _digest(remover)
        self._as(remover)

        preview = _remove(remover, self.REGION, preview=True, digest=digest).json()

        shown = {(row["kind"], row["place"]) for row in preview["blockers"]}
        assert ("grant", "role customer_service") in shown and ("security", "type Customer, row rule") in shown
        assert ("action", "action CreateCustomer") in shown
        # Account, SupportTicket and Transaction each borrow the rule through it.
        assert preview["hidden_blockers"] == 3 and preview["can_remove"] is False
        text = str(preview["blockers"])
        assert not any(name in text for name in ("Account", "SupportTicket", "Transaction"))

    def test_the_names_they_can_discover_are_shown_and_only_those(self, remover):
        _deprecate(remover, self.REGION)
        digest = _digest(remover)
        self._as(remover, "discover:Account", "discover:SupportTicket")

        preview = _remove(remover, self.REGION, preview=True, digest=digest).json()

        shown = {row["place"] for row in preview["blockers"]}
        assert "Account row rule" in shown and "SupportTicket row rule" in shown
        assert "Transaction row rule" not in shown and preview["hidden_blockers"] == 1

    def test_the_apply_answers_with_the_same_filtered_blockers(self, remover):
        _deprecate(remover, self.REGION)
        digest = _digest(remover)
        self._as(remover)

        response = _remove(remover, self.REGION, digest=digest)

        assert response.status_code == 409
        assert response.json()["hidden_blockers"] == 3
        assert "Transaction" not in str(response.json())

    def test_a_removal_blocked_only_by_what_they_cannot_discover_still_cannot_go(self):
        # Nothing visible blocks it; the count alone must refuse, or the
        # filter would turn a block into a way round it.
        from elysium.api.routes import _blocked_answer, _Removal

        plan = _Removal(files={}, deprecated=True, remove_after=None, blockers=[], hidden=2, stored_data=[],
                        what="Account.currency", audited_as="Account.currency")

        answer = _blocked_answer(plan)

        assert answer is not None and answer.status_code == 409
        plan.hidden = 0
        assert _blocked_answer(plan) is None


class TestWhatASearchByMeaningReadsBlocksItsRemoval:
    @pytest.fixture
    def searched(self, config_dir, request):
        _prepared(config_dir)
        # Seen only by someone who may discover every name the row carries.
        policy = yaml.safe_load((config_dir / "policy.yaml").read_text())
        policy["roles"]["remover"]["allowed_actions"] += ["discover:SupportTicket", "discover:SupportTicket.subject"]
        (config_dir / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
        schema = yaml.safe_load((config_dir / FILE).read_text())
        schema["object_types"]["SupportTicket"]["semantic_search"] = {"from": ["subject", "status"]}
        (config_dir / FILE).write_text(yaml.safe_dump(schema, sort_keys=False))
        config = yaml.safe_load((config_dir / "config.yaml").read_text())
        config["llm"]["embedding_model"] = "nomic-embed-text"
        (config_dir / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
        client = request.getfixturevalue("client")
        _login_as(client, "ops", "remover")
        return client

    def test_the_blocker_is_shown_rather_than_a_generic_unloadable_409(self, searched, config_dir):
        what = {"kind": "field", "object_type": "SupportTicket", "field": "status"}
        _deprecate(searched, what)
        before = (config_dir / FILE).read_text()

        for response in (_remove(searched, what, preview=True), _remove(searched, what)):
            body = response.json()
            assert any(row["kind"] == "semantic_search" and "searched by meaning" in row["says"]
                       for row in body["blockers"]), body
        assert (config_dir / FILE).read_text() == before


class TestWhenOnlyWhatTheyCannotSeeBlocksIt:
    """The route's own handling of a removal that nothing visible blocks and
    something hidden does -- with the blockers stubbed, since which row is
    hidden is the other class's business."""

    @pytest.fixture
    def only_hidden(self, remover, monkeypatch):
        from elysium.core.ontology.used_by import Referrer

        _deprecate(remover)
        monkeypatch.setattr("elysium.core.ontology.removal.field_blockers", lambda *given: [
            Referrer("security", "Elsewhere row rule", "borrows its rule through here", ("Nowhere",))])
        return remover

    def test_the_preview_says_it_cannot_go_and_how_many_it_will_not_name(self, only_hidden):
        preview = _remove(only_hidden, preview=True).json()

        assert preview["can_remove"] is False and preview["blockers"] == [] and preview["hidden_blockers"] == 1
        assert preview["impact"] is None

    def test_the_apply_refuses_and_changes_nothing(self, only_hidden, config_dir):
        before = (config_dir / FILE).read_text()

        response = _remove(only_hidden)

        assert response.status_code == 409 and response.json()["hidden_blockers"] == 1
        assert "Elsewhere" not in str(response.json())
        assert (config_dir / FILE).read_text() == before


class TestWhenTheReloadFails:
    def test_the_old_file_is_put_back_and_the_reply_names_nothing_the_loader_said(
            self, remover, config_dir, monkeypatch):
        _deprecate(remover)
        before = (config_dir / FILE).read_text()

        def failing(*given, **asked):
            raise RuntimeError("Role 'secret_role': grant 'read:Hidden.thing' references an unknown field")

        monkeypatch.setattr("elysium.api.routes.reload_generation", failing)

        response = _remove(remover)

        assert response.status_code == 409 and "unable to load" in response.json()["detail"]
        assert "secret_role" not in response.text and "Hidden" not in response.text
        assert (config_dir / FILE).read_text() == before


class TestTheTwoFilesGoTogetherOrNotAtAll:
    """_write_config_files: the pair is staged, then renamed bindings-first
    (a binding for a field the ontology lacks stops the NEXT restart; a
    field without its binding loads), and a failure never leaves a half pair."""

    @staticmethod
    def _failing(monkeypatch, config_dir, fails):
        """Makes os.replace raise for the n-th rename onto a named file:
        `fails` is {filename: {n, ...}} (1 = its first rename). Returns the
        list of (filename, n) renames attempted, in order."""
        import os

        real, seen, attempted = os.replace, {}, []

        def replace(source, target, *given, **asked):
            name = target.name if hasattr(target, "name") else os.path.basename(target)
            seen[name] = seen.get(name, 0) + 1
            attempted.append((name, seen[name]))
            if seen[name] in fails.get(name, ()) and os.path.dirname(os.fspath(target)) == str(config_dir):
                raise OSError(28, "No space left on device")
            return real(source, target, *given, **asked)

        monkeypatch.setattr("elysium.api.routes.os.replace", replace)
        return attempted

    def _both_unchanged(self, config_dir, before):
        for name, text in before.items():
            assert (config_dir / name).read_text() == text
        assert [p.name for p in config_dir.iterdir() if "elysium-edit" in p.name] == []

    def _before(self, config_dir):
        return {FILE: (config_dir / FILE).read_text(), BINDINGS: (config_dir / BINDINGS).read_text()}

    def test_the_bindings_are_renamed_first(self, two_files, config_dir, monkeypatch):
        _deprecate(two_files)
        attempted = self._failing(monkeypatch, config_dir, {})

        assert _remove(two_files).status_code == 200

        assert [name for name, _ in attempted][:2] == [BINDINGS, FILE]

    def test_the_state_between_the_two_renames_is_one_the_loader_accepts(self, two_files, config_dir, tmp_path):
        """Bindings renamed, ontology not yet (a crash right there) loads;
        the other order would be 'binds field(s) ... does not declare'."""
        from elysium.core.deployment_loader import load_deployment

        _deprecate(two_files)
        old_ontology = (config_dir / FILE).read_text()
        assert _remove(two_files).status_code == 200
        half = tmp_path / "half"
        shutil.copytree(config_dir, half)
        (half / FILE).write_text(old_ontology)

        assert "currency" in load_deployment(half).schema["Account"]["fields"]

        wrong = tmp_path / "wrong"
        shutil.copytree(config_dir, wrong)
        (wrong / BINDINGS).write_text((half / BINDINGS).read_text().replace(
            "  Account:\n", "  Account:\n    fields:\n      currency: {column: x}\n", 1))
        (wrong / FILE).write_text((config_dir / FILE).read_text())
        with pytest.raises(ValueError, match="does not declare"):
            load_deployment(wrong)

    def test_a_failure_on_the_second_rename_puts_the_first_back_and_is_a_clean_error(
            self, two_files, config_dir, monkeypatch):
        _deprecate(two_files)
        before = self._before(config_dir)
        self._failing(monkeypatch, config_dir, {FILE: {1}})

        response = _remove(two_files)

        assert response.status_code == 500 and "Nothing was changed" in response.json()["detail"]
        assert "No space left" not in response.text
        self._both_unchanged(config_dir, before)

    def test_a_failure_staging_the_second_file_writes_neither(self, two_files, config_dir, monkeypatch):
        _deprecate(two_files)
        before = self._before(config_dir)
        real = type(config_dir).write_bytes

        # The routes stage the file's own bytes (api/routes._put_exact_text).
        def write_bytes(path, data):
            if path.name == f".{BINDINGS}.elysium-edit":
                raise OSError(28, "No space left on device")
            return real(path, data)

        monkeypatch.setattr(type(config_dir), "write_bytes", write_bytes)

        response = _remove(two_files)

        assert response.status_code == 500 and "Nothing was changed" in response.json()["detail"]
        monkeypatch.undo()
        self._both_unchanged(config_dir, before)

    def test_when_the_restore_fails_too_it_names_both_files_and_what_to_do(self, two_files, config_dir, monkeypatch):
        _deprecate(two_files)
        before = self._before(config_dir)
        self._failing(monkeypatch, config_dir, {FILE: {1}, BINDINGS: {2}})

        response = _remove(two_files)

        detail = response.json()["detail"]
        assert response.status_code == 500
        assert FILE in detail and BINDINGS in detail and "before you restart" in detail
        assert str(config_dir / BINDINGS) in detail and str(config_dir / FILE) in detail
        # The honest state: bindings changed, ontology not -- what the message says.
        assert (config_dir / FILE).read_text() == before[FILE]
        assert (config_dir / BINDINGS).read_text() != before[BINDINGS]

    def test_after_a_failed_reload_every_file_is_tried_even_when_one_restore_fails(
            self, two_files, config_dir, monkeypatch):
        _deprecate(two_files)
        before = self._before(config_dir)

        def failing(*given, **asked):
            raise RuntimeError("would not build")

        monkeypatch.setattr("elysium.api.routes.reload_generation", failing)
        # Renames: bindings 1, ontology 1 (apply); the undo goes ontology first
        # (its 2nd rename fails), and the bindings must still be put back.
        self._failing(monkeypatch, config_dir, {FILE: {2}})

        response = _remove(two_files)

        assert response.status_code == 500 and str(config_dir / FILE) in response.json()["detail"]
        assert (config_dir / BINDINGS).read_text() == before[BINDINGS]


class TestWhoMay:
    def test_only_a_manager_of_the_deployment(self, remover):
        remover.cookies.clear()
        remover.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(remover, "pat", "correct-pw")

        for preview in (True, False):
            response = _remove(remover, digest="x", preview=preview)
            assert response.status_code == 403 and response.json() == {"detail": "Needs manage:deployment"}


# ---------------------------------------------------------------------------
# Removing a whole object type.
# ---------------------------------------------------------------------------

TAG = {"kind": "type", "object_type": "Tag"}
TAGS_LINK = {"kind": "link", "link": "CustomerTags"}


def _without_grants_on_type(policy, *types):
    """Every grant that names these types or any of their fields."""
    for role in policy["roles"].values():
        role["allowed_actions"] = [grant for grant in role["allowed_actions"]
                                   if grant.partition(":")[2].partition(".")[0] not in types]


def _tag_prepared(config_dir, split=False):
    """Nothing grants on Tag or its link, so Tag can go once its link has;
    with `split`, the bindings are in source_bindings.yaml."""
    _prepared(config_dir)
    policy = yaml.safe_load((config_dir / "policy.yaml").read_text())
    _without_grants_on_type(policy, "Tag")
    (config_dir / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
    if split:
        schema = yaml.safe_load((config_dir / FILE).read_text())
        declaration, bindings = split_bindings(schema["object_types"])
        (config_dir / FILE).write_text(yaml.safe_dump({**schema, "object_types": declaration}, sort_keys=False))
        (config_dir / BINDINGS).write_text(yaml.safe_dump({"object_types": bindings}, sort_keys=False))


@pytest.fixture
def tag_remover(config_dir, request):
    _tag_prepared(config_dir)
    client = request.getfixturevalue("client")
    _login_as(client, "ops", "remover")
    return client


@pytest.fixture
def tag_two_files(config_dir, request):
    _tag_prepared(config_dir, split=True)
    client = request.getfixturevalue("client")
    _login_as(client, "ops", "remover")
    return client


def _ready_to_remove_tag(client):
    """Its link type removed first (a link names the type it joins), then Tag deprecated."""
    _deprecate(client, TAGS_LINK)
    assert _remove(client, TAGS_LINK).status_code == 200
    _deprecate(client, TAG)


class TestRemovingAType:
    def test_a_deprecated_type_nothing_names_is_deleted_and_the_deployment_reloaded(self, tag_remover, config_dir):
        _ready_to_remove_tag(tag_remover)
        before = _generation(tag_remover)

        response = _remove(tag_remover, TAG)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "applied" and response.json()["to_generation"] == before + 1
        types = _file(config_dir)["object_types"]
        assert "Tag" not in types and {"Customer", "Account", "Transaction", "SupportTicket"} <= set(types)
        assert "Tag" not in tag_remover.app.state.generation.config.schema

    def test_the_binding_goes_with_the_type_from_source_bindings(self, tag_two_files, config_dir):
        assert "Tag" in _file(config_dir, BINDINGS)["object_types"]
        _ready_to_remove_tag(tag_two_files)

        response = _remove(tag_two_files, TAG)

        assert response.status_code == 200, response.text
        assert "Tag" not in _file(config_dir, BINDINGS)["object_types"]
        assert "Tag" not in _file(config_dir)["object_types"]
        assert "Customer" in _file(config_dir, BINDINGS)["object_types"]

    def test_every_comment_line_in_the_file_survives_even_inside_the_type(self, config_dir, request):
        _tag_prepared(config_dir)
        path = config_dir / FILE
        path.write_text(path.read_text().replace("    title_field: label\n", "    title_field: label\n"
                                                 "    # a note inside Tag\n", 1))
        comments = [line for line in path.read_text().splitlines() if line.lstrip().startswith("#")]
        client = request.getfixturevalue("client")
        _login_as(client, "ops", "remover")
        _ready_to_remove_tag(client)

        assert _remove(client, TAG).status_code == 200

        kept = [line for line in path.read_text().splitlines() if line.lstrip().startswith("#")]
        assert "    # a note inside Tag" in kept
        assert set(comments) <= set(kept)

    def test_the_preview_shows_the_lines_that_go_and_the_honest_sentences_about_stored_data(self, tag_remover):
        _ready_to_remove_tag(tag_remover)

        preview = _remove(tag_remover, TAG, preview=True).json()

        assert preview["can_remove"] is True and preview["deprecated"] is True and preview["impact"] is not None
        assert any(line.startswith("-") and "tags" in line for line in preview["diff"])
        said = " ".join(preview["stored_data"])
        assert "keep the type's tables exactly as they were" in said and "Nothing is deleted from your source" in said
        assert "Nothing serves the type" in said

    def test_a_type_nobody_deprecated_is_refused_and_told_what_to_do_first(self, tag_remover, config_dir):
        _deprecate(tag_remover, TAGS_LINK)
        assert _remove(tag_remover, TAGS_LINK).status_code == 200
        before = (config_dir / FILE).read_text()

        for preview in (True, False):
            response = _remove(tag_remover, TAG, preview=preview)
            body = response.json()
            assert (body["can_remove"] is False and body["deprecated"] is False) if preview else (
                response.status_code == 409 and "not deprecated" in body["detail"])
        assert (config_dir / FILE).read_text() == before

    def test_a_stale_view_is_refused_and_nothing_is_removed(self, tag_remover, config_dir):
        _ready_to_remove_tag(tag_remover)
        digest = _digest(tag_remover)
        path = config_dir / FILE
        path.write_text(path.read_text() + "\n# an operator was here\n")

        assert _remove(tag_remover, TAG, digest=digest).status_code == 409
        assert "Tag" in _file(config_dir)["object_types"]

    @pytest.mark.parametrize("what", [{"kind": "type", "object_type": "Nobody"},
                                      {"kind": "type", "object_type": "tag"}])
    def test_an_unknown_name_is_not_found_on_preview_and_apply(self, tag_remover, what):
        for preview in (True, False):
            response = _remove(tag_remover, what, preview=preview)
            assert response.status_code == 404 and response.json() == {"detail": "Not found"}

    def test_the_loader_has_the_last_word(self, tag_remover, config_dir, monkeypatch):
        _ready_to_remove_tag(tag_remover)
        before = (config_dir / FILE).read_text()
        broken = before.replace("  Customer:\n", "  Customer:\n    not_a_known_key_at_all: [\n", 1)
        monkeypatch.setattr("elysium.core.config_editing.apply_removal", lambda *given: (broken, None))

        response = _remove(tag_remover, TAG)

        assert response.status_code == 409 and "unable to load" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_if_the_permission_code_says_it_would_widen_access_nothing_is_written(
            self, tag_remover, config_dir, monkeypatch):
        _ready_to_remove_tag(tag_remover)
        before = (config_dir / FILE).read_text()
        monkeypatch.setattr("elysium.api.routes._access_impact", lambda request, replacements: (None, {"widens": True}))

        response = _remove(tag_remover, TAG)

        assert response.status_code == 409 and "read more" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_a_failed_reload_puts_every_file_back(self, tag_two_files, config_dir, monkeypatch):
        _ready_to_remove_tag(tag_two_files)
        before = {FILE: (config_dir / FILE).read_text(), BINDINGS: (config_dir / BINDINGS).read_text()}

        def failing(*given, **asked):
            raise RuntimeError("Role 'secret_role' grants read:Hidden.thing")

        monkeypatch.setattr("elysium.api.routes.reload_generation", failing)

        response = _remove(tag_two_files, TAG)

        assert response.status_code == 409 and "secret_role" not in response.text
        assert {name: (config_dir / name).read_text() for name in before} == before

    def test_the_audit_log_says_removed(self, tag_remover):
        _ready_to_remove_tag(tag_remover)
        assert _remove(tag_remover, TAG).status_code == 200

        entries = [e for e in read_audit_log(tag_remover.app.state.runtime_paths.log_dir)
                   if e.get("stage") == "config_edit" and e.get("file") == FILE]
        assert entries[-1]["outcome"] == "applied" and entries[-1]["changes"] == {"Tag": "removed"}


class TestWhatBlocksATypeFromGoing:
    def _link_only(self, config_dir, request):
        """Tag deprecated, its link NOT removed, nothing else naming it."""
        _tag_prepared(config_dir)
        client = request.getfixturevalue("client")
        _login_as(client, "ops", "remover")
        _deprecate(client, TAG)
        return client

    def test_a_type_others_link_to_is_refused_on_preview_and_apply(self, config_dir, request):
        client = self._link_only(config_dir, request)

        for preview in (True, False):
            response = _remove(client, TAG, preview=preview)
            body = response.json()
            # The manager has no grant on Customer, so the link's other end is a name they may not
            # discover: the block is counted, and still refuses.
            assert body["hidden_blockers"] >= 1
            assert (body["can_remove"] is False) if preview else response.status_code == 409
        assert "Tag" in _file(config_dir)["object_types"]

    def test_the_link_is_shown_only_to_someone_who_can_discover_its_other_end(self, config_dir, request):
        client = self._link_only(config_dir, request)
        digest = _digest(client)
        with_roles(client.app, narrow={"allowed_actions": frozenset(["manage:deployment"])})
        _login_as(client, "nar", "narrow")

        hidden = _remove(client, TAG, preview=True, digest=digest).json()
        assert hidden["can_remove"] is False and hidden["hidden_blockers"] >= 1
        assert "CustomerTags" not in str(hidden["blockers"]) and "Customer" not in str(hidden["blockers"])
        assert _remove(client, TAG, digest=digest).json()["hidden_blockers"] >= 1

        with_roles(client.app, narrow={"allowed_actions": frozenset(
            ["manage:deployment", "discover:Customer", "discover:Customer.tags"])})
        shown = _remove(client, TAG, preview=True, digest=digest).json()
        assert "link CustomerTags" in {row["place"] for row in shown["blockers"]}
        assert shown["hidden_blockers"] == 0

    def test_a_grant_naming_the_type_or_one_of_its_fields_blocks_it(self, config_dir, request):
        _prepared(config_dir)
        client = request.getfixturevalue("client")
        _login_as(client, "ops", "remover")
        _deprecate(client, TAGS_LINK)
        assert _remove(client, TAGS_LINK).status_code == 200
        _deprecate(client, TAG)

        body = _remove(client, TAG, preview=True).json()

        assert body["can_remove"] is False
        assert ("grant", "role customer_service") in {(row["kind"], row["place"]) for row in body["blockers"]}

    def test_an_action_acting_on_it_blocks_it(self, config_dir, request):
        _prepared(config_dir)
        client = request.getfixturevalue("client")
        _login_as(client, "ops", "remover")
        _deprecate(client, {"kind": "type", "object_type": "Account"})

        body = _remove(client, {"kind": "type", "object_type": "Account"}, preview=True).json()

        assert ("action", "action TransferFunds") in {(row["kind"], row["place"]) for row in body["blockers"]}

    def test_the_list_is_the_used_by_report_plus_only_what_that_does_not_read(self, tag_remover):
        _deprecate(tag_remover, TAG)
        reported = tag_remover.get("/api/admin/ontology/used-by", params={"object_type": "Tag"}).json()["referrers"]

        preview = _remove(tag_remover, TAG, preview=True).json()

        assert reported and all(row in reported for row in preview["blockers"])
        assert len(preview["blockers"]) + preview["hidden_blockers"] == len(reported)

    def test_a_proposed_write_waiting_on_one_of_its_fields_blocks_and_an_applied_one_does_not(self, tag_remover):
        _ready_to_remove_tag(tag_remover)
        log = WriteLogWriter(tag_remover.app.state.runtime_paths.data_dir / "write_log.db")
        applied = log.log_pending_update("Tag", "t1", {"label": "a"}, {}, "ops", "set it")
        log.mark_applied(applied)

        preview = _remove(tag_remover, TAG, preview=True).json()

        assert preview["can_remove"] is True
        assert any("1 edit(s) already applied" in line for line in preview["stored_data"])

        log.log_pending_update("Tag", "t2", {"label": "b"}, {}, "ops", "set it too")
        preview = _remove(tag_remover, TAG, preview=True).json()

        assert preview["can_remove"] is False
        assert [(row["kind"], row["place"]) for row in preview["blockers"]] == [("pending write", "Tag.label")]
        assert _remove(tag_remover, TAG).status_code == 409

    def test_a_reference_made_after_the_preview_is_found_when_it_is_applied(self, tag_remover, config_dir):
        _ready_to_remove_tag(tag_remover)
        assert _remove(tag_remover, TAG, preview=True).json()["can_remove"] is True
        policy = yaml.safe_load((config_dir / "policy.yaml").read_text())
        policy["roles"]["debug"]["allowed_actions"].append("read:Tag")
        (config_dir / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))

        response = _remove(tag_remover, TAG)

        assert response.status_code == 409
        assert ("grant", "role debug") in {(row["kind"], row["place"]) for row in response.json()["blockers"]}
        assert "Tag" in _file(config_dir)["object_types"]


class TestASilosIncrementalDeclarationBlocksItsOnlyTable:
    def test_the_blocker_is_named_instead_of_a_generic_unloadable_409(self, config_dir, request):
        _tag_prepared(config_dir)
        silos = yaml.safe_load((config_dir / "data_silos.yaml").read_text())
        silos["data_silos"]["primary_sql"]["incremental"] = {"tags": {"cursor": "label"}}
        (config_dir / "data_silos.yaml").write_text(yaml.safe_dump(silos, sort_keys=False))
        client = request.getfixturevalue("client")
        _login_as(client, "ops", "remover")
        _ready_to_remove_tag(client)

        for preview in (True, False):
            body = _remove(client, TAG, preview=preview)
            body = body.json() if preview else (body.status_code, body.json())[1]
            assert ("silo", "data silo primary_sql, incremental") in {
                (row["kind"], row["place"]) for row in body["blockers"]}
        assert "Tag" in _file(config_dir)["object_types"]


class TestATypeIsRemovedWithItsBindingOrNotAtAll:
    def test_the_ontology_is_renamed_first_for_a_type(self, tag_two_files, config_dir, monkeypatch):
        _ready_to_remove_tag(tag_two_files)
        attempted = TestTheTwoFilesGoTogetherOrNotAtAll._failing(monkeypatch, config_dir, {})

        assert _remove(tag_two_files, TAG).status_code == 200

        assert [name for name, _ in attempted][:2] == [FILE, BINDINGS]

    def test_neither_half_state_loads_so_the_order_is_chosen_for_the_message_a_person_can_finish(
            self, tag_two_files, config_dir, tmp_path):
        """MEASURED, and the reason a type is not ordered like a field: with
        either file renamed alone the loader refuses. Ontology-first says the
        bindings bind a type it does not declare -- finish by deleting that
        entry; bindings-first says the type has no binding -- harder to mend."""
        from elysium.core.deployment_loader import load_deployment

        _ready_to_remove_tag(tag_two_files)
        old_ontology, old_bindings = (config_dir / FILE).read_text(), (config_dir / BINDINGS).read_text()
        assert _remove(tag_two_files, TAG).status_code == 200
        new_ontology, new_bindings = (config_dir / FILE).read_text(), (config_dir / BINDINGS).read_text()

        for name, ontology, bindings, message in (
                ("ontology_first", new_ontology, old_bindings, "binds object type"),
                ("bindings_first", old_ontology, new_bindings, "no source binding")):
            half = tmp_path / name
            shutil.copytree(config_dir, half)
            (half / FILE).write_text(ontology)
            (half / BINDINGS).write_text(bindings)
            with pytest.raises(ValueError, match=message):
                load_deployment(half)

    def test_a_failure_on_the_second_rename_puts_the_first_back(self, tag_two_files, config_dir, monkeypatch):
        _ready_to_remove_tag(tag_two_files)
        before = {FILE: (config_dir / FILE).read_text(), BINDINGS: (config_dir / BINDINGS).read_text()}
        TestTheTwoFilesGoTogetherOrNotAtAll._failing(monkeypatch, config_dir, {BINDINGS: {1}})

        response = _remove(tag_two_files, TAG)

        assert response.status_code == 500 and "Nothing was changed" in response.json()["detail"]
        assert {name: (config_dir / name).read_text() for name in before} == before
        assert [p.name for p in config_dir.iterdir() if "elysium-edit" in p.name] == []


class TestWhoMayRemoveAType:
    def test_only_a_manager_of_the_deployment(self, tag_remover):
        _ready_to_remove_tag(tag_remover)
        tag_remover.cookies.clear()
        tag_remover.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(tag_remover, "pat", "correct-pw")

        for preview in (True, False):
            response = _remove(tag_remover, TAG, preview=preview, digest="x")
            assert response.status_code == 403 and response.json() == {"detail": "Needs manage:deployment"}


# ---------------------------------------------------------------------------
# What the removal leaves behind in stored data, against a REAL SYNC.
# ---------------------------------------------------------------------------

@pytest.fixture
def lake(tmp_path, monkeypatch, request):
    """A deployment with its source databases built and its gold published,
    Transaction.currency (nothing names it once its grants are out) the
    field that will go. `ingest_undeclared_columns` comes from the test."""
    from elysium.core.deployment_loader import RuntimePaths

    monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
    config = tmp_path / "config"
    shutil.copytree(integration_conftest.FIXTURES_DIR, config)
    policy = yaml.safe_load((config / "policy.yaml").read_text())
    _without_grants_naming(policy, "Transaction.currency")
    policy["roles"]["remover"] = {"allowed_actions": ["manage:deployment"]}
    (config / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
    if getattr(request, "param", None) is not None:
        with (config / "config.yaml").open("a") as handle:
            handle.write(f"\ningest_undeclared_columns: {str(request.param).lower()}\n")
    data = tmp_path / "data"
    fixtures = data / "dev_fixtures"
    fixtures.mkdir(parents=True)
    for sql, db in (("schema.sql", "mediator.db"), ("support_schema.sql", "support.db"),
                    ("risk_schema.sql", "risk.db")):
        integration_conftest._build_sqlite_db(integration_conftest.FIXTURES_DIR / sql, fixtures / db)
    (tmp_path / "log").mkdir()
    return RuntimePaths(config_dir=config, data_dir=data, log_dir=tmp_path / "log")


def _sync(paths):
    from elysium.scripts.run_sync import run_sync

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert run_sync(paths) == 0


def _tables(paths):
    from elysium.core.mirror.catalog import open_mirror_catalog

    catalog = open_mirror_catalog(paths.data_dir / "mirror")
    return {layer: catalog.load_table(name) for layer, name in (
        ("bronze", "bronze_primary_sql.transactions"), ("silver", "primary_sql.transactions"),
        ("gold", "gold.Transaction"))}


def _currency(table, snapshot_id=None):
    scan = table.scan(snapshot_id=snapshot_id) if snapshot_id else table.scan()
    return scan.to_arrow().column("currency").to_pylist()


def _remove_currency_and_sync_again(paths):
    """Syncs, publishes gold twice (a source row changes between), removes
    Transaction.currency through the routes, syncs again. Returns the tables
    as they were before the removal and as they are after."""
    from elysium.api.app import create_app

    _sync(paths)
    with sqlite3.connect(paths.data_dir / "dev_fixtures" / "mediator.db") as source:
        source.execute("UPDATE transactions SET amount = amount + 1 "
                       "WHERE transaction_id = (SELECT min(transaction_id) FROM transactions)")
    _sync(paths)
    before = _tables(paths)
    snapshots = {layer: [s.snapshot_id for s in table.snapshots()] for layer, table in before.items()}
    tags_before = set(before["gold"].refs())

    client = TestClient(create_app(paths))
    with contextlib.suppress(ValueError):
        client.app.state.user_directory.create_user("ops", "correct-pw", "us-west", "remover")
    _login(client, "ops", "correct-pw")
    what = {"kind": "field", "object_type": "Transaction", "field": "currency"}
    _deprecate(client, what)
    assert _remove(client, what).status_code == 200
    _sync(paths)
    return before, snapshots, tags_before, _tables(paths)


class TestWhatHappensToStoredData:
    """Each sentence the dialog shows (core/ontology/removal.stored_data),
    as the layers hold it after a real sync -- so the words cannot drift
    from the code, which is what they describe."""

    def test_the_source_is_never_written(self, lake):
        _remove_currency_and_sync_again(lake)

        with sqlite3.connect(lake.data_dir / "dev_fixtures" / "mediator.db") as source:
            assert {row[0] for row in source.execute("SELECT currency FROM transactions")} == {"USD", "EUR"}

    def test_silver_keeps_the_column_empty_and_its_earlier_snapshots_hold_the_values(self, lake):
        before, snapshots, _tags, after = _remove_currency_and_sync_again(lake)

        assert "currency" in [f.name for f in after["silver"].schema().fields]
        assert set(_currency(after["silver"])) == {None}
        assert set(_currency(after["silver"], snapshots["silver"][-1])) == {"USD", "EUR"}
        assert set(_currency(before["silver"])) == {"USD", "EUR"}

    def test_gold_is_rebuilt_without_the_column_and_its_publication_tags_restart(self, lake):
        _before, _snapshots, tags_before, after = _remove_currency_and_sync_again(lake)

        assert "currency" not in [f.name for f in after["gold"].schema().fields]
        assert "published-2" in tags_before
        assert set(after["gold"].refs()) - {"main"} == {"published-1"}

    def test_bronze_keeps_the_raw_values_when_undeclared_columns_are_not_refused(self, lake):
        _before, _snapshots, _tags, after = _remove_currency_and_sync_again(lake)

        assert set(_currency(after["bronze"])) == {"USD", "EUR"}

    @pytest.mark.parametrize("lake", [False], indirect=True)
    def test_bronze_is_emptied_when_undeclared_columns_are_refused(self, lake):
        _before, snapshots, _tags, after = _remove_currency_and_sync_again(lake)

        assert set(_currency(after["bronze"])) == {None}
        assert set(_currency(after["bronze"], snapshots["bronze"][-1])) == {"USD", "EUR"}

    def test_a_silver_rebuild_drops_the_column_and_the_sync_after_it_succeeds(self, lake):
        from elysium.scripts.run_sync import run_sync

        _remove_currency_and_sync_again(lake)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert run_sync(lake, rebuild={"primary_sql.transactions"}) == 0

        assert "currency" not in [f.name for f in _tables(lake)["silver"].schema().fields]

    def test_nothing_serves_it_from_the_moment_it_applies_before_any_sync(self, lake):
        from elysium.api.app import create_app

        _sync(lake)
        client = TestClient(create_app(lake))
        client.app.state.user_directory.create_user("ops", "correct-pw", "us-west", "remover")
        _login(client, "ops", "correct-pw")
        what = {"kind": "field", "object_type": "Transaction", "field": "currency"}
        _deprecate(client, what)
        assert "currency" in client.app.state.generation.config.schema["Transaction"]["fields"]
        _remove(client, what)

        # Gold still holds the column (no sync has run); the configuration every read goes through
        # no longer has it.
        assert "currency" in [f.name for f in _tables(lake)["gold"].schema().fields]
        assert "currency" not in client.app.state.generation.config.schema["Transaction"]["fields"]


# ---------------------------------------------------------------------------
# Removing a whole TYPE, against a real sync.
# ---------------------------------------------------------------------------

TAG_TABLES = (("bronze", "bronze_primary_sql.tags"), ("silver", "primary_sql.tags"),
              ("gold", "gold.Tag"), ("history", "gold_history.Tag"),
              ("bronze_join", "bronze_primary_sql.customer_tags"), ("silver_join", "primary_sql.customer_tags"))


@pytest.fixture
def tag_lake(lake):
    """The lake with nothing granting on Tag or its link, so Tag can go once
    its link type has."""
    policy = yaml.safe_load((lake.config_dir / "policy.yaml").read_text())
    _without_grants_naming(policy, "Customer.tags")
    _without_grants_on_type(policy, "Tag")
    (lake.config_dir / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
    return lake


def _tag_layers(paths):
    from elysium.core.mirror.catalog import open_mirror_catalog

    catalog = open_mirror_catalog(paths.data_dir / "mirror")
    found = {}
    for layer, name in TAG_TABLES:
        try:
            found[layer] = catalog.load_table(name)
        except Exception:  # noqa: BLE001 - absent is an answer here
            found[layer] = None
    return found


def _remove_tag_and_sync_again(paths):
    from elysium.api.app import create_app

    _sync(paths)
    with sqlite3.connect(paths.data_dir / "dev_fixtures" / "mediator.db") as source:
        source.execute("UPDATE tags SET label = label || 'x' WHERE tag_id = (SELECT min(tag_id) FROM tags)")
    _sync(paths)
    before = _tag_layers(paths)
    client = TestClient(create_app(paths))
    client.app.state.user_directory.create_user("ops", "correct-pw", "us-west", "remover")
    _login(client, "ops", "correct-pw")
    for what in (TAGS_LINK, TAG):
        _deprecate(client, what)
        response = _remove(client, what)
        assert response.status_code == 200, response.text
    _sync(paths)
    return before, _tag_layers(paths), client


def _snapshots(tables):
    return {layer: ([s.snapshot_id for s in table.snapshots()], sorted(table.refs()))
            for layer, table in tables.items()}


class TestWhatHappensToStoredDataWhenATypeGoes:
    """Each sentence in removal._TYPE_TABLES, as a real sync leaves the lake."""

    def test_no_layer_loses_its_tables_or_gains_a_snapshot_and_gold_keeps_its_tags(self, tag_lake):
        before, after, _client = _remove_tag_and_sync_again(tag_lake)

        assert all(table is not None for table in after.values())
        assert _snapshots(after) == _snapshots(before)
        assert {"published-1", "published-2"} <= set(after["gold"].refs())
        assert after["history"].scan().to_arrow().num_rows == before["history"].scan().to_arrow().num_rows > 0

    def test_a_rebuild_of_its_silver_table_does_nothing(self, tag_lake):
        from elysium.scripts.run_sync import run_sync

        _before, after, _client = _remove_tag_and_sync_again(tag_lake)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert run_sync(tag_lake, rebuild={"primary_sql.tags"}) == 0

        assert _snapshots(_tag_layers(tag_lake)) == _snapshots(after)

    def test_the_source_is_never_written_and_other_types_keep_syncing(self, tag_lake):
        _before, _after, _client = _remove_tag_and_sync_again(tag_lake)
        with sqlite3.connect(tag_lake.data_dir / "dev_fixtures" / "mediator.db") as source:
            assert source.execute("SELECT count(*) FROM tags").fetchone()[0] == 2

        from elysium.core.mirror.catalog import open_mirror_catalog

        catalog = open_mirror_catalog(tag_lake.data_dir / "mirror")
        before_snapshots = len(catalog.load_table("gold.Transaction").snapshots())
        source = sqlite3.connect(tag_lake.data_dir / "dev_fixtures" / "mediator.db")
        with source:
            source.execute("UPDATE transactions SET amount = amount + 1")
        source.close()
        _sync(tag_lake)
        assert len(catalog.load_table("gold.Transaction").snapshots()) > before_snapshots

    def test_nothing_serves_the_type_from_the_moment_it_applies(self, tag_lake):
        _before, _after, client = _remove_tag_and_sync_again(tag_lake)

        assert "Tag" not in client.app.state.generation.config.schema
