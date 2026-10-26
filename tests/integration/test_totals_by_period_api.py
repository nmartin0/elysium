"""Totals per period through the API, on a real sync (R68's ground).

Against a COPY of the fixture configuration with the transactions' date
declared a date -- the fixture leaves it text -- so nothing shared
changes.
"""

import contextlib
import io
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

import tests.integration.conftest as integration_conftest
from tests.integration.test_api import _csrf_headers, _login  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    from api.app import create_app
    from core.deployment_loader import RuntimePaths
    from scripts.run_sync import run_sync

    monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
    config = tmp_path / "config"
    shutil.copytree(integration_conftest.FIXTURES_DIR, config)
    ontology = yaml.safe_load((config / "ontology_schema.yaml").read_text())
    ontology["object_types"]["Transaction"]["fields"]["transaction_date"]["data_type"] = "date"
    (config / "ontology_schema.yaml").write_text(yaml.safe_dump(ontology))
    data = tmp_path / "data"
    fixtures = data / "dev_fixtures"
    fixtures.mkdir(parents=True)
    for sql, db in (("schema.sql", "mediator.db"), ("support_schema.sql", "support.db"),
                    ("risk_schema.sql", "risk.db")):
        integration_conftest._build_sqlite_db(integration_conftest.FIXTURES_DIR / sql, fixtures / db)
    (tmp_path / "log").mkdir()
    paths = RuntimePaths(config_dir=config, data_dir=data, log_dir=tmp_path / "log")
    with contextlib.redirect_stdout(io.StringIO()):
        run_sync(paths)
    client = TestClient(create_app(paths))
    client.app.state.user_directory.create_user("ops", "correct-pw", "us-west", "debug")
    _login(client, "ops", "correct-pw")
    return client


def _aggregate(client, **body):
    return client.post("/api/objects/Transaction/aggregate",
                       json={"aggregate": "count", "group_by": "transaction_date", **body},
                       headers=_csrf_headers(client))


def test_counted_by_month_with_the_empty_month_as_zero(client):
    response = _aggregate(client, period="month")
    assert response.status_code == 200, response.text
    # us-west's four transactions (cust_001 and cust_002): May, two in
    # June, nothing in July, none after -- us-east's July is not theirs.
    assert response.json()["results"] == {"2026-05-01": 2, "2026-06-01": 2}


def test_summed_by_week(client):
    response = _aggregate(client, period="week", aggregate="sum", field="amount")
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert list(results) == sorted(results) and results["2026-04-27"] == pytest.approx(99.98)
    assert all(value == 0 for start, value in results.items()
               if start not in ("2026-04-27", "2026-06-01", "2026-06-08"))


def test_a_period_on_text_is_a_400_that_says_why(client):
    response = client.post("/api/objects/Transaction/aggregate",
                           json={"aggregate": "count", "group_by": "category", "period": "week"},
                           headers=_csrf_headers(client))
    assert response.status_code == 400 and "must name a date" in response.text


def test_counted_by_a_fixed_length_of_days(client):
    # P7D counts from Monday 3 January 2000, so its weeks begin on Mondays
    # too -- the same starts as period=week, by another road.
    by_length = _aggregate(client, duration="P7D").json()["results"]
    by_week = _aggregate(client, period="week").json()["results"]
    assert by_length == by_week and by_length


@pytest.mark.parametrize("body, said", [
    ({"duration": "PT1H"}, "whole days only"),
    ({"duration": "P1W"}, "ask by period week"),
    ({"duration": "P1D", "time_zone": "Nowhere/At_All"}, "Unknown time zone"),
])
def test_a_duration_that_cannot_be_used_is_a_400_that_says_why(client, body, said):
    response = _aggregate(client, **body)
    assert response.status_code == 400 and said in response.text
