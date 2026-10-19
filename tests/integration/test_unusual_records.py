"""Unusual records end to end (R51): declared, found when gold is rebuilt,
each compartment judged on its own.

Against a COPY of the fixture with Transaction declaring
`unusual: {numbers: [amount], within: [category]}` and 400 transactions
per compartment added, amounts that depend on the category -- and a few
planted that are ordinary for the table but not for their category.
"""

import contextlib
import io
import random
import shutil
import sqlite3

import pytest
import yaml

import tests.integration.conftest as integration_conftest

WEST, EAST = ("cust_001", "cust_002"), ("cust_003",)
USUAL = {"subscription": (50, 5), "hardware": (300, 30), "refund": (-80, 10)}


@pytest.fixture
def deployment(tmp_path):
    from core.deployment_loader import RuntimePaths

    config = tmp_path / "config"
    shutil.copytree(integration_conftest.FIXTURES_DIR, config)
    ontology = yaml.safe_load((config / "ontology_schema.yaml").read_text())
    ontology["object_types"]["Transaction"]["unusual"] = {"numbers": ["amount"],
                                                          "within": ["category"]}
    (config / "ontology_schema.yaml").write_text(yaml.safe_dump(ontology))
    data = tmp_path / "data"
    fixtures = data / "dev_fixtures"
    fixtures.mkdir(parents=True)
    for sql, db in (("schema.sql", "mediator.db"), ("support_schema.sql", "support.db"),
                    ("risk_schema.sql", "risk.db")):
        integration_conftest._build_sqlite_db(integration_conftest.FIXTURES_DIR / sql, fixtures / db)
    rng = random.Random(4)
    rows = []
    for customers, odd in ((WEST, ("subscription", 300.0)), (EAST, ("hardware", 50.0))):
        for index in range(400):
            category = rng.choice(list(USUAL))
            mean, spread = USUAL[category]
            rows.append((customers[index % len(customers)], round(rng.gauss(mean, spread), 2),
                         "USD", category, "2026-08-01"))
        # ORDINARY FOR THE TABLE, NOT FOR ITS CATEGORY.
        rows.append((customers[0], odd[1], "USD", odd[0], "2026-08-02"))
    with sqlite3.connect(fixtures / "mediator.db") as conn:
        conn.executemany("INSERT INTO transactions (customer_id, amount, currency, category, "
                         "transaction_date) VALUES (?, ?, ?, ?, ?)", rows)
    (tmp_path / "log").mkdir()
    return RuntimePaths(config_dir=config, data_dir=data, log_dir=tmp_path / "log")


def _sync(paths) -> str:
    from scripts.run_sync import run_sync

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        run_sync(paths)
    return out.getvalue()


def _flags(paths):
    from core.unusual_flags import UnusualFlagStore

    return UnusualFlagStore(paths.data_dir / "unusual_flags.db").flags("Transaction")


def test_found_at_the_sync_and_judged_within_each_compartment(deployment):
    said = _sync(deployment)
    assert "unusual record value(s) in Transaction" in said
    flags = _flags(deployment)
    by_compartment = {}
    for flag in flags:
        by_compartment.setdefault(flag.compartment, []).append(flag)
    west = {(flag.value, dict(flag.kind)["category"]) for flag in by_compartment["us-west"]}
    east = {(flag.value, dict(flag.kind)["category"]) for flag in by_compartment["us-east"]}
    assert (300.0, "subscription") in west and (50.0, "hardware") in east
    # EACH AGAINST ITS OWN: us-west's planted record is not us-east's.
    assert (50.0, "hardware") not in west and (300.0, "subscription") not in east
    reason = next(flag for flag in by_compartment["us-west"] if flag.value == 300.0).reason()
    assert reason.startswith("amount 300 is far above the usual ")


def test_unchanged_gold_keeps_its_flags_and_is_not_scanned_again(deployment, monkeypatch):
    import core.mirror.unusual_scan as unusual_scan

    _sync(deployment)
    before = _flags(deployment)
    calls = []
    monkeypatch.setattr(unusual_scan, "scan", lambda *a, **k: calls.append(a) or 0)
    _sync(deployment)
    assert calls == [] and _flags(deployment) == before


def _client(paths, user, region, role="debug"):
    from fastapi.testclient import TestClient

    from api.app import create_app
    from tests.integration.test_api import _login

    client = TestClient(create_app(paths))
    with contextlib.suppress(ValueError):
        client.app.state.user_directory.create_user(user, "correct-pw", region, role)
    _login(client, user, "correct-pw")
    return client


def _planted_id(paths, compartment, value):
    return next(flag.record_id for flag in _flags(paths)
                if flag.compartment == compartment and flag.value == value)


def _unusual(client, ids):
    response = client.get("/api/unusual/Transaction", params={"ids": ",".join(ids)})
    assert response.status_code == 200, response.text
    return response.json()["unusual"]


class TestTheMarker:
    def test_a_reader_of_the_fields_is_told_why(self, deployment, monkeypatch):
        monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
        _sync(deployment)
        west = _planted_id(deployment, "us-west", 300.0)
        (flag,) = _unusual(_client(deployment, "ops", "us-west"), [west, "1"])[west]
        assert flag["field"] == "amount" and flag["value"] == 300.0
        assert flag["reason"].startswith("amount 300 is far above the usual ")

    def test_another_compartment_is_told_nothing(self, deployment, monkeypatch):
        monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
        _sync(deployment)
        west = _planted_id(deployment, "us-west", 300.0)
        assert _unusual(_client(deployment, "east", "us-east"), [west]) == {}

    def test_not_without_reading_every_field_it_was_compared_within(self, deployment,
                                                                   monkeypatch):
        monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
        policy_path = deployment.config_dir / "policy.yaml"
        policy = yaml.safe_load(policy_path.read_text())
        policy["roles"]["no_category"] = {"allowed_actions": [
            action for action in policy["roles"]["debug"]["allowed_actions"]
            if action != "read:Transaction.category"]}
        policy_path.write_text(yaml.safe_dump(policy))
        _sync(deployment)
        west = _planted_id(deployment, "us-west", 300.0)
        assert _unusual(_client(deployment, "ops", "us-west"), [west])
        assert _unusual(_client(deployment, "nocat", "us-west", "no_category"), [west]) == {}

    def test_expected_clears_it_for_everyone_until_the_value_changes(self, deployment,
                                                                    monkeypatch):
        from core.unusual_flags import UnusualFlagStore

        monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
        _sync(deployment)
        west = _planted_id(deployment, "us-west", 300.0)
        UnusualFlagStore(deployment.data_dir / "unusual_flags.db").decide(
            "Transaction", west, "amount", 300.0, "expected", "ops")
        assert _unusual(_client(deployment, "ops", "us-west"), [west]) == {}

    def test_a_flag_from_another_compartment_is_not_shown_on_a_readable_record(
            self, deployment, monkeypatch):
        """The record moved compartment since it was judged: the flag rests
        on the other compartment's records, so it is not shown -- though
        the record itself now may be read."""
        import dataclasses

        from core.unusual import find_unusual  # noqa: F401 - the shape stored
        from core.unusual_flags import UnusualFlagStore

        monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
        _sync(deployment)
        store = UnusualFlagStore(deployment.data_dir / "unusual_flags.db")
        west = next(flag for flag in store.flags("Transaction")
                    if flag.compartment == "us-west" and flag.value == 300.0)
        _restore(store, [dataclasses.replace(west, compartment="us-east")])
        assert _unusual(_client(deployment, "ops", "us-west"), [west.record_id]) == {}

    def test_a_record_the_reader_cannot_see_is_not_answered(self, deployment, monkeypatch):
        """A flag with no compartment, on a record the reader may not read:
        the record's own check answers it."""
        import dataclasses

        from core.unusual_flags import UnusualFlagStore

        monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
        _sync(deployment)
        store = UnusualFlagStore(deployment.data_dir / "unusual_flags.db")
        east = next(flag for flag in store.flags("Transaction")
                    if flag.compartment == "us-east" and flag.value == 50.0)
        _restore(store, [dataclasses.replace(east, compartment=None)])
        assert _unusual(_client(deployment, "ops", "us-west"), [east.record_id]) == {}

    def test_a_flag_the_declaration_no_longer_makes_is_not_shown(self, deployment,
                                                                 monkeypatch):
        """Flags found under an earlier declaration -- another number, or
        compared within other fields -- wait for the next scan unshown."""
        import dataclasses

        from core.unusual_flags import UnusualFlagStore

        monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
        _sync(deployment)
        store = UnusualFlagStore(deployment.data_dir / "unusual_flags.db")
        west = next(flag for flag in store.flags("Transaction")
                    if flag.compartment == "us-west" and flag.value == 300.0)
        client = _client(deployment, "ops", "us-west")
        _restore(store, [dataclasses.replace(west, field="currency")])
        assert _unusual(client, [west.record_id]) == {}
        _restore(store, [dataclasses.replace(west, kind=(("currency", "USD"),))])
        assert _unusual(client, [west.record_id]) == {}
        _restore(store, [west])
        assert _unusual(client, [west.record_id])  # THE CONTROL: as found, shown.


def _restore(store, stored):
    """Writes stored flags back, as the scan would have."""
    from core.unusual import Flag

    by_compartment: dict = {}
    for flag in stored:
        by_compartment.setdefault(flag.compartment, []).append(Flag(
            flag.record_id, flag.field, flag.value, flag.kind, flag.median, flag.low, flag.high,
            flag.group_size, flag.score))
    store.replace("Transaction", {key: (flags, len(flags)) for key, flags in
                                  by_compartment.items()})


def _with_roles(paths, **extra):
    """Adds roles to the copy's policy: each the debug role's grants,
    plus or minus some."""
    policy_path = paths.config_dir / "policy.yaml"
    policy = yaml.safe_load(policy_path.read_text())
    base = policy["roles"]["debug"]["allowed_actions"]
    for name, (plus, minus) in extra.items():
        policy["roles"][name] = {"allowed_actions": [a for a in base if a not in minus] + plus}
    policy_path.write_text(yaml.safe_dump(policy))


def _queue(client):
    response = client.get("/api/unusual-review")
    assert response.status_code == 200, response.text
    return response.json()


def _decide(client, record_id, decision, field="amount"):
    from tests.integration.test_api import _csrf_headers

    return client.post("/api/unusual-review/decide", json={
        "object_type": "Transaction", "record_id": record_id, "field": field,
        "decision": decision}, headers=_csrf_headers(client))


def _waiting(client):
    response = client.get("/api/me/inbox")
    assert response.status_code == 200, response.text
    return response.json()["unusual"]


@pytest.fixture
def reviewed(deployment, monkeypatch):
    monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
    _with_roles(deployment, reviewer=(["write:Transaction"], []),
                reviewer_no_category=(["write:Transaction"], ["read:Transaction.category"]))
    _sync(deployment)
    return deployment


class TestTheQueue:
    def test_someone_who_may_edit_the_type_is_shown_why_in_their_compartment(self, reviewed):
        client = _client(reviewed, "rev", "us-west", "reviewer")
        queue = _queue(client)
        planted = next(item for item in queue["items"] if item["value"] == 300.0)
        assert planted["reason"].startswith("amount 300 is far above the usual ")
        assert planted["field_label"] and planted["decision"] is None
        assert {item["compartment"] for item in queue["items"]} == {"us-west"}
        assert queue["found"] >= len(queue["items"]) > 0
        assert _waiting(client) == len(queue["items"])

    def test_not_without_write_on_the_type(self, reviewed):
        """A reader is told of it on the record; deciding is an editor's."""
        client = _client(reviewed, "ops", "us-west")
        west = _planted_id(reviewed, "us-west", 300.0)
        assert _unusual(client, [west])
        assert _queue(client)["items"] == [] and _waiting(client) == 0
        assert _decide(client, west, "expected").status_code == 404

    def test_not_without_read_on_every_field_compared_within(self, reviewed):
        client = _client(reviewed, "revnocat", "us-west", "reviewer_no_category")
        west = _planted_id(reviewed, "us-west", 300.0)
        assert _queue(client)["items"] == [] and _waiting(client) == 0
        assert _decide(client, west, "expected").status_code == 404

    def test_another_compartment_neither_sees_nor_decides(self, reviewed):
        client = _client(reviewed, "reveast", "us-east", "reviewer")
        west = _planted_id(reviewed, "us-west", 300.0)
        assert all(item["record_id"] != west for item in _queue(client)["items"])
        assert _decide(client, west, "expected").status_code == 404
        # THE CONTROL: its own compartment's planted value is there.
        assert any(item["value"] == 50.0 for item in _queue(client)["items"])

    def test_expected_clears_the_marker_for_everyone_and_is_audited(self, reviewed):
        import json

        reviewer = _client(reviewed, "rev", "us-west", "reviewer")
        reader = _client(reviewed, "ops", "us-west")
        west = _planted_id(reviewed, "us-west", 300.0)
        before = _waiting(reviewer)
        response = _decide(reviewer, west, "expected")
        assert response.status_code == 200, response.text
        assert response.json()["decision"] == "expected"
        assert _unusual(reader, [west]) == {}
        assert _waiting(reviewer) == before - 1
        # STILL LISTED, decided, so the decision can be changed.
        (item,) = [item for item in _queue(reviewer)["items"] if item["record_id"] == west]
        assert item["decision"] == "expected" and item["decided_by"] == "rev"
        lines = (reviewed.log_dir / "audit.log").read_text().splitlines()
        entries = [entry for entry in map(json.loads, lines)
                   if entry.get("stage") == "unusual_decision"]
        assert [(e["object_id"], e["value"], e["decision"], e["user_id"]) for e in entries] == [
            (west, 300.0, "expected", "rev")]

    def test_worth_a_look_keeps_the_marker_and_leaves_the_count(self, reviewed):
        reviewer = _client(reviewed, "rev", "us-west", "reviewer")
        reader = _client(reviewed, "ops", "us-west")
        west = _planted_id(reviewed, "us-west", 300.0)
        before = _waiting(reviewer)
        assert _decide(reviewer, west, "worth_a_look").status_code == 200
        (shown,) = _unusual(reader, [west])[west]
        assert shown["decision"] == "worth_a_look"
        assert _waiting(reviewer) == before - 1

    def test_only_the_two_decisions(self, reviewed):
        reviewer = _client(reviewed, "rev", "us-west", "reviewer")
        west = _planted_id(reviewed, "us-west", 300.0)
        assert _decide(reviewer, west, "deleted").status_code == 422
        assert _decide(reviewer, west, "expected", field="currency").status_code == 404

    def test_a_record_the_reviewer_cannot_see_is_neither_listed_nor_decided(self, reviewed):
        """A flag with no compartment on a record of another: the record's
        own read check answers, in the listing and the decision both."""
        import dataclasses

        from core.unusual_flags import UnusualFlagStore

        store = UnusualFlagStore(reviewed.data_dir / "unusual_flags.db")
        east = next(flag for flag in store.flags("Transaction")
                    if flag.compartment == "us-east" and flag.value == 50.0)
        _restore(store, [dataclasses.replace(east, compartment=None)])
        reviewer = _client(reviewed, "rev", "us-west", "reviewer")
        assert _queue(reviewer)["items"] == [] and _waiting(reviewer) == 0
        assert _decide(reviewer, east.record_id, "expected").status_code == 404
        # THE CONTROL: its own compartment's reviewer may.
        assert _decide(_client(reviewed, "reveast", "us-east", "reviewer"), east.record_id,
                       "expected").status_code == 200
