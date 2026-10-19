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
