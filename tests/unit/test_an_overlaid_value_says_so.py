"""Which fields a read serves from the write log (R67b).

An approved write's value is served over the mirror's older copy --
read-your-writes -- and nothing on the ordinary read path said so.
DataMediator.overlaid_fields names the fields and the kind; the object
detail route carries it and the object page shows it.
"""

from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter

SINCE = "2000-01-01T00:00:00+00:00"


def _mediator(log, mirror_synced_at=SINCE):
    mediator = DataMediator.__new__(DataMediator)
    mediator.write_log = log
    mediator.mirror_synced_at = mirror_synced_at
    mediator.mirror_synced_at_by_type = {}
    return mediator


def test_an_approved_write_still_being_applied_is_pending(tmp_path):
    log = WriteLogWriter(tmp_path / "wl.db")
    log.log_pending_update("Account", "acc1", {"balance": 900}, {"balance": 1000}, "u", "t")

    assert _mediator(log).overlaid_fields("Account", "acc1", ["balance"]) == {"balance": "pending"}


def test_an_applied_write_the_mirror_has_not_caught_up_with_is_unsynced(tmp_path):
    log = WriteLogWriter(tmp_path / "wl.db")
    log.mark_applied(log.log_pending_update("Account", "acc1", {"balance": 900},
                                            {"balance": 1000}, "u", "t"))

    assert _mediator(log).overlaid_fields("Account", "acc1", ["balance"]) == {"balance": "unsynced"}


def test_only_the_fields_asked_about(tmp_path):
    """The route asks only about fields the caller was given a value for."""
    log = WriteLogWriter(tmp_path / "wl.db")
    log.log_pending_update("Account", "acc1", {"balance": 900}, {"balance": 1000}, "u", "t")

    assert _mediator(log).overlaid_fields("Account", "acc1", ["owner"]) == {}


def test_nothing_without_a_write(tmp_path):
    """THE CONTROL: an object nobody wrote to says nothing."""
    log = WriteLogWriter(tmp_path / "wl.db")

    assert _mediator(log).overlaid_fields("Account", "acc1", ["balance"]) == {}
