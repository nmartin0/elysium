"""A predicted field end to end (R48): proposed from gold, reviewed and
decided in the Inbox -- one compartment at a time.

Against a COPY of the fixture configuration with one predicted field
added, and enough transactions to learn from: the fixture's seven are
far below predictions.MIN_KNOWN.

    Transaction.refund_chance: the chance a transaction is a refund,
    learned from amount and currency. A refund is a negative amount --
    a pattern a model finds and the naive guess cannot.
"""

import contextlib
import io
import random
import shutil
import sqlite3
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

import tests.integration.conftest as integration_conftest
from tests.integration.test_api import _csrf_headers as _csrf
from tests.integration.test_api import _login  # noqa: F401

#: Customers by compartment, from the fixture's schema.sql.
WEST, EAST = ("cust_001", "cust_002"), ("cust_003",)
GRANTS = ["read:Transaction", "read:Transaction.transaction_id", "read:Transaction.amount",
          "read:Transaction.currency", "read:Transaction.category",
          "read:Transaction.refund_chance"]


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    from core.deployment_loader import RuntimePaths

    monkeypatch.setenv("ELYSIUM_COOKIE_SECURE", "false")
    config = tmp_path / "config"
    shutil.copytree(integration_conftest.FIXTURES_DIR, config)
    ontology = yaml.safe_load((config / "ontology_schema.yaml").read_text())
    ontology["object_types"]["Transaction"]["fields"]["refund_chance"] = {
        "predict": {"of": "category", "from": ["amount", "currency"], "chance_of": "refund"}}
    (config / "ontology_schema.yaml").write_text(yaml.safe_dump(ontology))
    policy = yaml.safe_load((config / "policy.yaml").read_text())
    policy["roles"]["debug"]["allowed_actions"] += GRANTS
    # MAY READ EVERYTHING INVOLVED but not manage the deployment, so its
    # refusal is about that grant and nothing else.
    policy["roles"]["customer_service"]["allowed_actions"] += GRANTS
    # MANAGES THE DEPLOYMENT and reads all but one input -- refused for
    # that input alone.
    policy["roles"]["manager_no_amount"] = {
        "allowed_actions": [action for action in policy["roles"]["debug"]["allowed_actions"]
                            + GRANTS if action != "read:Transaction.amount"]}
    (config / "policy.yaml").write_text(yaml.safe_dump(policy))

    data = tmp_path / "data"
    fixtures = data / "dev_fixtures"
    fixtures.mkdir(parents=True)
    for sql, db in (("schema.sql", "mediator.db"), ("support_schema.sql", "support.db"),
                    ("risk_schema.sql", "risk.db")):
        integration_conftest._build_sqlite_db(integration_conftest.FIXTURES_DIR / sql, fixtures / db)
    _add_transactions(fixtures / "mediator.db")
    (tmp_path / "log").mkdir()
    return RuntimePaths(config_dir=config, data_dir=data, log_dir=tmp_path / "log")


def _add_transactions(db):
    """300 per compartment's customers, a fifth refunds (mostly negative); and
    ten per compartment whose category is blank -- not known, so those are
    the ones a prediction fills."""
    rng = random.Random(3)
    rows = []
    for customers in (WEST, EAST):
        for index in range(300):
            refund = rng.random() < 0.2
            # MOSTLY negative: one refund in five is entered as a positive
            # amount, so the pattern is real but not a giveaway -- a
            # perfect one would rightly be called too good to be true.
            negative = refund and rng.random() < 0.8
            amount = -rng.uniform(5, 300) if negative else rng.uniform(5, 300)
            rows.append((customers[index % len(customers)], round(amount, 2),
                         rng.choice(["USD", "USD", "EUR"]),
                         "refund" if refund else rng.choice(["subscription", "hardware"]),
                         "2026-08-01"))
        for index in range(10):
            rows.append((customers[index % len(customers)], -50.0 if index < 5 else 80.0, "USD",
                         "", "2026-09-01"))
    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO transactions (customer_id, amount, currency, category, "
                         "transaction_date) VALUES (?, ?, ?, ?, ?)", rows)


def _sync(paths):
    from scripts.run_sync import run_sync

    with contextlib.redirect_stdout(io.StringIO()):
        run_sync(paths)


def _client(paths, user="ops", region="us-west", role="debug"):
    from api.app import create_app

    client = TestClient(create_app(paths))
    with contextlib.suppress(ValueError):
        client.app.state.user_directory.create_user(user, "correct-pw", region, role)
    _login(client, user, "correct-pw")
    return client


def _propose(paths, monkeypatch, *extra):
    """scripts.propose_prediction, as a person runs it."""
    from scripts import propose_prediction

    monkeypatch.setenv("ELYSIUM_CONFIG_DIR", str(paths.config_dir))
    monkeypatch.setenv("ELYSIUM_DATA_DIR", str(paths.data_dir))
    monkeypatch.setenv("ELYSIUM_LOG_DIR", str(paths.log_dir))
    monkeypatch.setattr(sys, "argv", ["propose_prediction", "Transaction.refund_chance", *extra])
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = propose_prediction.main()
    return code, out.getvalue() + err.getvalue()


def _proposals(client):
    response = client.get("/api/prediction-proposals")
    assert response.status_code == 200, response.text
    return response.json()["proposals"]


class TestProposing:
    def test_the_script_measures_and_proposes_for_one_compartment(self, deployment, monkeypatch):
        _sync(deployment)
        code, said = _propose(deployment, monkeypatch, "--group-by", "currency")
        assert code == 1 and "3 security compartments" in said, said

        code, said = _propose(deployment, monkeypatch, "--group-by", "currency",
                              "--compartment", "us-west")
        assert code == 0, said
        assert "PROPOSED as" in said and "By currency:" in said

        (proposal,) = _proposals(_client(deployment))
        assert proposal["compartment"] == "us-west"
        assert proposal["kind"] == "chance" and proposal["chance_of"] == "refund"
        evaluation = proposal["evaluation"]
        # LEARNED FROM ITS OWN COMPARTMENT ONLY: us-west's 300 known
        # transactions plus the fixture's four of its customers.
        assert evaluation["known"] == 304, evaluation
        assert 0.3 < evaluation["skill"] < 0.98 and proposal["refusal"] is None
        assert "warning" not in evaluation
        assert evaluation["important"][0]["field"] == "amount"
        assert {group["value"] for group in evaluation["groups"]} == {"USD", "EUR"}

    def test_a_group_field_is_required(self, deployment, monkeypatch):
        _sync(deployment)
        with pytest.raises(SystemExit):
            _propose(deployment, monkeypatch, "--compartment", "us-west")

    def test_a_group_field_that_cannot_group_is_refused(self, deployment, monkeypatch):
        _sync(deployment)
        code, said = _propose(deployment, monkeypatch, "--group-by", "category",
                              "--compartment", "us-west")
        assert code == 1 and "the answer" in said, said


GOOD = {"skill": 0.42, "score": 0.05, "naive_score": 0.16, "known": 300, "judged_on": 60,
        "learned_from": 240, "measure": "chance error (Brier)", "kind": "chance",
        "important": [{"field": "amount", "share": 1.0}], "group_by": "currency",
        "groups": [{"value": "USD", "records": 40, "score": 0.05, "skill": 0.4}]}


def _store_proposal(paths, compartment="us-west", evaluation=None):
    from core.ontology.predicted_fields import declaration_hash, prediction_of
    from core.prediction_proposals import PredictionProposalStore

    fields = yaml.safe_load((paths.config_dir / "ontology_schema.yaml").read_text())[
        "object_types"]["Transaction"]["fields"]
    digest = declaration_hash("Transaction", "refund_chance",
                              prediction_of(fields["refund_chance"], fields))
    return PredictionProposalStore(paths.data_dir / "prediction_proposals.db").propose(
        "Transaction", "refund_chance", digest, compartment, evaluation or GOOD, {})


class TestReviewing:
    def test_seen_only_in_its_own_compartment(self, deployment):
        west = _store_proposal(deployment, "us-west")
        _store_proposal(deployment, "us-east")
        assert [p["proposal_id"] for p in _proposals(_client(deployment))] == [west]

    def test_not_seen_without_managing_the_deployment(self, deployment):
        _store_proposal(deployment)
        assert _proposals(_client(deployment, "cs", role="customer_service")) == []

    def test_not_seen_without_reading_every_input(self, deployment):
        _store_proposal(deployment)
        assert _proposals(_client(deployment, "mgr", role="manager_no_amount")) == []

    def test_approved_once_and_counted_while_waiting(self, deployment):
        proposal = _store_proposal(deployment)
        client = _client(deployment)
        assert client.get("/api/me/inbox").json()["predictions"] == 1
        decided = client.post(f"/api/prediction-proposals/{proposal}/decide", json={"approve": True},
                           headers=_csrf(client))
        assert decided.status_code == 200, decided.text
        assert decided.json()["status"] == "approved"
        assert client.get("/api/me/inbox").json()["predictions"] == 0
        again = client.post(f"/api/prediction-proposals/{proposal}/decide", json={"approve": True},
                           headers=_csrf(client))
        assert again.status_code == 409

    def test_no_better_than_guessing_is_refused_but_may_be_rejected(self, deployment):
        proposal = _store_proposal(deployment, evaluation={**GOOD, "skill": -0.1})
        client = _client(deployment)
        (shown,) = _proposals(client)
        assert "no better than the naive guess" in shown["refusal"]
        refused = client.post(f"/api/prediction-proposals/{proposal}/decide", json={"approve": True},
                           headers=_csrf(client))
        assert refused.status_code == 409 and "naive guess" in refused.text
        rejected = client.post(f"/api/prediction-proposals/{proposal}/decide",
                               json={"approve": False},
                           headers=_csrf(client))
        assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"

    def test_another_compartments_proposal_cannot_be_decided(self, deployment):
        proposal = _store_proposal(deployment, "us-east")
        client = _client(deployment)
        response = client.post(f"/api/prediction-proposals/{proposal}/decide",
                               json={"approve": True}, headers=_csrf(client))
        assert response.status_code == 404
