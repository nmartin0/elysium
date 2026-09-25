"""A value the pipeline produced is not written back to the source
(R50, and the write-path half of CONCERN-3).

THE LOOP, CONCRETELY. Silver standardises on the way in -- NFC, trim,
collapse whitespace (patch 337). So a source row holding
`"  Ada   Okafor "` is SERVED as `"Ada Okafor"`. A form prefilled from
the served value, saved by somebody who edited a DIFFERENT field,
proposes `name = "Ada Okafor"`. Before this guard the write path put
that into the customer's own row: a transformation nobody chose,
attributed to somebody who never typed it, and the original gone.

NOTHING PREVIOUSLY NOTICED. `_expected_current_values_for()` reads
through `_adapter_mediator`, which is bound to the SOURCE, so the
lost-update check compared source against source and passed. The
proposed value was never compared against what the caller was shown.

THE RULE: different from the SOURCE, identical to the SERVED value.
A field equal to the source is a no-op and is left alone. A field
equal to neither is a real edit and is kept. Only the echo is dropped,
and only that field -- refusing the whole action would block the
legitimate edit it arrived alongside, which is the common case.

WHY THESE TESTS DRIVE THE REAL METHOD rather than a whole deployment.
The condition needs source and served to DISAGREE, which means a
synced lake with a standardisation rule that actually fired. Building
one inside a unit test would be testing the pipeline, not the guard;
the suite already runs the write path end to end against the shipped
fixture and stayed green through this change, with no test edited.
What is exercised here is the decision itself, with the two readers
reporting exactly the disagreement that makes the loop possible.
"""

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import WriteMediator

SOURCE = "  Ada   Okafor "      # what the customer's row holds
SERVED = "Ada Okafor"           # what silver standardised it into


class _SpyAuditLog:
    def __init__(self):
        self.skipped: list[tuple] = []

    def log_echoed_value_not_written(self, user_id, object_type, object_id, field_name):
        self.skipped.append((user_id, object_type, object_id, field_name))


class _ServedReader:
    """The READ mediator: answers from published gold."""

    def __init__(self, audit_log, served: dict):
        self.audit_log = audit_log
        self._served = served

    def get_field(self, user_record, object_type, object_id, field_name):
        return self._served.get(field_name)


def _mediator(audit_log, served: dict) -> WriteMediator:
    mediator = object.__new__(WriteMediator)
    # audit_log is a PROPERTY returning self.mediator.audit_log.
    mediator.mediator = _ServedReader(audit_log, served)
    return mediator


@pytest.fixture
def user():
    return UserRecord(user_id="alice", security_value="us-west", role_name="agent")


@pytest.fixture
def audit():
    return _SpyAuditLog()


def _drop(mediator, user, changes, source_values):
    return mediator._drop_values_the_pipeline_produced(
        user, "Customer", "cust_001", changes, source_values, "UpdateCustomer"
    )


class TestTheEcho:
    def test_a_value_equal_to_the_served_one_is_not_written(self, user, audit):
        mediator = _mediator(audit, {"name": SERVED})

        kept = _drop(mediator, user, {"name": SERVED, "city": "Lagos"}, {"name": SOURCE, "city": "Abuja"})

        assert "name" not in kept, "the standardised value was written back to the source"
        assert kept == {"city": "Lagos"}, "the real edit alongside it was lost"

    def test_and_it_is_audited_by_name(self, user, audit):
        """A field silently not written is worse than one refused --
        the caller believes they saved it."""
        mediator = _mediator(audit, {"name": SERVED})

        _drop(mediator, user, {"name": SERVED, "city": "Lagos"}, {"name": SOURCE, "city": "Abuja"})

        assert audit.skipped == [("alice", "Customer", "cust_001", "name")]


class TestWhatMustStillGetThrough:
    """THE OPPOSITE DIRECTION, and it is most of the surface. A guard
    that dropped everything would satisfy the tests above while
    breaking every write in the product."""

    def test_a_real_edit_is_kept(self, user, audit):
        mediator = _mediator(audit, {"name": SERVED})

        kept = _drop(mediator, user, {"name": "Ada Okonkwo"}, {"name": SOURCE})

        assert kept == {"name": "Ada Okonkwo"}
        assert audit.skipped == []

    def test_a_value_equal_to_the_source_is_a_no_op_and_is_kept(self, user, audit):
        """Not an echo. The caller submitted the source's own value, so
        writing it changes nothing and dropping it would be a
        behaviour change for no benefit."""
        mediator = _mediator(audit, {"name": SERVED})

        kept = _drop(mediator, user, {"name": SOURCE}, {"name": SOURCE})

        assert kept == {"name": SOURCE}
        assert audit.skipped == []

    def test_a_field_with_no_source_value_read_is_kept(self, user, audit):
        mediator = _mediator(audit, {"name": SERVED})

        kept = _drop(mediator, user, {"nickname": "Ada"}, {})

        assert kept == {"nickname": "Ada"}

    def test_an_unreadable_field_is_kept(self, user, audit):
        """FAILS TO TODAY'S BEHAVIOUR, NOT OPEN. get_field() returns
        None for a field the caller may not read, so it cannot be
        compared. Keeping it is the pre-R50 behaviour and no weaker --
        this guard protects DATA; MAC and RBAC already ran above."""
        mediator = _mediator(audit, {})  # nothing readable

        kept = _drop(mediator, user, {"name": SERVED}, {"name": SOURCE})

        assert kept == {"name": SERVED}
        assert audit.skipped == []

    def test_where_source_and_served_agree_nothing_is_dropped(self, user, audit):
        """THE ORDINARY DEPLOYMENT. With no standardisation rule firing,
        source and served are identical and this guard must be inert --
        which is why the whole suite stayed green."""
        mediator = _mediator(audit, {"name": "Ada Okafor"})

        kept = _drop(mediator, user, {"name": "Ada Okonkwo"}, {"name": "Ada Okafor"})

        assert kept == {"name": "Ada Okonkwo"}
        assert audit.skipped == []


class TestAnUpdateThatWouldChangeNothing:
    def test_is_refused_rather_than_written_empty(self, user, audit):
        """An update whose every field was an echo has nothing left. An
        empty change set must not reach the write log -- F-27 is what a
        fabricated entry with empty changes costs."""
        mediator = _mediator(audit, {"name": SERVED})

        with pytest.raises(ValueError, match="would change nothing"):
            _drop(mediator, user, {"name": SERVED}, {"name": SOURCE})

    def test_and_the_message_says_why(self, user, audit):
        mediator = _mediator(audit, {"name": SERVED})

        with pytest.raises(ValueError) as raised:
            _drop(mediator, user, {"name": SERVED}, {"name": SOURCE})

        message = str(raised.value)
        assert "already shown to the caller" in message
        assert "source holds a different form" in message
