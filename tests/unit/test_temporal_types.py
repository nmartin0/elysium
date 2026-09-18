"""
Three temporal types, because a date is not an instant.

MIRRORING ICEBERG, because the mirror IS Iceberg and a type we invent
has to be emulated -- which is where guarantees quietly disappear.

    date         no time, no zone, NEVER converted
    timestamp    a wall-clock reading with no zone, stored as given
    timestamptz  a true instant, stored UTC

THE BUG THIS REPLACES was measured: dates stored as strings compare
lexically, so '2026-1-5' sorts AFTER '2026-02-03' and '01/05/2026'
sorts by month with the year ignored. A date_range filter for "after
February" returned a January row and said nothing.
"""

import datetime

import pyarrow as pa
import pytest

from core.ontology.field_types import arrow_type_for, coerce


class TestADateIsNotAnInstant:
    def test_a_bare_date_reads_as_a_date(self):
        assert coerce("2026-03-12", "date") == datetime.date(2026, 3, 12)

    def test_a_time_of_day_is_refused(self):
        """fromisoformat HAPPILY TURNS '2026-03-12' INTO MIDNIGHT, so
        accepting a datetime here would silently discard a real time --
        and silently invent one on the way back out."""
        with pytest.raises(ValueError, match="time of day"):
            coerce("2026-03-12 14:30:00", "date")

    def test_a_date_is_never_converted(self):
        """A BIRTHDAY DOES NOT MOVE. Converting a date "to UTC" is the
        classic bug where somebody's birthday shifts a day for readers
        in Auckland."""
        assert coerce("2026-01-01", "date") == datetime.date(2026, 1, 1)


class TestAWallClockReadingIsNotAnInstant:
    def test_a_naive_timestamp_is_stored_as_given(self):
        assert coerce("2026-03-12 14:30:00", "timestamp") == datetime.datetime(
            2026, 3, 12, 14, 30,
        )

    def test_an_offset_is_refused(self):
        """Dropping the offset would turn a KNOWN moment into an
        unknown one -- a loss dressed up as a conversion."""
        with pytest.raises(ValueError, match="real instant"):
            coerce("2026-03-12T14:30:00Z", "timestamp")


class TestAnInstantIsStoredUTC:
    def test_a_zulu_time_is_utc(self):
        assert coerce("2026-03-12T14:30:00Z", "timestamptz") == datetime.datetime(
            2026, 3, 12, 14, 30, tzinfo=datetime.UTC,
        )

    def test_an_offset_is_converted_to_utc(self):
        # Iceberg's spec: "values are stored as UTC and do not retain a
        # source time zone".
        assert coerce("2026-03-12T14:30:00-05:00", "timestamptz") == datetime.datetime(
            2026, 3, 12, 19, 30, tzinfo=datetime.UTC,
        )

    def test_a_naive_value_is_not_promoted_by_guessing(self):
        """ASSUMING UTC IS A GUESS, and assuming the server's zone is
        worse: it makes the same data mean different things on two
        machines, which is the coupling storing UTC exists to
        remove."""
        with pytest.raises(ValueError, match="no UTC offset"):
            coerce("2026-03-12 14:30:00", "timestamptz")


class TestADeclaredZonePromotes:
    def test_a_field_may_state_its_source_zone(self):
        # Someone had to write the zone down, which is the difference
        # between knowing and assuming.
        assert coerce(
            "2026-03-12 14:30:00", "timestamptz", "America/New_York",
        ) == datetime.datetime(2026, 3, 12, 18, 30, tzinfo=datetime.UTC)

    def test_daylight_saving_is_handled_by_the_zone(self):
        """MARCH IS EDT (-4) AND JANUARY IS EST (-5). A fixed offset
        would be wrong for half the year, which is why the declaration
        is an IANA zone rather than a number."""
        summer = coerce("2026-07-12 14:30:00", "timestamptz", "America/New_York")
        winter = coerce("2026-01-12 14:30:00", "timestamptz", "America/New_York")

        assert summer.hour == 18
        assert winter.hour == 19

    def test_an_unknown_zone_is_refused(self):
        with pytest.raises(ValueError, match="not a known IANA timezone"):
            coerce("2026-03-12 14:30:00", "timestamptz", "Mars/Olympus")

    def test_a_declared_zone_does_not_override_a_real_offset(self):
        # The value already names an instant; the declaration is for
        # values that do not.
        assert coerce(
            "2026-03-12T14:30:00Z", "timestamptz", "America/New_York",
        ) == datetime.datetime(2026, 3, 12, 14, 30, tzinfo=datetime.UTC)


class TestFormatsAreNotGuessed:
    def test_a_non_iso_format_is_refused(self):
        """'01/05/2026' IS JANUARY IN ONE COUNTRY AND MAY IN ANOTHER,
        and nothing in the value says which. Accepting it would make
        the mirror's meaning depend on where it was built."""
        with pytest.raises(ValueError, match="not ISO-8601"):
            coerce("01/05/2026", "date")

    def test_the_unpadded_case_that_sorted_wrongly(self):
        # '2026-1-5' sorted AFTER '2026-02-03' as a string. As a date
        # it either parses correctly or is refused -- never silently
        # mis-ordered.
        with pytest.raises(ValueError, match="not ISO-8601"):
            coerce("2026-1-5", "date")


class TestAlreadyTypedValuesPassThrough:
    def test_a_date_object_is_accepted(self):
        """psycopg HANDS BACK `date` FOR A DATE COLUMN, so a live read
        needs no parsing. SQLite returns strings for all three shapes,
        so a sync through bronze always parses. Both paths must reach
        the same answer."""
        assert coerce(datetime.date(2026, 3, 12), "date") == datetime.date(2026, 3, 12)

    def test_an_aware_datetime_object_is_accepted(self):
        value = datetime.datetime(2026, 3, 12, 14, 30, tzinfo=datetime.UTC)

        assert coerce(value, "timestamptz") == value


class TestTheyFitWhereTheyAreStored:
    def test_each_maps_to_its_arrow_type(self):
        assert arrow_type_for("date") == pa.date32()
        assert arrow_type_for("timestamp") == pa.timestamp("us")
        assert arrow_type_for("timestamptz") == pa.timestamp("us", tz="UTC")

    def test_every_accepted_value_survives_arrow(self):
        # THE CONTROL THAT MATTERS, as with decimal: a value this
        # coercer accepts must fit, or the drift report loses the one
        # thing that makes it useful.
        pa.array([coerce("2026-03-12", "date")], type=pa.date32())
        pa.array(
            [coerce("2026-03-12 14:30:00", "timestamp")], type=pa.timestamp("us"),
        )
        pa.array(
            [coerce("2026-03-12T14:30:00Z", "timestamptz")],
            type=pa.timestamp("us", tz="UTC"),
        )

    def test_null_stays_null(self):
        for data_type in ("date", "timestamp", "timestamptz"):
            assert coerce(None, data_type) is None
