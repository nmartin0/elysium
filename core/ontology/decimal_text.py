"""A decimal as the text an API answer carries (PA001-G12).

TWO THINGS WENT WRONG, by route.

  A route WITHOUT a response model went through FastAPI's
  jsonable_encoder, whose decimal_encoder turns Decimal("10.500000000")
  into the float 10.5 -- a different number in general, since
  Decimal("12345678901234567.89") does not survive the trip, and money
  is exactly what a field is declared decimal for.

  A route WITH one went through pydantic, which keeps the value exact
  but at the STORAGE scale: silver holds decimal(38, 9), so a field the
  ontology declares with `decimal_places: 2` arrived as "10.500000000"
  -- while the live path, reading the customer's database, gave
  "10.50". The same value read two ways (G12's "scale differs by path").

THE RULE HERE: a string, EXACT, at the DECLARED scale where one is
declared. Exact wins over declared: a value holding more places than
the field declares keeps them, because rounding at the API would send a
different number from the one stored and the one a filter compares
against. `decimal_places` pads; it never truncates. (The UI's
formatValue rounds for DISPLAY, which is its business; the prompt's
render_value rounds for the model; neither changes what is sent here.)

WHY A STRING: JSON has one number type and every client parses it as a
binary float. A string is the only way to hand over the exact value.
"""

import decimal

DECIMAL_PLACES = "decimal_places"

#: Wide enough for any decimal(38, s) silver holds, plus padding. The
#: default context's 28 digits would ROUND a 38-digit value inside
#: normalize(), which is the opposite of this module's job.
_EXACT = decimal.Context(prec=80)


def decimal_text(value: decimal.Decimal, places: int | None = None) -> str:
    """Exact, in plain notation, padded to `places` if declared.

    `10.500000000` -> "10.5", or "10.50" with places=2.
    `10.555`, places=2 -> "10.555": never rounded.
    `1E+2` -> "100": plain notation, which every client parses.
    NaN and infinities have no plain form; their str() is returned.
    """
    if not value.is_finite():
        return str(value)
    exact = value.normalize(_EXACT)
    if places is not None:
        try:
            wanted = -int(places)
        except (TypeError, ValueError):
            wanted = None
        exponent = exact.as_tuple().exponent
        if wanted is not None and isinstance(exponent, int) and exponent > wanted:
            # FEWER places than declared: padding adds zeros only, so
            # the quantize is exact by construction.
            exact = exact.quantize(decimal.Decimal(1).scaleb(wanted), context=_EXACT)
    return f"{exact:f}"


def exact_decimals(values: dict, field_defs: dict | None) -> dict:
    """`values` ({field: value}) with every Decimal as decimal_text at
    its field's declared scale; everything else unchanged."""
    field_defs = field_defs or {}
    out = {}
    for name, value in values.items():
        if isinstance(value, decimal.Decimal):
            value = decimal_text(value, (field_defs.get(name) or {}).get(DECIMAL_PLACES))
        out[name] = value
    return out
