"""A field the reader may know exists and not read (DEV_UI 9.7, E4).

The UI's FieldValue tells "Not permitted" from "not set" by the
schema's `readable`, because the VALUE cannot: a discover-only field
arrives as null, the same as an empty one. These pin the two halves of
that contract over HTTP, and the one place the server ordered by such a
field anyway.
"""

from tests.conftest import read_audit_log
from tests.integration.test_api import _login  # noqa: F401


def _as_one_who_sees_email_exists(client):
    client.app.state.user_directory.create_user(
        "nosy", "correct-pw", "us-west", "customer_service_sees_email_exists")
    _login(client, "nosy", "correct-pw")


def test_the_schema_says_unreadable_and_the_row_says_null(client):
    """Both halves FieldValue relies on. If the server started omitting
    the key instead, Browse would render nothing in the cell; if the
    schema stopped saying `readable: false`, it would render a dash and
    the column would read as nobody having an email address."""
    _as_one_who_sees_email_exists(client)
    schema = client.get("/api/me/visible-schema").json()
    assert schema["Customer"]["fields"]["email"]["readable"] is False

    rows = client.get("/api/objects/Customer/search?q=").json()["results"]
    assert rows, "the fixture should give this role some customers"
    assert all(row["fields"].get("email", "absent") is None for row in rows)


def _denied_email_reads(client) -> int:
    log_dir = client.app.state.runtime_paths.log_dir
    return sum(
        1 for entry in read_audit_log(log_dir)
        if entry.get("action") == "read:Customer.email" and entry.get("allowed") is False
    )


def test_sorting_by_it_is_ignored_and_reads_nothing_more(client):
    """Ordering by a discover-only field ordered every matching row by
    None -- after one DENIED read per row, each its own audit record. A
    sort request should not look like hundreds of attempts to read a
    field the caller is not cleared for."""
    _as_one_who_sees_email_exists(client)

    before = _denied_email_reads(client)
    plain = client.get("/api/objects/Customer/search?q=&page_size=5").json()
    after_plain = _denied_email_reads(client)

    sorted_ = client.get("/api/objects/Customer/search?q=&page_size=5&order_by=email:desc").json()
    after_sorted = _denied_email_reads(client)

    assert len(plain["results"]) >= 2, "an order needs two rows to mean anything"
    assert after_plain > before, "the page should read (and be denied) email per row"
    assert [r["id"] for r in sorted_["results"]] == [r["id"] for r in plain["results"]]
    # The page itself still asks for email per row it shows, and is
    # denied -- that is the summary read, unchanged. The sort adds none.
    assert after_sorted - after_plain == after_plain - before
