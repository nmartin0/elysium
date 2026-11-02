"""Changing a field's data type from the UI (slice R1 of the retype design;
BLOCKING.md, "RETYPE, CHECKED AND SLICED"), over HTTP against a COPY of the
fixture configuration -- these tests write the files.

The rules under test: only a manager of the deployment may, and everyone
else gets the same denial whatever the name; a stale view is refused (409)
and nothing is written; the edit is one line and the deployment reloads, or
the old file is put back; a name that does not exist is "Not found"; what
names the field is shown as notes, never as blockers; the reply lists the
tables whose silver must now be rebuilt, found by comparing the declared
type with the lake; and the sync route takes only names that need it.

The last classes run a REAL SYNC before and after, so the sentences the
dialog shows (core/ontology/retype.stored_data) are pinned by what each layer
holds, and so is what the sync does about gold while silver is refused.
"""

import contextlib
import io
import json
import re
import shutil
import sqlite3

import pytest
import yaml
from fastapi.testclient import TestClient

from core.ontology.used_by import Referrer
from tests.conftest import read_audit_log, with_roles
from tests.integration import test_editing_config_from_the_ui as editing
from tests.integration.test_api import _csrf_headers, _login
from tests.integration.test_removal_from_the_ui import _digest, _file, _login_as, _prepared

config_dir = editing.config_dir

FILE = "ontology_schema.yaml"
AMOUNT = {"object_type": "Transaction", "field": "amount", "data_type": "decimal"}
SILVER = "primary_sql.transactions"


@pytest.fixture
def retyper(config_dir, request):
    """A manager of the deployment on a copy of the configuration (the
    removal tests' prepared one: a role holding manage:deployment and
    nothing else)."""
    _prepared(config_dir)
    client = request.getfixturevalue("client")
    assert client.app.state.runtime_paths.config_dir == config_dir
    _login_as(client, "ops", "remover")
    return client


def _retype(client, what=AMOUNT, preview=False, **given):
    body = {**what, "digest": given.pop("digest", None) or _digest(client), **given}
    send = client.post if preview else client.put
    return send("/api/admin/ontology/retype" + ("/preview" if preview else ""),
                headers=_csrf_headers(client), json=body)


class TestRetyping:
    def test_the_line_changes_the_deployment_reloads_and_nothing_else_does(self, retyper, config_dir):
        before = _generation(retyper)
        was = _file(config_dir)

        response = _retype(retyper)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "applied" and body["to_generation"] == before + 1
        was["object_types"]["Transaction"]["fields"]["amount"]["data_type"] = "decimal"
        assert _file(config_dir) == was
        assert retyper.app.state.generation.config.schema["Transaction"]["fields"]["amount"]["data_type"] == "decimal"
        assert any("decimal" in line for line in body["diff"])

    def test_the_preview_writes_nothing_and_says_what_changes(self, retyper, config_dir):
        text = (config_dir / FILE).read_text()

        preview = _retype(retyper, preview=True)

        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["from_type"] == "number" and body["to_type"] == "decimal"
        assert body["tables"] == [SILVER]
        assert any(line.startswith("+") and "decimal" in line for line in body["diff"])
        assert (config_dir / FILE).read_text() == text

    def test_a_field_with_no_data_type_is_a_string_and_gains_the_line(self, retyper, config_dir):
        what = {**AMOUNT, "field": "transaction_date", "data_type": "date"}

        assert _retype(retyper, what, preview=True).json()["from_type"] == "string"
        assert _retype(retyper, what).status_code == 200

        assert _file(config_dir)["object_types"]["Transaction"]["fields"]["transaction_date"]["data_type"] == "date"

    def test_the_change_is_audited_with_the_new_type(self, retyper):
        _retype(retyper)

        entries = [e for e in read_audit_log(retyper.app.state.runtime_paths.log_dir)
                   if e.get("stage") == "config_edit" and e.get("file") == FILE]
        assert entries[-1]["outcome"] == "applied" and entries[-1]["user_id"] == "ops"
        assert entries[-1]["changes"] == {"Transaction.amount.data_type": "decimal"}

    def test_the_reply_lists_the_silver_table_that_now_needs_a_rebuild(self, retyper):
        assert _retype(retyper).json()["rebuild"] == [SILVER]

    def test_the_reply_says_which_tables_are_this_fields_and_which_are_owed_overall(self, retyper):
        what = {**AMOUNT, "field": "transaction_date", "data_type": "date"}

        body = _retype(retyper, what).json()
        assert body["tables"] == [SILVER] and body["rebuild"] == [SILVER] and body["rebuild_unknown"] is False
        # A second field of another table: this field's tables are its own, the owed ones are all of them.
        other = {"object_type": "Account", "field": "currency", "data_type": "integer"}
        body = _retype(retyper, other).json()
        assert body["tables"] == ["primary_sql.accounts"]
        assert body["rebuild"] == ["primary_sql.accounts", SILVER]

    def test_a_mirror_that_cannot_be_read_does_not_fail_an_edit_that_has_landed(
            self, retyper, config_dir, broken_catalog):

        response = _retype(retyper)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "applied" and body["rebuild"] == [] and body["rebuild_unknown"] is True
        assert "data_type: decimal" in (config_dir / FILE).read_text()

    def test_the_preview_of_a_retype_still_answers_when_the_mirror_cannot_be_read(self, retyper, broken_catalog):

        response = _retype(retyper, preview=True)

        assert response.status_code == 200
        assert any("could not be read just now" in line for line in response.json()["stored_data"])

    def test_where_silver_was_never_built_there_is_nothing_to_rebuild(self, retyper):
        from core.mirror.catalog import open_mirror_catalog

        open_mirror_catalog(retyper.app.state.runtime_paths.data_dir / "mirror").drop_table(SILVER)

        assert _retype(retyper).json()["rebuild"] == []

    def test_a_field_no_table_is_read_for_the_type_changes_nothing_to_rebuild(self, retyper):
        """Account.currency is read from primary_sql.accounts; retyping
        it lists that table and no other."""
        what = {"object_type": "Account", "field": "currency", "data_type": "integer"}
        assert _retype(retyper, what, preview=True).json()["tables"] == ["primary_sql.accounts"]
        assert _retype(retyper, what).json()["rebuild"] == ["primary_sql.accounts"]

    def test_a_stale_view_is_refused_on_both_and_nothing_is_changed(self, retyper, config_dir):
        digest = _digest(retyper)
        path = config_dir / FILE
        path.write_text(path.read_text() + "\n# an operator was here\n")
        text = path.read_text()

        for preview in (True, False):
            response = _retype(retyper, preview=preview, digest=digest)
            assert response.status_code == 409 and "changed since you opened it" in response.json()["detail"]
        assert path.read_text() == text

    def test_the_loader_has_the_last_word(self, retyper, config_dir, monkeypatch):
        before = (config_dir / FILE).read_text()
        broken = before.replace("  Customer:\n", "  Customer:\n    not_a_known_key_at_all: [\n", 1)
        monkeypatch.setattr("core.config_editing.apply_retype", lambda *given: broken)

        for preview in (True, False):
            response = _retype(retyper, preview=preview)
            assert response.status_code == 400 and "would not load" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    def test_a_field_the_loader_refuses_in_its_new_type_is_refused_not_written(self, retyper, config_dir):
        """A timezone belongs to timestamptz alone (object_type_validation):
        the loader, not this edit, says so."""
        path = config_dir / FILE
        path.write_text(path.read_text().replace(
            "      transaction_date:\n        type: data\n",
            "      transaction_date:\n        type: data\n        data_type: timestamptz\n"
            "        timezone: Europe/Paris\n", 1))
        assert "timezone: Europe/Paris" in path.read_text()
        before = path.read_text()

        response = _retype(retyper, {**AMOUNT, "field": "transaction_date", "data_type": "date"})

        assert response.status_code == 400 and "timezone" in response.json()["detail"]
        assert path.read_text() == before

    def test_a_failed_reload_puts_the_old_file_back(self, retyper, config_dir, monkeypatch):
        before = (config_dir / FILE).read_text()

        def failing(*given, **asked):
            raise RuntimeError("the reload broke")

        monkeypatch.setattr("api.routes.reload_generation", failing)

        response = _retype(retyper)

        assert response.status_code == 400 and "would not reload" in response.json()["detail"]
        assert (config_dir / FILE).read_text() == before

    @pytest.mark.parametrize("given,status,says", [
        ({"data_type": "number"}, 400, "already number"),
        ({"data_type": "varchar"}, 400, "data type is one of"),
        ({"object_type": "Customer", "field": "customers", "data_type": "string"}, 404, "Not found"),
        ({"field": "nope"}, 404, "Not found"),
        ({"object_type": "Nobody"}, 404, "Not found"),
        ({"field": "customer_id", "data_type": "integer"}, 400, "A field that a link made"),
        ({"object_type": "Customer", "field": "region", "data_type": "integer"}, 400, "who may see each row"),
    ])
    def test_what_is_refused_and_how(self, retyper, config_dir, given, status, says):
        before = (config_dir / FILE).read_text()

        for preview in (True, False):
            response = _retype(retyper, {**AMOUNT, **given}, preview=preview)
            assert response.status_code == status and says in response.json()["detail"], response.text
        assert (config_dir / FILE).read_text() == before

    def test_the_identifier_is_not_a_field_of_the_running_schema_so_it_is_not_found(self, retyper):
        assert _retype(retyper, {**AMOUNT, "field": "transaction_id", "data_type": "string"}).status_code == 404

    def test_missing_parts_are_a_validation_error(self, retyper):
        response = retyper.put("/api/admin/ontology/retype", headers=_csrf_headers(retyper),
                               json={"digest": _digest(retyper), "object_type": "Transaction"})
        assert response.status_code == 422


class TestWhatNamesTheField:
    def test_the_places_are_the_used_by_report_as_notes_and_do_not_stop_it(self, retyper):
        from api import routes  # noqa: F401  (the report below is the Used by route's)

        used_by = retyper.get("/api/admin/ontology/used-by",
                              params={"object_type": "Transaction", "field": "amount"}).json()["referrers"]

        preview = _retype(retyper, preview=True).json()

        assert preview["places"] == used_by and len(used_by) >= 1
        assert preview["hidden_places"] == 0 and preview["not_listed"]
        assert _retype(retyper).status_code == 200

    def test_places_naming_what_the_person_cannot_discover_are_counted_not_named(self, retyper, monkeypatch):
        rows = [Referrer("grant", "role everyone", "names it", ()),
                Referrer("rule", "type Secret, row rule", "reads it", ("Secret.thing",))]
        monkeypatch.setattr("core.ontology.retype.places_naming", lambda *given: rows)
        with_roles(retyper.app, narrow={"allowed_actions": frozenset(["manage:deployment"])})
        _login_as(retyper, "nar", "narrow")

        preview = _retype(retyper, preview=True).json()

        assert [row["place"] for row in preview["places"]] == ["role everyone"]
        assert preview["hidden_places"] == 1 and "Secret" not in str(preview)
        # They are notes: a retype with hidden ones still applies.
        assert _retype(retyper).status_code == 200


class TestWhoMay:
    def test_only_a_manager_of_the_deployment_and_the_denial_is_the_same_for_every_name(self, retyper):
        retyper.cookies.clear()
        retyper.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(retyper, "pat", "correct-pw")

        for what in (AMOUNT, {**AMOUNT, "field": "nope"}, {**AMOUNT, "object_type": "Nobody"}):
            for preview in (True, False):
                response = _retype(retyper, what, preview=preview, digest="x")
                assert response.status_code == 403 and response.json() == {"detail": "Needs manage:deployment"}

    def test_nothing_is_written_for_someone_who_may_not(self, retyper, config_dir):
        text = (config_dir / FILE).read_text()
        retyper.cookies.clear()
        retyper.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(retyper, "pat", "correct-pw")

        _retype(retyper, digest=_digest_of(config_dir))

        assert (config_dir / FILE).read_text() == text


def _digest_of(config_dir):
    from core.config_editing import digest

    return digest((config_dir / FILE).read_text())


def _generation(client):
    return client.app.state.generation.generation


# ---------------------------------------------------------------------------
# The sync route's `rebuild`.
# ---------------------------------------------------------------------------

class _CapturedThread:
    started: list = []

    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        _CapturedThread.started.append(self._target)


@pytest.fixture
def captured(retyper):
    _CapturedThread.started = []
    retyper.app.state.sync_thread_factory = _CapturedThread
    return _CapturedThread


def _post_sync(client, **body):
    return client.post("/api/admin/mirror/sync", headers=_csrf_headers(client), **({"json": body} if body else {}))


@pytest.fixture
def broken_catalog(monkeypatch):
    """Any catalog error after the deployment has started (the loader itself
    refuses to START on a catalog whose metadata file is gone, so an edit
    cannot be applied to one; what is left is a catalog that fails when the
    routes read it later)."""
    def broken(request):
        raise RuntimeError("the catalog cannot be read")

    monkeypatch.setattr("api.routes._mirror_catalog_for", broken)


class TestSyncRebuildNames:
    @staticmethod
    def _run(target, monkeypatch):
        """What the thread the route started would call run_sync with."""
        import scripts.run_sync

        calls = []
        monkeypatch.setattr(scripts.run_sync, "run_sync", lambda *given, **asked: calls.append((given, asked)))
        target()
        return calls

    def test_with_no_body_it_is_the_sync_it_always_was(self, retyper, captured, monkeypatch):
        assert _post_sync(retyper).status_code == 200

        (target,) = captured.started
        assert self._run(target, monkeypatch) == [((), {})]

    def test_an_empty_list_is_the_same_as_no_body(self, retyper, captured, monkeypatch):
        assert _post_sync(retyper, rebuild=[]).status_code == 200

        (target,) = captured.started
        assert self._run(target, monkeypatch) == [((), {})]

    @pytest.mark.parametrize("name", [SILVER, "primary_sql.nope", "nonsense", ""])
    def test_a_name_that_needs_no_rebuild_is_refused_by_name_and_nothing_starts(self, retyper, captured, name):
        """Refuses names that merely EXIST (SILVER is a real table, here
        with nothing built or changed): a rebuild nobody needs destroys
        snapshot history for nothing."""
        response = _post_sync(retyper, rebuild=[name])

        assert response.status_code == 400 and name in response.json()["detail"]
        assert captured.started == []
        entries = read_audit_log(retyper.app.state.runtime_paths.log_dir)
        assert not [e for e in entries if e.get("action") in ("start", "rebuild")]
        (refusal,) = [e for e in entries if e.get("action") == "rebuild_refused"]
        assert refusal["object_id"] == [name] and refusal["user_id"] == "ops" and refusal["allowed"] is False

    def test_the_guard_comes_first_and_says_nothing_about_names(self, retyper, captured):
        retyper.cookies.clear()
        retyper.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(retyper, "pat", "correct-pw")

        response = _post_sync(retyper, rebuild=["nonsense"])

        assert response.status_code == 403 and "nonsense" not in response.text
        assert captured.started == []

    def test_the_names_reach_the_sync_and_no_names_start_it_as_it_always_ran(self, monkeypatch):
        from api.routes import _run_sync_in_background

        assert self._run(_run_sync_in_background, monkeypatch) == [((), {})]
        assert self._run(lambda: _run_sync_in_background({SILVER}), monkeypatch) == [((), {"rebuild": {SILVER}})]

    def test_the_route_hands_the_names_it_checked_to_the_thread(self, retyper, captured, monkeypatch):
        _retype(retyper)

        assert _post_sync(retyper, rebuild=[SILVER, SILVER]).status_code == 200

        (target,) = captured.started
        assert self._run(target, monkeypatch) == [((), {"rebuild": {SILVER}})]

    def test_a_rebuild_is_audited_as_allowed_and_so_is_the_start(self, retyper, captured):
        _retype(retyper)

        _post_sync(retyper, rebuild=[SILVER])

        entries = read_audit_log(retyper.app.state.runtime_paths.log_dir)
        (rebuild,) = [e for e in entries if e.get("action") == "rebuild"]
        (start,) = [e for e in entries if e.get("action") == "start"]
        assert rebuild["allowed"] is True and start["allowed"] is True and rebuild["object_id"] == [SILVER]

    def test_while_another_sync_holds_the_lock_the_rebuild_is_refused_and_not_dropped_silently(
            self, retyper, captured):
        from core.mirror.sync_lock import single_writer

        _retype(retyper)
        lock = retyper.app.state.runtime_paths.data_dir / "sync.lock"

        with single_writer(lock) as taken:
            assert taken
            response = _post_sync(retyper, rebuild=[SILVER])

        assert response.status_code == 409 and "the rebuild was not started" in response.json()["detail"]
        assert captured.started == []
        entries = read_audit_log(retyper.app.state.runtime_paths.log_dir)
        assert not [e for e in entries if e.get("action") == "rebuild"]
        assert [e for e in entries if e.get("action") == "rebuild_refused"]
        # Free again, the same request starts.
        assert _post_sync(retyper, rebuild=[SILVER]).status_code == 200

    def test_a_sync_with_no_names_is_not_held_back_by_the_lock_check(self, retyper, captured):
        from core.mirror.sync_lock import single_writer

        with single_writer(retyper.app.state.runtime_paths.data_dir / "sync.lock"):
            assert _post_sync(retyper).status_code == 200
        assert len(captured.started) == 1

    def test_a_mirror_that_cannot_be_read_is_a_clear_refusal_and_not_a_traceback(
            self, retyper, captured, broken_catalog):

        response = _post_sync(retyper, rebuild=[SILVER])

        assert response.status_code == 503 and "could not be read" in response.json()["detail"]
        assert "Traceback" not in response.text and captured.started == []
        assert [e for e in read_audit_log(retyper.app.state.runtime_paths.log_dir)
                if e.get("action") == "rebuild_refused"]

    def test_a_body_that_is_not_a_list_of_names_is_a_validation_error(self, retyper, captured):
        assert _post_sync(retyper, rebuild="primary_sql.transactions").status_code == 422
        assert captured.started == []


# ---------------------------------------------------------------------------
# Against a real sync.
# ---------------------------------------------------------------------------

def _layers(catalog):
    """Each layer's table (None when absent), as the lake holds them."""
    names = {"bronze": "bronze_primary_sql.transactions", "silver": SILVER, "gold": "gold.Transaction",
             "history": "gold_history.Transaction"}
    found = {}
    for layer, name in names.items():
        try:
            found[layer] = catalog.load_table(name)
        except Exception:  # noqa: BLE001 - absent is an answer here
            found[layer] = None
    return found


class _Lake:
    """What the layers held at one moment: snapshot ids, tags, the type of
    `amount`, and the history rows as stored."""

    def __init__(self, paths):
        from core.mirror.catalog import open_mirror_catalog

        tables = _layers(open_mirror_catalog(paths.data_dir / "mirror"))
        self.snapshots = {layer: [s.snapshot_id for s in table.snapshots()] if table else None
                          for layer, table in tables.items()}
        self.tags = sorted(set(tables["gold"].refs()) - {"main"}) if tables["gold"] else None
        self.types = {layer: str(tables[layer].schema().as_arrow().field("amount").type)
                      for layer in ("bronze", "silver", "gold")}
        self.history = sorted(json.dumps(row, sort_keys=True, default=str)
                              for row in tables["history"].scan().to_arrow().to_pylist())
        self.silver_amounts = sorted(float(v) for v in tables["silver"].scan().to_arrow().column("amount").to_pylist())
        self.gold_amounts = sorted(float(v) for v in tables["gold"].scan().to_arrow().column("amount").to_pylist())


class _Flow:
    """One run of the whole story, measured at each step: sync twice (so
    gold has published twice), retype, sync with silver refused, rebuild,
    change the source, sync again."""


@pytest.fixture(scope="class")
def flow(tmp_path_factory):
    from api.app import create_app
    from core.deployment_loader import RuntimePaths
    from scripts.run_sync import run_sync
    from tests.integration import conftest as integration_conftest

    tmp_path = tmp_path_factory.mktemp("retype")
    patch = pytest.MonkeyPatch()
    patch.setenv("ELYSIUM_COOKIE_SECURE", "false")
    config = tmp_path / "config"
    shutil.copytree(integration_conftest.FIXTURES_DIR, config)
    policy = yaml.safe_load((config / "policy.yaml").read_text())
    policy["roles"]["retyper"] = {"allowed_actions": ["manage:deployment"]}
    (config / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
    data = tmp_path / "data"
    fixtures = data / "dev_fixtures"
    fixtures.mkdir(parents=True)
    for sql, db in (("schema.sql", "mediator.db"), ("support_schema.sql", "support.db"),
                    ("risk_schema.sql", "risk.db")):
        integration_conftest._build_sqlite_db(integration_conftest.FIXTURES_DIR / sql, fixtures / db)
    (tmp_path / "log").mkdir()
    paths = RuntimePaths(config_dir=config, data_dir=data, log_dir=tmp_path / "log")

    def sync(**given):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            failures = run_sync(paths, **given)
        return failures, out.getvalue() + err.getvalue()

    def source(sql):
        with sqlite3.connect(fixtures / "mediator.db") as connection:
            connection.execute(sql)

    result = _Flow()
    result.paths = paths
    assert sync()[0] == 0
    source("UPDATE transactions SET amount = amount + 1 "
           "WHERE transaction_id = (SELECT min(transaction_id) FROM transactions)")
    assert sync()[0] == 0
    result.before = _Lake(paths)
    result.source_before = _source_rows(fixtures)

    client = TestClient(create_app(paths))
    client.app.state.user_directory.create_user("ops", "correct-pw", "us-west", "retyper")
    _login(client, "ops", "correct-pw")
    client.app.state.sync_thread_factory = _CapturedThread
    _CapturedThread.started = []
    result.client = client
    result.preview = _retype(client, preview=True).json()
    result.applied = _retype(client)
    result.rebuild = result.applied.json()["rebuild"]

    # Silver is refused: gold is the finding.
    result.refused_failures, result.refused_output = sync()
    result.refused = _Lake(paths)
    result.still_to_rebuild = _post_sync(client, rebuild=result.rebuild)
    result.thread = list(_CapturedThread.started)

    result.rebuilt_failures, _output = sync(rebuild=set(result.rebuild))
    result.rebuilt = _Lake(paths)
    result.after_rebuild_the_names_are_refused = _post_sync(client, rebuild=result.rebuild)
    result.left = _retype(client, preview=True, what={**AMOUNT, "data_type": "number"}).json()["tables"]

    source("UPDATE transactions SET amount = amount + 1 "
           "WHERE transaction_id = (SELECT min(transaction_id) FROM transactions)")
    assert sync()[0] == 0
    result.later = _Lake(paths)
    result.source_after = _source_rows(fixtures)
    result.audit = read_audit_log(paths.log_dir)
    yield result
    patch.undo()


def _source_rows(fixtures):
    with sqlite3.connect(fixtures / "mediator.db") as connection:
        return connection.execute("SELECT * FROM transactions ORDER BY transaction_id").fetchall()


class TestWhatHappensToStoredData:
    """Each sentence of core/ontology/retype.stored_data, as the layers hold
    it after a real sync."""

    def test_the_preview_names_the_table_and_the_reply_lists_it_to_rebuild(self, flow):
        assert flow.preview["tables"] == [SILVER]
        assert flow.applied.status_code == 200 and flow.rebuild == [SILVER]
        assert flow.before.types["silver"] == "double" and flow.before.types["gold"] == "double"

    def test_the_sentences_the_dialog_shows(self, flow):
        said = " ".join(flow.preview["stored_data"])
        for part in ("Nothing is deleted from your source", SILVER, "rebuilt from bronze",
                     "snapshot history is discarded", "Bronze is not touched", "publication tags",
                     "changelog and its history", "keep the values they had, in the old type",
                     "records no difference", "not counted yet"):
            assert part in said, part

    def test_the_source_is_never_written(self, flow):
        """The only change to the source is the one UPDATE this fixture ran
        itself (the first transaction's amount, plus one)."""
        before, after = flow.source_before, flow.source_after
        assert [row[0] for row in after] == [row[0] for row in before]
        changed = [(was, now) for was, now in zip(before, after, strict=True) if was != now]
        assert len(changed) == 1
        (was, now), = changed
        assert now[2] == was[2] + 1 and was[:2] + was[3:] == now[:2] + now[3:]

    def test_silver_is_refused_until_rebuilt_and_the_old_silver_stays_as_it_was(self, flow):
        assert flow.refused_failures == 1
        assert "no longer matches the mirror" in flow.refused_output
        assert f"--rebuild {SILVER}" in flow.refused_output
        assert flow.refused.snapshots["silver"] == flow.before.snapshots["silver"]
        assert flow.refused.types["silver"] == "double"

    def test_the_rebuild_is_still_owed_after_a_refused_sync_because_it_is_derived_not_remembered(self, flow):
        assert flow.still_to_rebuild.status_code == 200
        assert len(flow.thread) == 1 and flow.thread[0].args == ({SILVER},)

    def test_a_rebuild_makes_silver_the_new_type_with_a_history_of_its_own(self, flow):
        assert flow.rebuilt_failures == 0
        assert flow.rebuilt.types["silver"] == "decimal128(38, 9)"
        assert flow.rebuilt.snapshots["silver"] != flow.before.snapshots["silver"]
        assert not set(flow.rebuilt.snapshots["silver"]) & set(flow.before.snapshots["silver"])
        assert flow.rebuilt.silver_amounts == flow.before.silver_amounts

    def test_bronze_is_untouched(self, flow):
        assert flow.before.snapshots["bronze"] == flow.refused.snapshots["bronze"] == \
            flow.rebuilt.snapshots["bronze"]
        assert flow.rebuilt.types["bronze"] == flow.before.types["bronze"]

    def test_the_names_are_refused_once_rebuilt_and_nothing_is_left_to_rebuild(self, flow):
        assert flow.after_rebuild_the_names_are_refused.status_code == 400
        assert SILVER in flow.after_rebuild_the_names_are_refused.json()["detail"]

    def test_the_rebuild_names_are_in_the_audit_log(self, flow):
        entries = [e for e in flow.audit if e.get("action") == "rebuild"]
        assert len(entries) == 1 and entries[0]["object_id"] == [SILVER] and entries[0]["user_id"] == "ops"

    def test_gold_is_rebuilt_and_its_publication_tags_restart(self, flow):
        assert flow.before.tags == ["published-1", "published-2"]
        assert flow.rebuilt.types["gold"] == "decimal128(38, 9)"
        assert flow.rebuilt.tags == ["published-1"]
        assert flow.rebuilt.gold_amounts == flow.before.gold_amounts

    def test_the_changelog_is_kept_with_old_entries_in_the_old_type_and_the_rebuild_records_no_diff(self, flow):
        assert flow.before.history  # the update between the first two syncs
        assert flow.rebuilt.history == flow.before.history
        assert flow.rebuilt.snapshots["history"] == flow.before.snapshots["history"]

    def test_history_goes_on_afterwards_and_the_old_entries_are_not_rewritten(self, flow):
        assert len(flow.later.history) == len(flow.before.history) + 1
        assert set(flow.before.history) <= set(flow.later.history)

    def test_an_old_entry_keeps_its_value_as_it_was_and_a_new_one_has_the_new_type(self, flow):
        def amount(entry):
            return json.loads(json.loads(entry)["values"])["amount"]

        (old,) = flow.before.history
        (new,) = set(flow.later.history) - set(flow.before.history)
        assert amount(old) == "50.99"
        assert amount(new) == "51.990000000"


class TestWhileSilverIsRefused:
    """THE GOLD FINDING (asked of slice R1, fixed by R2): once the YAML says
    the new type and silver is refused, the sync SKIPS gold of that type. It
    neither rebuilds it from the old-typed silver nor fails it: the type's
    gold keeps its rows, its column type, its tags and its changelog exactly
    as published."""

    def test_the_refused_sync_reports_one_failed_table(self, flow):
        assert flow.refused_failures == 1

    def test_gold_is_neither_rebuilt_nor_changed(self, flow):
        assert flow.refused.snapshots["gold"] == flow.before.snapshots["gold"]
        assert flow.refused.tags == flow.before.tags
        assert flow.refused.types["gold"] == "double"
        assert flow.refused.history == flow.before.history

    def test_the_sync_says_so_out_loud(self, flow):
        assert ("skipped gold.Transaction: primary_sql.transactions did not sync, so its silver is stale"
                in flow.refused_output)
        assert "FAILED  gold.Transaction" not in flow.refused_output



def _made_crlf(config_dir, *names):
    """The named configuration files with CRLF line ends, as an editor on
    Windows leaves them; returns {name: bytes}."""
    for name in names:
        path = config_dir / name
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    return {name: (config_dir / name).read_bytes() for name in names}


class TestACrlfFileStaysCrlf:
    """Path.read_text() turned CRLF into LF, so every edit from the screen
    rewrote a CRLF file with LF line ends, and the mixed-line-end refusal
    could never fire. The routes read and write the bytes as they are."""

    @pytest.fixture
    def crlf(self, config_dir, request):
        _prepared(config_dir)
        _made_crlf(config_dir, FILE)
        client = request.getfixturevalue("client")
        _login_as(client, "ops", "remover")
        return client

    def test_retype_keeps_every_line_end_and_the_digest_is_the_files_own(self, crlf, config_dir):
        import hashlib

        on_disk = (config_dir / FILE).read_bytes()
        assert hashlib.sha256(on_disk).hexdigest() == _digest(crlf)

        assert _retype(crlf).status_code == 200

        after = (config_dir / FILE).read_bytes()
        assert b"\r\n" in after and not re.search(rb"(?<!\r)\n", after)
        assert b"data_type: decimal" in after and after != on_disk

    def test_the_preview_of_a_retype_writes_nothing(self, crlf, config_dir):
        on_disk = (config_dir / FILE).read_bytes()
        assert _retype(crlf, preview=True).status_code == 200
        assert (config_dir / FILE).read_bytes() == on_disk

    def test_a_file_mixing_line_ends_is_refused_and_untouched(self, crlf, config_dir):
        path = config_dir / FILE
        path.write_bytes(path.read_bytes() + b"# an LF line\n")
        on_disk = path.read_bytes()

        for preview in (True, False):
            response = _retype(crlf, preview=preview)
            assert response.status_code == 400 and "mixes CRLF and LF" in response.json()["detail"]
        assert path.read_bytes() == on_disk

    def test_a_removal_keeps_every_line_end(self, crlf, config_dir):
        from tests.integration.test_removal_from_the_ui import _deprecate, _remove

        _deprecate(crlf)
        response = _remove(crlf)

        assert response.status_code == 200, response.text
        after = (config_dir / FILE).read_bytes()
        assert b"\r\n" in after and not re.search(rb"(?<!\r)\n", after)
        assert "currency" not in yaml.safe_load(after)["object_types"]["Account"]["fields"]

    def test_a_description_keeps_every_line_end(self, crlf, config_dir):
        response = crlf.put("/api/admin/ontology/descriptions", headers=_csrf_headers(crlf), json={
            "digest": _digest(crlf),
            "changes": [{"object_type": "Account", "field": "currency", "key": "description",
                         "value": "The currency."}]})

        assert response.status_code == 200, response.text
        after = (config_dir / FILE).read_bytes()
        assert b"The currency." in after and b"\r\n" in after and not re.search(rb"(?<!\r)\n", after)


class TestARefusalRestsOnTheLoadedSchemaAndTheColumn:
    """The refusal read the FILE's words and compared FIELD NAMES, but the
    loader resolves `security: inherit` to the silo's block, and storage is
    per COLUMN (a second declaration of a column on a shared table wins its
    type). core/ontology/retype.refusal judges what loads and what is
    stored where."""

    @staticmethod
    def _start(config_dir, request, mutate, silos=None):
        _prepared(config_dir)
        schema = yaml.safe_load((config_dir / FILE).read_text())
        mutate(schema["object_types"])
        (config_dir / FILE).write_text(yaml.safe_dump(schema, sort_keys=False))
        if silos:
            declared = yaml.safe_load((config_dir / "data_silos.yaml").read_text())
            silos(declared["data_silos"])
            (config_dir / "data_silos.yaml").write_text(yaml.safe_dump(declared, sort_keys=False))
        client = request.getfixturevalue("client")
        _login_as(client, "ops", "remover")
        return client

    @staticmethod
    def _refused(client, config_dir, what, says):
        before = (config_dir / FILE).read_bytes()
        for preview in (True, False):
            response = _retype(client, what, preview=preview)
            assert response.status_code == 400 and says in response.json()["detail"], response.text
        assert (config_dir / FILE).read_bytes() == before

    def test_a_field_whose_row_rule_is_inherited_from_its_silo_is_refused(self, config_dir, request):
        client = self._start(
            config_dir, request,
            lambda types: types["Customer"].update(security="inherit"),
            lambda silos: silos["primary_sql"].update(security={"field": "region"}))
        assert client.app.state.generation.config.schema["Customer"]["security"] == {"field": "region"}

        self._refused(client, config_dir, {"object_type": "Customer", "field": "region", "data_type": "integer"},
                      "who may see each row")

    def _shared(self, types):
        types["Vip"] = {"storage": {"silo": "primary_sql", "table": "customers", "id_column": "customer_id"},
                        "id_field": "customer_id", "security": "unrestricted",
                        "fields": {"region": {"type": "data"}, "name": {"type": "data"}}}

    def test_a_second_types_copy_of_the_security_column_on_a_shared_table_is_refused(self, config_dir, request):
        client = self._start(config_dir, request, self._shared)

        self._refused(client, config_dir, {"object_type": "Vip", "field": "region", "data_type": "integer"},
                      "decides who may see the rows of")

    def test_another_field_of_the_shared_table_is_still_retyped(self, config_dir, request):
        client = self._start(config_dir, request, self._shared)

        what = {"object_type": "Vip", "field": "name", "data_type": "integer"}
        assert _retype(client, what, preview=True).status_code == 200

    def test_a_field_stored_in_the_identifier_column_under_another_name_is_refused(self, config_dir, request):
        client = self._start(config_dir, request, lambda types: types["Customer"]["fields"].update(
            ref={"type": "data", "column": "customer_id"}))

        self._refused(client, config_dir, {"object_type": "Customer", "field": "ref", "data_type": "integer"},
                      "identifies the rows of Customer")

    def test_a_field_stored_in_a_links_key_column_is_refused(self, config_dir, request):
        client = self._start(config_dir, request, lambda types: types["Transaction"]["fields"].update(
            cust={"type": "data", "column": "customer_id"}))

        self._refused(client, config_dir, {"object_type": "Transaction", "field": "cust", "data_type": "integer"},
                      "joins on")

    def test_a_computed_field_is_refused_by_its_rule_not_by_its_type(self, config_dir, request):
        client = self._start(config_dir, request, lambda types: types["Customer"]["fields"].update(
            doubled={"type": "data", "derived": {"multiply": ["risk_score", 2]}}))
        response = _retype(client, {"object_type": "Customer", "field": "doubled", "data_type": "integer"},
                           preview=True)
        assert response.status_code == 400 and "what its rule produces" in response.json()["detail"]


class TestWhatTheDialogSaysForEachMode:
    """What a value that will not convert does depends on on_type_mismatch
    (config.yaml): the sentences say the one that is true."""

    @staticmethod
    def _preview(config_dir, request, setting):
        _prepared(config_dir)
        if setting:
            path = config_dir / "config.yaml"
            path.write_text(path.read_text() + f"\non_type_mismatch: {setting}\n")
        client = request.getfixturevalue("client")
        _login_as(client, "ops", "remover")
        response = _retype(client, preview=True)
        assert response.status_code == 200, response.text
        return " ".join(response.json()["stored_data"])

    @pytest.mark.parametrize("setting", [None, "refuse"])
    def test_refuse_stops_the_sync_and_the_rebuild_until_the_data_or_the_type_is_fixed(
            self, config_dir, request, setting):
        said = self._preview(config_dir, request, setting)

        assert "stops with an error naming it, and so does the rebuild" in said
        assert "until the data at the source or the type is fixed" in said and "set aside" not in said

    def test_quarantine_sets_rows_aside_at_each_sync(self, config_dir, request):
        said = self._preview(config_dir, request, "quarantine")

        assert "set aside in the quarantine table at every sync" in said and "stops with an error" not in said

    def test_the_dialogs_text_does_not_claim_nothing_is_lost_by_waiting(self, config_dir, request):
        said = self._preview(config_dir, request, None)

        assert "nothing is lost by waiting" not in said


class TestWhatIsOwedAsked:
    def test_the_list_is_what_the_sync_would_accept_and_is_empty_once_rebuilt_by_hand(self, retyper):
        assert retyper.get("/api/admin/mirror/rebuild-owed").json() == {"rebuild": [], "unknown": False}
        _retype(retyper)
        assert retyper.get("/api/admin/mirror/rebuild-owed").json() == {"rebuild": [SILVER], "unknown": False}

    def test_a_mirror_that_cannot_be_read_is_unknown_not_an_error(self, retyper, broken_catalog):
        response = retyper.get("/api/admin/mirror/rebuild-owed")

        assert response.status_code == 200 and response.json() == {"rebuild": [], "unknown": True}

    def test_only_a_manager_of_the_deployment_may_ask(self, retyper):
        retyper.cookies.clear()
        retyper.app.state.user_directory.create_user("pat", "correct-pw", "us-west", "customer_service")
        _login(retyper, "pat", "correct-pw")

        assert retyper.get("/api/admin/mirror/rebuild-owed").status_code == 403


class TestTheRebuildListIsTheSyncsOwn:
    def test_a_column_the_source_no_longer_has_makes_no_rebuild_owed(self, retyper):
        """The sync drops a column the source lost before it compares, so a
        rebuild for it would discard history for nothing: the route reads the
        columns bronze recorded at the last sync."""
        from core.mirror.catalog import open_mirror_catalog
        from core.mirror.iceberg_sync import SOURCE_COLUMNS_PROPERTY

        bronze = open_mirror_catalog(retyper.app.state.runtime_paths.data_dir / "mirror").load_table(
            "bronze_primary_sql.transactions")
        recorded = set(json.loads(bronze.properties[SOURCE_COLUMNS_PROPERTY]))
        assert "amount" in recorded
        with bronze.transaction() as change:
            change.set_properties({SOURCE_COLUMNS_PROPERTY: json.dumps(sorted(recorded - {"amount"}))})

        assert _retype(retyper).json()["rebuild"] == []
        assert _post_sync(retyper, rebuild=[SILVER]).status_code == 400
