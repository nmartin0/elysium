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
from core.ontology.bindings import split_bindings
from core.ontology.write_log import WriteLogWriter
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
        monkeypatch.setattr("core.config_editing.apply_removal", lambda *given: (broken, None))

        response = _remove(remover)

        assert response.status_code == 409 and "unable to load" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_if_the_permission_code_says_it_would_widen_access_nothing_is_written(
            self, remover, config_dir, monkeypatch):
        _deprecate(remover)
        before = (config_dir / FILE).read_text()
        monkeypatch.setattr("api.routes._access_impact", lambda request, replacements: (None, {"widens": True}))

        response = _remove(remover)

        assert response.status_code == 409 and "read more" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_a_field_a_link_made_is_refused_with_the_way_out(self, remover):
        response = _remove(remover, {"kind": "field", "object_type": "Customer", "field": "tags"})

        assert response.status_code == 400 and "removing the link type" in response.json()["detail"]

    def test_a_type_is_not_removed_here(self, remover):
        response = _remove(remover, {"kind": "type", "object_type": "Tag"})

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
        from api.routes import _blocked_answer, _Removal

        plan = _Removal(files={}, deprecated=True, remove_after=None, blockers=[], hidden=2, stored_data=[],
                        what="Account.currency", audited_as="Account.currency")

        answer = _blocked_answer(plan)

        assert answer is not None and answer.status_code == 409
        plan.hidden = 0
        assert _blocked_answer(plan) is None


class TestWhenOnlyWhatTheyCannotSeeBlocksIt:
    """The route's own handling of a removal that nothing visible blocks and
    something hidden does -- with the blockers stubbed, since which row is
    hidden is the other class's business."""

    @pytest.fixture
    def only_hidden(self, remover, monkeypatch):
        from core.ontology.used_by import Referrer

        _deprecate(remover)
        monkeypatch.setattr("core.ontology.removal.field_blockers", lambda *given: [
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

        monkeypatch.setattr("api.routes.reload_generation", failing)

        response = _remove(remover)

        assert response.status_code == 409 and "unable to load" in response.json()["detail"]
        assert "secret_role" not in response.text and "Hidden" not in response.text
        assert (config_dir / FILE).read_text() == before


class TestWhoMay:
    def test_only_a_manager_of_the_deployment(self, remover):
        remover.cookies.clear()
        remover.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(remover, "pat", "correct-pw")

        for preview in (True, False):
            response = _remove(remover, digest="x", preview=preview)
            assert response.status_code == 403 and response.json() == {"detail": "Needs manage:deployment"}


# ---------------------------------------------------------------------------
# What the removal leaves behind in stored data, against a REAL SYNC.
# ---------------------------------------------------------------------------

@pytest.fixture
def lake(tmp_path, monkeypatch, request):
    """A deployment with its source databases built and its gold published,
    Transaction.currency (nothing names it once its grants are out) the
    field that will go. `ingest_undeclared_columns` comes from the test."""
    from core.deployment_loader import RuntimePaths

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
    from scripts.run_sync import run_sync

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert run_sync(paths) == 0


def _tables(paths):
    from core.mirror.catalog import open_mirror_catalog

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
    from api.app import create_app

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
        from scripts.run_sync import run_sync

        _remove_currency_and_sync_again(lake)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert run_sync(lake, rebuild={"primary_sql.transactions"}) == 0

        assert "currency" not in [f.name for f in _tables(lake)["silver"].schema().fields]

    def test_nothing_serves_it_from_the_moment_it_applies_before_any_sync(self, lake):
        from api.app import create_app

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
