"""A view filtered on a recent date answers (found 16 October).

adapters/sqlalchemy_adapter.py said the mediator turned a relative date
into a date_range before calling storage. Nothing did: every adapter
declined `relative_date`, the Python fallback raised "Cannot evaluate",
and the filter answered with an error everywhere -- Browse, the count,
and every trigger watching such a view. Found by checking a trigger on
one end to end. core/filters.py, resolved().

Pinned to a fixed now, because the fixture's transactions are dated
May to July 2026 and "the last N days" moves.
"""

from datetime import UTC, datetime

import core.filters
from tests.integration.test_api import _csrf_headers, _login

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def _pin(monkeypatch):
    real = core.filters.resolve_relative_date
    monkeypatch.setattr(core.filters, "resolve_relative_date",
                        lambda value, now=None: real(value, now or NOW))


def _count(client, value):
    response = client.post(
        "/api/objects/Transaction/count",
        json={"conditions": [{"field": "transaction_date", "operator": "relative_date", "value": value}]},
        headers=_csrf_headers(client))
    assert response.status_code == 200, response.text
    return response.json()["count"]


def test_in_the_last_n_days(client, monkeypatch):
    """alice (us-west) sees cust_001 and cust_002's four transactions;
    two of them are within 60 days of 20 July: 14 June and 2 June."""
    _pin(monkeypatch)
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    assert _count(client, {"since_days_ago": 60}) == 2
    assert _count(client, {"since_days_ago": 36500}) == 4


def test_more_than_n_days_ago(client, monkeypatch):
    _pin(monkeypatch)
    client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
    _login(client, "alice", "correct-pw")

    assert _count(client, {"until_days_ago": 60}) == 2


def test_a_date_field_gets_dates():
    """A timestamp bound is not compared with a date column."""
    condition = core.filters.FieldFilter("d", "relative_date", {"since_days_ago": 1})

    assert core.filters.resolved(condition, "date", NOW).value == {"start": "2026-07-19", "end": None}
    assert core.filters.resolved(condition, "timestamp", NOW).value["start"].startswith("2026-07-19T12:00")
