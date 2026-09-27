"""An audit entry survives whatever type an id field declares
(SEC-25).

FOUND READING core/intermediate_layer/audit.py.

`_write()` used a bare `json.dumps(entry)`. `object_id` is typed `Any`
and comes from the object's `id_field`, whose `data_type` an ontology
may declare freely -- `object_type_validation` accepts `decimal`,
`date` and `timestamp` for it, tested below. `_write` runs on EVERY
access decision, so a date-keyed or decimal-keyed type raised
TypeError on every read: the whole object type unusable, reporting a
JSON error rather than anything about the ontology.

    log_access(..., object_id=Decimal("49.99"), ...)
    -> TypeError: Object of type Decimal is not JSON serializable

FAIL-CLOSED, WHICH IS WHY THIS IS AVAILABILITY AND NOT A HOLE. The
raise happened INSIDE the authorization path, so an access that could
not be logged did not proceed. Nothing was served unlogged.

WHY `default=str` IS RIGHT HERE AND WAS WRONG IN
pending_write_serialisation (SEC-16). There, a stored
`expected_current_value` is COMPARED against a freshly read one, so a
stringified Decimal silently stops matching and every such write is
refused as a conflict -- a crash traded for a wrong answer. Nothing
compares an audit entry to anything: it is a record for an operator,
read back only to be shown. The string form of an id is exactly what a
person reading a trace wants. The same one-line change is correct in
one place and a bug in the other, which is the whole reason to say why
rather than to apply a habit.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from core.intermediate_layer.audit import AuditLog
from core.ontology.object_type_validation import validate_object_types


@pytest.fixture
def log(tmp_path) -> AuditLog:
    return AuditLog(tmp_path / "audit.log")


def _lines(log) -> list[dict]:
    return [json.loads(line) for line in log._log_path.read_text().splitlines()]


class TestTheTypesAnIdFieldMayDeclare:
    @pytest.mark.parametrize("object_id", [
        "cust_001",
        42,
        Decimal("49.99"),
        date(2026, 1, 1),
        datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        b"\x00\x01binary",
    ])
    def test_an_access_decision_is_recorded(self, log, object_id):
        log.log_access("alice", "Customer", object_id, "read:Customer.name", True, True)

        assert len(_lines(log)) == 1

    def test_every_line_stays_valid_json(self, log):
        """The log is JSONL and is read back line by line. A writer
        that emitted something unparseable would break the trace
        instead of the write."""
        for object_id in ("cust_001", 42, Decimal("1.5"), date(2026, 1, 1), b"\x00"):
            log.log_access("alice", "Customer", object_id, "read:Customer.name", True, True)

        assert len(_lines(log)) == 5

    def test_a_denial_is_recorded_too(self, log):
        """Denials matter more than allowances here, and they take the
        same path."""
        log.log_access("alice", "Customer", Decimal("49.99"),
                       "read:Customer.name", mac_allowed=False, rbac_allowed=True)

        entry = _lines(log)[0]
        assert entry["mac_allowed"] is False
        assert entry["rbac_allowed"] is True


class TestTheOntologyReallyAllowsThose:
    """REACHABILITY, checked rather than asserted. If a non-text id
    were refused at load, the tests above would be guarding something
    that cannot happen."""

    @pytest.mark.parametrize("data_type", ["decimal", "date", "timestamp", "integer", "string"])
    def test_an_id_field_may_declare_it(self, data_type):
        validate_object_types({"Payment": {
            "id_field": "payment_id",
            "security": {"field": "region"},
            "storage": {"silo": "s", "table": "t", "id_column": "payment_id"},
            "fields": {"payment_id": {"type": "data", "data_type": data_type},
                       "region": {"type": "data"}},
        }})


class TestWhatMustNotChange:
    def test_an_ordinary_entry_is_unaltered(self, log):
        """default=str must only touch values json cannot handle. A
        string id stays a string, an int stays an int."""
        log.log_access("alice", "Customer", "cust_001", "read:Customer.name", True, True)

        entry = _lines(log)[0]
        assert entry["object_id"] == "cust_001"
        assert entry["mac_allowed"] is True
        assert "timestamp" in entry

    def test_an_integer_id_is_not_stringified(self, log):
        log.log_access("alice", "Customer", 42, "read:Customer.name", True, True)

        assert _lines(log)[0]["object_id"] == 42

    def test_a_decimal_id_is_readable_as_its_exact_text(self, log):
        """An operator reading a trace wants the value, not a repr."""
        log.log_access("alice", "Customer", Decimal("49.99"), "read:Customer.name", True, True)

        assert _lines(log)[0]["object_id"] == "49.99"
