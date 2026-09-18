"""
Nothing expires Iceberg snapshots, and adding it has a prerequisite.

THE HAZARD, if expiry is added without thought:

    1. A query pins generation N, naming snapshot 12345.
    2. Sync runs twice. 12345 is two versions back.
    3. expire_snapshots reclaims it and DELETES the Parquet files.
    4. Hop 5 of the still-running query scans 12345. Gone.

On CPU-only hardware a query can run for half an hour, so the window is
wide.

WHY THIS IS A GUARD AND NOT AN IMPLEMENTATION. Retention machinery
built before retention exists is speculative work, and the protection
is only meaningful alongside the thing it protects against. This fails
the moment expiry appears, which is exactly when the decision needs
making -- and not before.

THE DECISION, recorded in HOT_RELOAD_PLAN.md step 5h, and TWO rules
rather than one:

  - NEVER reclaim a table's CURRENT snapshot, whatever its age. This is
    the rule Foundry treats as primary -- their retention "will never
    delete transactions that are in the latest view of any branch", and
    the override is documented as "very dangerous" precisely because it
    "may result in the deletion of current data that is still in use".
    It protects every request pinned to the newest snapshot -- the
    common case -- absolutely, with no threshold to tune.
  - EXPIRE BY AGE with a margin longer than the longest possible
    request, covering the narrower case of a request pinned to a
    snapshot a sync has since superseded. Foundry has an age selector
    too, so this is precedent rather than invention.

NOT by coordinating with live generations: expiry would run in a
different PROCESS from the server, so a Python-side refcount of live
generations is invisible to it and protects nothing.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_EXPIRY_CALLS = ("expire_snapshots", "remove_snapshot", "expire_snapshot")


def _sources():
    for directory in ("core", "scripts", "api", "adapters"):
        for path in (ROOT / directory).rglob("*.py"):
            yield path, path.read_text()


def test_nothing_expires_snapshots_without_an_age_margin():
    # When this fails, read HOT_RELOAD_PLAN.md step 5h before making it
    # pass. The requirement is an age threshold exceeding the longest
    # possible request by an order of magnitude -- bounded by max_hops
    # and the request timeout, so the case becomes unreachable rather
    # than merely unlikely.
    offenders = [
        f"{path.relative_to(ROOT)}: {call}"
        for path, source in _sources()
        for call in _EXPIRY_CALLS
        if call in source and "older_than" not in source and "RETENTION_MARGIN" not in source
    ]

    assert not offenders, (
        f"snapshot expiry added without an age margin: {offenders}. A pinned "
        f"generation's snapshot can be deleted mid-read -- see HOT_RELOAD_PLAN.md "
        f"step 5h for why coordinating with live generations does NOT work."
    )


def test_the_guard_would_actually_notice():
    # A guard that cannot fire is worse than none: it reads as
    # protection while protecting nothing. Proves the detection works
    # against a synthetic source rather than trusting the loop above.
    fake = "table.expire_snapshots().commit()"

    assert any(call in fake for call in _EXPIRY_CALLS)
    assert "older_than" not in fake
