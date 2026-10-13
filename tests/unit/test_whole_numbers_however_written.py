"""
An integer field reads a whole number however it was written, and never
truncates one that is not whole (PA001-F3).

BRONZE STORES EVERY VALUE AS TEXT, so a source's float 5.0 reaches
silver as "5.0" -- which was refused, where the same 5.0 read directly
was accepted. Fixing that found the worse half: a native 5.5 was
accepted and became 5, its fraction dropped without a word.
"""

from decimal import Decimal

import pytest

from core.ontology.field_types import coerce


@pytest.mark.parametrize("value, expected", [
    (5.0, 5), ("5.0", 5), ("-12.000", -12), (Decimal("5.0"), 5), ("5", 5), ("1e3", 1000),
])
def test_a_whole_number_is_read_however_it_is_written(value, expected):
    assert coerce(value, "integer") == expected


@pytest.mark.parametrize("value", [5.5, "5.5", Decimal("5.5"), "0.001", float("nan")])
def test_a_fraction_is_refused_not_truncated(value):
    with pytest.raises(ValueError, match="not a whole number"):
        coerce(value, "integer")


def test_the_text_and_the_native_value_now_agree():
    """The bronze round trip: what the source sent, and the text bronze
    stores for it, coerce to the same thing."""
    from core.mirror.bronze_text import bronze_text

    for native in (5.0, 7.0, -3.0, 5.5):
        try:
            direct = coerce(native, "integer")
        except ValueError:
            direct = "refused"
        try:
            through_bronze = coerce(bronze_text(native), "integer")
        except ValueError:
            through_bronze = "refused"
        assert direct == through_bronze, native
