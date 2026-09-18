"""
A field may state the zone its source records time in.

WHY IT IS DECLARED RATHER THAN INFERRED. A source that hands back
'2026-03-12 14:30:00' has given a wall-clock reading in an unstated
place, not an instant. Assuming UTC is a guess, and assuming the
server's zone is worse: it makes the same data mean different things
on two machines, which is the coupling storing UTC exists to remove.

Someone had to write the zone down. That is the whole difference
between knowing and assuming.
"""

import pytest

from core.ontology.field_types import split_declared_type
from core.ontology.object_type_validation import _validate_field_timezone


def _check(field_info, declared="timestamptz"):
    _validate_field_timezone("Thing", "seen", field_info, declared)


class TestTheDeclaration:
    def test_a_valid_iana_zone_is_accepted(self):
        _check({"timezone": "America/New_York"})

    def test_no_timezone_is_the_normal_case(self):
        _check({})

    def test_an_unknown_zone_is_refused_at_config_load(self):
        """NOT AT THE FIRST ROW THAT NEEDS IT. A typo would otherwise
        surface during a sync, hours later, as a drift report about
        data that is perfectly fine."""
        with pytest.raises(ValueError, match="not a known IANA zone"):
            _check({"timezone": "Mars/Olympus"})

    def test_an_offset_is_refused_with_advice(self):
        """'-05:00' IS WRONG FOR HALF THE YEAR in any zone that
        observes daylight saving. The message says to use a name."""
        with pytest.raises(ValueError, match="not an offset"):
            _check({"timezone": "-05:00"})

    def test_a_non_string_is_refused(self):
        with pytest.raises(ValueError, match="not a string"):
            _check({"timezone": 5})


class TestItBelongsOnlyOnAnInstant:
    @pytest.mark.parametrize("declared", ["date", "timestamp", "string"])
    def test_other_types_refuse_it(self, declared):
        """A `date` has no time to place, and a `timestamp` is
        DELIBERATELY naive -- promoting it would defeat the point of
        declaring it. Silently ignoring the key would let an author
        believe their dates were being converted."""
        with pytest.raises(ValueError, match="only `timestamptz`"):
            _check({"timezone": "America/New_York"}, declared)


class TestTheTwoTravelTogether:
    def test_a_type_and_its_zone_split_apart(self):
        assert split_declared_type("timestamptz@America/New_York") == (
            "timestamptz", "America/New_York",
        )

    def test_a_plain_type_has_no_zone(self):
        assert split_declared_type("integer") == ("integer", None)

    def test_the_split_is_in_one_place(self):
        """A FIRST VERSION SPLIT IT INLINE where the coercer needed it,
        and left arrow_type_for to receive the whole string and refuse
        it -- breaking the sync's SCHEMA BUILDER rather than the
        coercion, several files from the change.

        Both callers now come here, so the encoding is known in exactly
        one place.
        """
        from core.ontology.field_types import arrow_type_for

        data_type, _ = split_declared_type("timestamptz@Europe/London")

        assert arrow_type_for(data_type) is not None
