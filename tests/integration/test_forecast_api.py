"""A forecast through the API, on a real sync (R68).

Against a COPY of the fixture with the transactions' date declared a
date and a year of us-west transactions added, ending today: rising
slowly, busier on weekdays -- so there is a trend to find, and a week
still running.
"""

import contextlib
import datetime
import io
import random
import shutil
import sqlite3

import pytest
import yaml
from fastapi.testclient import TestClient

import tests.integration.conftest as integration_conftest
from tests.integration.test_api import _csrf_headers, _login  # noqa: F401

TODAY = datetime.datetime.now(datetime.UTC).date()


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    from core.deployment_loader import RuntimePaths
    from scripts.run_sync import run_sync

    root = tmp_path_factory.mktemp("forecast")
    config = root / "config"
    shutil.copytree(integration_conftest.FIXTURES_DIR, config)
    ontology = yaml.safe_load((config / "ontology_schema.yaml").read_text())
    ontology["object_types"]["Transaction"]["fields"]["transaction_date"]["data_type"] = "date"
    (config / "ontology_schema.yaml").write_text(yaml.safe_dump(ontology))
    data = root / "data"
    fixtures = data / "dev_fixtures"
    fixtures.mkdir(parents=True)
    for sql, db in (("schema.sql", "mediator.db"), ("support_schema.sql", "support.db"),
                    ("risk_schema.sql", "risk.db")):
        integration_conftest._build_sqlite_db(integration_conftest.FIXTURES_DIR / sql, fixtures / db)
    rng = random.Random(1)
    rows = []
    for back in range(365, -1, -1):
        day = TODAY - datetime.timedelta(days=back)
        for _ in range(max(0, round(rng.gauss(3 + (365 - back) / 120
                                              + (2 if day.weekday() < 5 else -1), 1)))):
            rows.append((rng.choice(["cust_001", "cust_002"]), round(rng.uniform(5, 300), 2),
                         "USD", "subscription", day.isoformat()))
    with sqlite3.connect(fixtures / "mediator.db") as conn:
        conn.executemany("INSERT INTO transactions (customer_id, amount, currency, category, "
                         "transaction_date) VALUES (?, ?, ?, ?, ?)", rows)
    (root / "log").mkdir()
    paths = RuntimePaths(config_dir=config, data_dir=data, log_dir=root / "log")
    with contextlib.redirect_stdout(io.StringIO()):
        run_sync(paths)
    return paths


def _client(paths, user, region, monkeypatch):
    from api.app import create_app

    monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
    client = TestClient(create_app(paths))
    with contextlib.suppress(ValueError):
        client.app.state.user_directory.create_user(user, "correct-pw", region, "debug")
    _login(client, user, "correct-pw")
    return client


def _forecast(client, **body):
    return client.post("/api/objects/Transaction/forecast",
                       json={"group_by": "transaction_date", "period": "week", **body},
                       headers=_csrf_headers(client))


def test_weekly_counts_are_forecast_and_tested(paths, monkeypatch):
    response = _forecast(_client(paths, "ops", "us-west", monkeypatch))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["refusal"] is None, body["refusal"]
    this_week = TODAY - datetime.timedelta(days=TODAY.weekday())
    # THE RUNNING WEEK IS APART, and never in the history the model saw.
    assert body["running"]["start"] == this_week.isoformat()
    assert this_week.isoformat() not in body["history"]
    assert max(body["history"]) == (this_week - datetime.timedelta(days=7)).isoformat()
    # THE FIRST PERIOD AHEAD IS THIS ONE: where the running week will
    # finish, beside what it has so far.
    assert len(body["points"]) == 8 and body["points"][0]["start"] == this_week.isoformat()
    backtest = body["backtest"]
    assert backtest["typical_miss"] < backtest["naive_miss"] and backtest["origins"] == 4
    # THE TREND IS UP: ahead of where the first weeks were.
    first_weeks = sorted(body["history"].items())[:8]
    assert body["points"][0]["value"] > max(value for _, value in first_weeks)


def test_another_compartment_forecasts_only_its_own_records(paths, monkeypatch):
    """us-east has the fixture's two transactions and none of the year
    added for us-west: weeks of nothing, which no forecast beats carrying
    on -- and none of us-west's records counted."""
    body = _forecast(_client(paths, "east", "us-east", monkeypatch)).json()
    assert sum(body["history"].values()) + (body["running"] or {}).get("value", 0) == 2
    assert body["points"] == [] and body["refusal"]


def test_a_sum_is_forecast_too(paths, monkeypatch):
    body = _forecast(_client(paths, "ops", "us-west", monkeypatch), aggregate="sum",
                     field="amount", period="month").json()
    assert body["history"] and (body["points"] or body["refusal"])


def test_only_a_count_or_a_sum(paths, monkeypatch):
    response = _forecast(_client(paths, "ops", "us-west", monkeypatch), aggregate="avg",
                         field="amount")
    assert response.status_code == 400 and "count or a sum" in response.text


def test_a_cut_off_set_is_not_forecast(paths, monkeypatch):
    """Every period counted from a cut-off set is a floor, and a forecast
    of floors is a guess about where the cut fell."""
    import core.ontology.mediator as mediator_module

    monkeypatch.setattr(mediator_module, "MAX_SEARCH_SCAN", 50)
    body = _forecast(_client(paths, "ops", "us-west", monkeypatch)).json()
    assert body["scan_truncated"] is True
    assert body["points"] == [] and "Only part of the set was counted" in body["refusal"]
