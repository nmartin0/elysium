"""Whether each configured SOURCE answers -- the customer's own
databases, never the mirror.

ONE FUNCTION, three callers: startup, /api/silos and /api/health. Before
it, nothing checked at startup (E-13), and the two routes checked the
MEDIATOR's adapters -- which, with read_from_mirror on (the default), are
mirror adapters, whose health_check lists the catalog. Measured: with the
source database DELETED, /api/silos reported it healthy and /api/health
said "reachable".

The failure is still the exception's class name. E-06, the owner's
decision, replaces that with a closed vocabulary -- here, in one place.
"""

from collections.abc import Iterable, Mapping


def source_failures(silo_names: Iterable[str], adapters: Mapping) -> dict[str, str]:
    """{silo: failure} for each source that does not answer. A healthy
    source is absent, so an empty dict means every source answered."""
    failures: dict[str, str] = {}
    for name in sorted(silo_names):
        adapter = adapters.get(name)
        if adapter is None:
            failures[name] = "NotConfigured"
            continue
        try:
            adapter.health_check()
        except Exception as exc:  # any failure is a finding, never a crash
            failures[name] = type(exc).__name__
    return failures
