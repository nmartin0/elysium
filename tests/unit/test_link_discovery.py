"""
Columns that look like links nobody declared (R54).

Inclusion dependencies against each type's ids: a candidate when at
least 95% of a column's distinct values are ids of some type. Declared
links, ids, the security column and low-cardinality columns are left
out; a name hint ranks, and nothing is applied.
"""

from core.mirror.link_discovery import discover

SCHEMA = {
    "Account": {
        "storage": {"silo": "s", "table": "accounts", "id_column": "account_id"},
        "id_field": "account_id",
        "security": {"field": "region"},
        "fields": {"region": {"type": "data"}, "owner": {"type": "data"}},
    },
    "Payment": {
        "storage": {"silo": "s", "table": "payments", "id_column": "payment_id"},
        "id_field": "payment_id",
        "fields": {
            "account_ref": {"type": "data"},          # an undeclared link
            "invoice_id": {"type": "link", "target": "Account", "cardinality": "one"},
            "status": {"type": "data"},
            "tier": {"type": "data"},
            "amount": {"type": "data"},
        },
    },
}

ACCOUNTS = [{"account_id": f"a{n}", "region": "us", "owner": f"o{n}"} for n in range(10)]
PAYMENTS = [{"payment_id": f"p{n}", "account_ref": f"a{n % 8}", "invoice_id": f"a{n % 5}",
             "status": ["new", "paid"][n % 2], "tier": ["a0", "a1"][n % 2],
             "amount": str(10 + n)} for n in range(40)]


def _rows(silo, table):
    return {"accounts": ACCOUNTS, "payments": PAYMENTS}.get(table)


def _found():
    return {(c.object_type, c.column, c.target_type): c for c in discover(SCHEMA, _rows)}


def test_an_undeclared_link_is_found():
    candidate = _found()[("Payment", "account_ref", "Account")]

    assert (candidate.distinct, candidate.unmatched, candidate.coverage) == (8, 0, 1.0)
    assert candidate.field == "account_ref"


def test_a_declared_link_is_not_suggested_again():
    assert ("Payment", "invoice_id", "Account") not in _found()


def test_a_column_of_few_values_is_not_a_link():
    """tier holds two values, and both happen to be Account ids -- the
    accident MIN_DISTINCT exists for: two values are "included" in
    almost anything."""
    assert not any(key[1] == "tier" for key in _found())


def test_values_that_are_not_ids_are_not_a_link():
    """THE CONTROL: amount's values appear in no id column."""
    assert not any(key[1] == "amount" for key in _found())


def test_a_few_orphans_still_qualify_and_are_counted():
    """Partial: one dangling value in twenty must not hide a link."""
    dirty = PAYMENTS + [{"payment_id": "px", "account_ref": "a-gone", "invoice_id": "a1",
                         "status": "new", "amount": "1"}]
    rows = {"accounts": ACCOUNTS + [{"account_id": f"a{n}"} for n in range(10, 30)],
            "payments": dirty + [{"payment_id": f"q{n}", "account_ref": f"a{n}",
                                  "invoice_id": "a1", "status": "new", "amount": "1"}
                                 for n in range(10, 30)]}

    candidate = {(c.object_type, c.column): c for c in discover(SCHEMA, lambda s, t: rows.get(t))}[
        ("Payment", "account_ref")]

    assert candidate.unmatched == 1 and candidate.coverage >= 0.95


def test_named_like_the_target_ranks_first():
    found = discover(SCHEMA, _rows)

    assert found[0].column == "account_ref" and found[0].named_like_target
