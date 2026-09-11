"""
reload.py  (replacing the running configuration without a restart)

Separate from api/app.py deliberately. app.py WIRES a process at
startup and sits above routes in api/'s layering, so a route cannot
import it. This takes the app as an argument instead of importing one,
which also makes it testable without standing a server up.
"""

import logging
import threading

from core.deployment_loader import DeploymentGeneration, build_generation

logger = logging.getLogger(__name__)


class ReloadInProgress(RuntimeError):
    """A reload was requested while another was still running."""


_reload_lock = threading.Lock()


def reload_generation(app, requested_by: str = "unknown") -> DeploymentGeneration:
    """Replaces the running configuration with a freshly loaded one.

    BUILD FULLY, VALIDATE FULLY, THEN SWAP. build_generation() either
    returns a whole generation or raises, so a broken YAML edit is a
    no-op with an error rather than an outage -- which is what it is
    today, since the only way to load new configuration is to restart.

    THE SWAP IS ONE ATOMIC ASSIGNMENT and takes no lock. Rebinding is
    atomic in CPython and so is reading, so a request can never observe
    a half-built generation. Requests already running keep the
    generation they pinned and finish on it; the next request gets the
    new one. That is bounded staleness with consistency inside each
    request, and it is only sound because the shared object cannot be
    mutated -- see core/immutable.py.

    SERIALISED, AND NON-BLOCKING. SIGHUP and an admin request can
    arrive together, and two builds racing to swap means the loser's
    work is either wasted or lands second and wins. A second reload is
    REJECTED rather than queued: queueing lets a burst of signals stack
    up rebuilds nobody asked for, and the caller learns nothing useful
    from waiting behind one.

    WHAT IT DELIBERATELY DOES NOT DO: resume_pending_writes(). That
    recovers writes interrupted by a crash and belongs to starting up.
    The writes it would recover are already recovered, and re-running
    it against in-flight state is a different operation with different
    risks.

    RUNTIME STATE IS UNTOUCHED -- sessions, credentials, lockout
    counters, rate limiters, pending writes, the artifact store, the
    thread pool. Rebuilding those would log out every user, discard
    every pending write, and reset every lockout counter, which would
    let an attacker clear their own rate limit by triggering a reload.
    """
    if not _reload_lock.acquire(blocking=False):
        raise ReloadInProgress("a configuration reload is already in progress")
    try:
        current = app.state.generation
        audit_log = current.mediator.audit_log
        try:
            new = build_generation(
                app.state.runtime_paths.config_dir,
                app.state.runtime_paths.data_dir,
                app.state.runtime_paths.log_dir,
            )
        except Exception as e:
            # The running generation is untouched. Recorded against the
            # OLD generation's log because that is what is in force --
            # there is no new one to attribute it to.
            audit_log.log_reload(requested_by, "rejected", current.generation,
                                 None, None, detail=str(e)[:500])
            raise
        app.state.generation = new
        audit_log.log_reload(requested_by, "applied", current.generation,
                             new.generation, new.source_digest)
        logger.info(
            f"configuration reloaded by {requested_by}: generation "
            f"{current.generation} -> {new.generation}, digest {new.source_digest[:12]}"
        )
        return new
    finally:
        _reload_lock.release()
