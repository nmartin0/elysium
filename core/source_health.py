"""Whether each configured SOURCE answers -- the customer's own
databases, never the mirror.

ONE FUNCTION, three callers: startup, /api/silos and /api/health. Before
it, nothing checked at startup (E-13), and the two routes checked the
MEDIATOR's adapters -- which, with read_from_mirror on (the default), are
mirror adapters, whose health_check lists the catalog. Measured: with the
source database DELETED, /api/silos reported it healthy and /api/health
said "reachable".

THE FAILURE IS A WORD FROM A CLOSED LIST (E-06, decided by the owner
14 Oct). It was the exception's class name -- "OperationalError" -- which
said little to the person reading it and named the library underneath.
Now every failure is one of FAILURE_KINDS, decided here in one place;
the class and message, which can carry a host or a path, go only to the
operator's log, through `details`.
"""

from collections.abc import Iterable, Mapping

#: Every word a failure can be reported as. Closed: an unrecognised
#: failure is "other", never a new word made up on the spot.
NOT_CONFIGURED = "not configured"
NOT_FOUND = "not found"
EMPTY = "empty"
REFUSED_CREDENTIALS = "refused credentials"
TIMED_OUT = "timed out"
UNREACHABLE = "unreachable"
MISCONFIGURED = "misconfigured"
OTHER = "other"
FAILURE_KINDS = (NOT_CONFIGURED, NOT_FOUND, EMPTY, REFUSED_CREDENTIALS, TIMED_OUT,
                 UNREACHABLE, MISCONFIGURED, OTHER)

# Phrases drivers use, matched lower-case, checked in this order: a
# message that names both a timeout and a connection is a timeout.
_BY_MESSAGE = (
    (EMPTY, ("contains no tables",)),
    (REFUSED_CREDENTIALS, ("password authentication failed", "access denied",
                           "authentication failed", "permission denied", "login failed",
                           "invalid password", "not authorized")),
    (TIMED_OUT, ("timed out", "timeout", "interrupted")),
    (NOT_FOUND, ("does not exist", "no such table", "unknown database", "no database at",
                 "not found")),
    (UNREACHABLE, ("could not connect", "connection refused", "could not translate host",
                   "name or service not known", "unable to open database", "connection reset",
                   "network is unreachable", "no route to host", "server closed the connection")),
)


def _chain(exc: BaseException):
    """The exception and everything it was raised from, outermost first."""
    seen = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def failure_kind(exc: BaseException) -> str:
    """One of FAILURE_KINDS for this failure. The message is read to
    decide, never returned."""
    chain = list(_chain(exc))
    text = " ".join(str(each) for each in chain).lower()
    for kind, phrases in _BY_MESSAGE:
        if any(phrase in text for phrase in phrases):
            return kind
    for each in chain:
        if isinstance(each, FileNotFoundError):
            return NOT_FOUND
        if isinstance(each, PermissionError):
            return REFUSED_CREDENTIALS
        if isinstance(each, TimeoutError):
            return TIMED_OUT
        if isinstance(each, (ConnectionError, OSError)):
            return UNREACHABLE
        if isinstance(each, (ValueError, KeyError, TypeError, ImportError)):
            return MISCONFIGURED
    return OTHER


def source_failures(silo_names: Iterable[str], adapters: Mapping,
                    details: "dict[str, str] | None" = None) -> dict[str, str]:
    """{silo: failure kind} for each source that does not answer. A
    healthy source is absent, so an empty dict means every source
    answered. `details`, when given, is filled with each failure's class
    and message -- for the operator's log, never a response."""
    failures: dict[str, str] = {}
    for name in sorted(silo_names):
        adapter = adapters.get(name)
        if adapter is None:
            failures[name] = NOT_CONFIGURED
            continue
        try:
            adapter.health_check()
        except Exception as exc:  # any failure is a finding, never a crash
            failures[name] = failure_kind(exc)
            if details is not None:
                details[name] = f"{type(exc).__name__}: {exc}"
    return failures
