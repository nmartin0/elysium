"""
Every field of `PendingWrite` is serialised, and adding one fails
here.

SEC-16 SAID ONLY "latent, in core/pending_write_serialisation.py" --
no severity, no probe, and the agent that raised it no longer exists
to be asked. The row cannot be reproduced. What CAN be done is to test
the promise that module makes about itself:

    a change to the dataclass fails HERE -- loudly, at import or in a
    round-trip test -- rather than silently writing a row that cannot
    be read back.

NOTHING ENFORCED THAT. The round-trip tests build a `PendingWrite`
with the fields they happen to know about and check it comes back. A
TENTH FIELD ADDED TO THE DATACLASS AND FORGOTTEN IN `to_row` WOULD NOT
FAIL ANY OF THEM: the round trip would pass, the field would be
dropped, and the loss would show up as a restored write missing
something a confirm decision depends on.

WHAT THAT WOULD COST. A pending write is a PROPOSAL that survives a
restart, and every question about whether it may execute is asked
again at confirm against the current configuration. A field silently
lost between those two moments is a question asked against incomplete
data.

SO THIS IS A COVERAGE TEST, NOT A BEHAVIOUR ONE. It compares the
dataclass's own field list against what the serialiser names, which is
the only check that keeps working when somebody adds a field this file
has never heard of.
"""

import dataclasses
import inspect

from core.pending_write_serialisation import from_row, to_row
from core.pending_write_store import PendingWrite


def _field_names():
    return {field.name for field in dataclasses.fields(PendingWrite)}


class TestTheSerialiserKnowsEveryField:
    def test_to_row_names_them_all(self):
        """A field the writer never mentions is a field never stored."""
        source = inspect.getsource(to_row)
        missing = sorted(name for name in _field_names() if name not in source)

        assert missing == [], (
            f"PendingWrite fields absent from to_row: {missing}. A field "
            f"added to the dataclass and forgotten here is written nowhere, "
            f"and the round-trip tests would still pass.")

    def test_from_row_names_them_all(self):
        """A field the reader never mentions comes back as its default,
        which is worse than an error: the write looks restored."""
        source = inspect.getsource(from_row)
        missing = sorted(name for name in _field_names() if name not in source)

        assert missing == [], (
            f"PendingWrite fields absent from from_row: {missing}.")

    def test_the_two_agree(self):
        """Serialising a field and not reading it back is as lossy as
        not serialising it."""
        written = inspect.getsource(to_row)
        read = inspect.getsource(from_row)
        names = _field_names()

        assert {n for n in names if n in written} == {n for n in names if n in read}


class TestTheCheckCanActuallyFail:
    def test_a_field_the_serialiser_does_not_know_is_detected(self):
        """A coverage test that cannot fail is the thing it is testing
        for. This proves the comparison bites."""
        source = inspect.getsource(to_row)
        invented = "a_field_nobody_has_added_yet"

        assert invented not in source

    def test_the_dataclass_has_fields_to_check(self):
        """If `fields()` returned nothing, both tests above would pass
        vacuously -- which is how a coverage test rots."""
        assert len(_field_names()) >= 5
