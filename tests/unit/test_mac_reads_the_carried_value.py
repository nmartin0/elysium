"""
MAC reads the carried column, so a later stage cannot change who sees
what by touching the data.

`LLM3-3`'s second half. The first copied the value into `_security` at
sync; this one makes MAC read it.

PROVEN RATHER THAN ARGUED. On a real deployment I overwrote every
`region` value in `gold.Customer` with "MANGLED-BY-ENRICHMENT",
leaving `_security` alone -- which is what a careless enrichment stage
would do -- and MAC partitioned exactly as before: us-west saw 2
customers, us-east saw 1. Before this patch both compartments would
have collapsed, because every row's security value would have become
the same string.

RESOLVED ON THE DECLARED FIELD. `_security` is not a declared field
and has no storage of its own; `with_lineage` writes it into the SAME
table the declared field lives in, so that field is what says which
adapter holds it. I called `_resolve_shared_storage` wrongly twice
before reading it -- it takes FIELD NAMES, and passing an object id
made it iterate the string and `KeyError` on the first character.

THE FALLBACK IS NOT A WEAKENING. A deployment reading live sources has
no `_security`, because it has no sync -- and therefore no pipeline
that could rewrite the value between the source and the read. The
thing the column protects against does not exist there. Measured:
reading it unconditionally failed 146 tests, every one a fixture
reading an adapter directly.

NO NEW STALENESS, which was my own objection and it did not survive
checking: the mediator reads through `GoldConnector`, so MAC has
always seen a published snapshot rather than live data. A write
reaches MAC at the next sync either way.
"""

from pathlib import Path

SOURCE = Path("core/ontology/mediator.py").read_text()


def _security_value_body():
    i = SOURCE.index("def _get_security_value")
    return SOURCE[i:SOURCE.index("\n    def ", i + 10)]


class TestTheCarriedColumnIsPreferred:
    def test_it_is_read_before_the_declared_field(self):
        """ORDER IS THE PROPERTY. A mirror-backed read must never
        consult the data column."""
        body = _security_value_body()
        carried = body.index("SECURITY_COLUMN,")
        declared = body.index("_read_field_with_log_check(\n", carried)

        assert carried < declared

    def test_the_carried_read_is_guarded(self):
        """A direct-read adapter says "no such column" in its own way.
        That is "there is no carried value here", not a fault."""
        body = _security_value_body()

        assert "except Exception:" in body
        assert "carried = None" in body

    def test_it_falls_through_rather_than_returning_none(self):
        """A missing carried column must reach the declared field, not
        answer "no compartment" -- which would make every object in a
        direct-read deployment invisible."""
        body = _security_value_body()

        assert "if carried is not None:" in body
        assert "return carried" in body


class TestWhereTheAdapterComesFrom:
    def test_it_resolves_on_the_declared_field(self):
        """`_security` has no storage declaration of its own. The
        declared field's storage is where `with_lineage` put it."""
        body = _security_value_body()
        i = body.index("SECURITY_COLUMN,")
        before = body[:i]

        assert "_resolve_shared_storage(\n                object_type, [field_name])" in before \
            or "_resolve_shared_storage(object_type, [field_name])" in before

    def test_the_second_argument_is_a_list(self):
        """It takes FIELD NAMES. Passing an object id makes it iterate
        the string -- `KeyError: 'c'` on the first character of
        'cust_001', which is how I found out."""
        for call in ("[field_name]", "[via_field]"):
            assert f"_resolve_shared_storage(object_type, {call})" in SOURCE \
                or f"object_type, {call})" in SOURCE


class TestTheLayering:
    def test_the_constant_comes_from_the_leaf(self):
        """`core/ontology` may not import `core/mirror` -- the contract
        refused it, correctly: the mediator should not depend on how
        the lake is built."""
        assert "from core.carried_columns import SECURITY_COLUMN" in SOURCE
        assert "from core.mirror.lineage import SECURITY_COLUMN" not in SOURCE


class TestViaFieldIsUnaffected:
    def test_a_linked_type_still_resolves_through_its_link(self):
        """A type secured through `via_field` reads its value from a
        DIFFERENT type's row, so there is no column on this table to
        carry and nothing here should change."""
        body = _security_value_body()
        i = body.index('if "via_field" in security:')

        assert "SECURITY_COLUMN" not in body[i:]
