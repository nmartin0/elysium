"""`security: unrestricted`, end to end (19 October).

A product catalogue in the source database, declared unrestricted,
synced into the lake and read through the API by two people in
different regions: both see every product, a role without the grant sees
none, and the customers beside it stay compartmented. And the "who can
see this" screen says it outright rather than "no compartment".
"""

import contextlib
import io
import shutil
import sqlite3

import pytest
import yaml

from tests.integration.conftest import FIXTURES_DIR, _build_sqlite_db
from tests.integration.test_api import _login


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api.app import create_app
    from core.deployment_loader import RuntimePaths
    from scripts.run_sync import run_sync

    monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
    config = tmp_path / "config"
    shutil.copytree(FIXTURES_DIR, config, ignore=shutil.ignore_patterns("other_deployment"))

    ontology = yaml.safe_load((config / "ontology_schema.yaml").read_text())
    ontology["object_types"]["Product"] = {
        "display_name": "Product", "plural_display_name": "Products",
        "storage": {"silo": "primary_sql", "table": "products", "id_column": "sku"},
        "id_field": "sku", "title_field": "name",
        "security": "unrestricted",
        "fields": {"name": {"type": "data"}, "price": {"type": "data"}},
    }
    (config / "ontology_schema.yaml").write_text(yaml.safe_dump(ontology, sort_keys=False))

    policy = yaml.safe_load((config / "policy.yaml").read_text())
    for role in ("customer_service", "debug"):
        policy["roles"][role]["allowed_actions"] += [
            "read:Product", "read:Product.sku", "read:Product.name", "read:Product.price"]
    (config / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))

    data = tmp_path / "data"
    fixtures = data / "dev_fixtures"
    fixtures.mkdir(parents=True)
    for db, sql in (("mediator.db", "schema.sql"), ("support.db", "support_schema.sql"),
                    ("risk.db", "risk_schema.sql")):
        _build_sqlite_db(FIXTURES_DIR / sql, fixtures / db)
    with sqlite3.connect(fixtures / "mediator.db") as conn:
        conn.execute("CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, price TEXT)")
        conn.executemany("INSERT INTO products VALUES (?, ?, ?)",
                         [("sku_1", "Kettle", "30"), ("sku_2", "Toaster", "45")])
    (tmp_path / "log").mkdir()
    paths = RuntimePaths(config_dir=config, data_dir=data, log_dir=tmp_path / "log")
    with contextlib.redirect_stdout(io.StringIO()):
        assert run_sync(paths) == 0
    app = create_app(paths)
    for name, region, role in (("west", "us-west", "customer_service"),
                               ("east", "us-east", "customer_service"),
                               ("admin", "us-west", "admin"),
                               ("dana", "us-west", "debug")):
        app.state.user_directory.create_user(name, "correct-pw", region, role)
    return TestClient(app)


def _products(client, user):
    _login(client, user, "correct-pw")
    response = client.get("/api/objects/Product/search", params={"q": ""})
    return response


def test_people_in_different_regions_both_see_every_product(client):
    for user in ("west", "east"):
        response = _products(client, user)
        assert response.status_code == 200, response.text
        assert response.json()["total_matches"] == 2, user


def test_a_role_without_the_grant_sees_none(client):
    response = _products(client, "admin")

    # UNIFORM DENIAL: an empty answer, not an error -- asserted exactly, so
    # a 500 cannot pass as "sees none" (the first version allowed it).
    assert response.status_code == 200 and response.json()["total_matches"] == 0


def test_customers_beside_it_stay_compartmented(client):
    _login(client, "west", "correct-pw")
    west = client.get("/api/objects/Customer/search", params={"q": ""}).json()["total_matches"]
    _login(client, "east", "correct-pw")
    east = client.get("/api/objects/Customer/search", params={"q": ""}).json()["total_matches"]

    assert west and east and west + east <= 4, "each region sees only its own customers"


def test_who_can_see_says_unrestricted(client):
    _login(client, "dana", "correct-pw")

    compartment = client.get("/api/schema/access").json()["Product"]["compartment"]

    assert compartment["unrestricted"] is True and compartment["field"] is None
