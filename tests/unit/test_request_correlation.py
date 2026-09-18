"""
Every access made while serving one request shares an id.

THE MECHANISM ALREADY EXISTED and reached almost nothing.
`RequestContext` carries a `request_id`, `check_access()` stamps it on
every audit line, and `entries_for_request()` reads them back. Its own
docstring says the purpose: "correlates every access decision made
while serving one query".

ONE ROUTE OUT OF THIRTY-NINE CREATED ONE. The Query route did;
Browse did not, so twelve object-reading call sites wrote UNTRACKED
audit lines and "what did this request touch" was unanswerable for
every one of them.

AND `get_object` DROPPED IT ON THE FLOOR. It is a per-field loop
around `get_field`, which accepted a context all along -- the wrapper
simply did not pass one, so a six-field read wrote six unrelated
lines.
"""

import pytest

from core.intermediate_layer.auth import UserRecord
from core.request_context import RequestContext


@pytest.fixture
def mediator(tmp_path):
    """Built against the SHIPPED deployment, deliberately.

    Correlation is a property of the real wiring -- mediator, audit
    log and context agreeing on one field -- so a stub mediator would
    test the stub. A fresh data directory keeps the audit log empty,
    which is what lets a count mean what it says.
    """
    from core.deployment_loader import build_generation, resolve_runtime_paths

    paths = resolve_runtime_paths()
    generation = build_generation(
        paths.config_dir, data_dir=tmp_path, log_dir=tmp_path / "log",
    )
    return generation.mediator


@pytest.fixture
def user():
    return UserRecord("debug", "us-west", "debug")


def test_one_read_of_several_fields_correlates(mediator, user):
    context = RequestContext.new()

    mediator.get_object(user, "Transaction", 1,
                        ["amount", "currency", "category"], context=context)

    entries = mediator.audit_log.entries_for_request(context.request_id, "debug")
    assert len(entries) == 3


def test_two_requests_do_not_mix(mediator, user):
    """THE CONTROL THAT MATTERS. A correlation that grouped everything
    would answer "what did this request touch" with "everything", which
    is the same as not answering."""
    first = RequestContext.new()
    second = RequestContext.new()

    mediator.get_object(user, "Transaction", 1, ["amount", "currency"], context=first)
    mediator.get_object(user, "Transaction", 2, ["amount"], context=second)

    audit = mediator.audit_log
    assert len(audit.entries_for_request(first.request_id, "debug")) == 2
    assert len(audit.entries_for_request(second.request_id, "debug")) == 1


def test_an_id_is_unique_per_context(mediator, user):
    # uuid4 rather than a counter: a counter needs shared state, which
    # is what this design avoids, and it would leak how many requests a
    # deployment has served.
    ids = {RequestContext.new().request_id for _ in range(100)}

    assert len(ids) == 100


def test_a_read_without_a_context_still_works(mediator, user):
    """UNTRACKED IS STILL SERVED. A context is for correlation, not
    authorisation -- a read that cannot be traced must not become a
    read that is refused."""
    assert mediator.get_object(user, "Transaction", 1, ["amount"]) is not None
