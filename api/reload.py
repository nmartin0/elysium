"""
reload.py  (replacing the running configuration without a restart)

Separate from api/app.py deliberately. app.py WIRES a process at
startup and sits above routes in api/'s layering, so a route cannot
import it. This takes the app as an argument instead of importing one,
which also makes it testable without standing a server up.
"""

import logging
import signal
import threading

from core.config_history import record_generation
from core.deployment_loader import (
    DeploymentGeneration,
    build_generation,
    repointed_silos,
)

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
        # REPOINTED SILOS ARE NAMED IN THE AUDIT, because "generation 7
        # became 8" does not distinguish a model-timeout tweak from the
        # customer's database being swapped underneath the ontology.
        # Recorded even though the reload succeeds: this is not an
        # error, it is the single change a reviewer most needs to see.
        repointed = repointed_silos(current.config, new.config)

        if repointed:
            # WARNED, NOT REFUSED, and the distinction is deliberate.
            # Requests already in flight keep the OLD adapters and go
            # on reading the OLD source -- correct, since an answer
            # assembled half from one database and half from another
            # was never true anywhere. But if the operator repointed
            # because the old path is going away, those reads are on
            # borrowed time, and only they know which it is.
            #
            # Refusing would be worse: a deployment that cannot be
            # repointed without a restart loses the thing this whole
            # migration is for.
            logger.warning(
                f"configuration reload repointed silo(s) {', '.join(repointed)}. "
                f"Requests already running keep reading the previous source; "
                f"if it is being decommissioned, let them drain first."
            )

        app.state.generation = new
        # Recorded BEFORE the audit entry, so a history row exists for
        # any generation the audit mentions. The reverse order would
        # leave an audit line pointing at a generation with no content
        # recorded, which is the exact gap this closes.
        record_generation(app.state.config_history, new)
        audit_log.log_reload(
            requested_by, "applied", current.generation, new.generation,
            new.source_digest,
            detail=f"repointed silos: {', '.join(repointed)}" if repointed else None,
        )
        logger.info(
            f"configuration reloaded by {requested_by}: generation "
            f"{current.generation} -> {new.generation}, digest {new.source_digest[:12]}"
        )
        return new
    finally:
        _reload_lock.release()


def install_sighup_handler(app, thread_factory=threading.Thread) -> None:
    """Makes SIGHUP reload configuration, the way daemons have forever.

    THE WORK RUNS ON A SHORT-LIVED THREAD, not in the handler. A signal
    handler runs on the MAIN thread, interrupting whatever it was
    doing -- which under uvicorn is the event loop. Building a
    generation opens databases and parses four files; doing that inline
    would stall every request in flight for the duration, turning a
    reload into an outage for as long as it takes.

    A thread per signal rather than a permanent worker, deliberately. A
    standing background thread is a concurrency surface that exists
    even when nothing is happening, for work that happens rarely and on
    demand -- the same argument that keeps a scheduler out of this
    process. These threads exist for the length of one reload.

    A BURST OF SIGNALS IS SAFE. reload_generation() takes its lock
    non-blocking, so the first wins and the rest are rejected
    immediately rather than queueing rebuilds nobody asked for.

    FAILURE NEVER REACHES THE PROCESS. There is no caller to return an
    error to, so the thread catches everything and logs it. A signal
    that cannot be answered must not be able to kill the service --
    especially when the likely cause is a half-saved YAML file.
    """

    # thread_factory is injected ONLY so a test can hold the thread and
    # join it. A test that polls for a side effect instead leaves the
    # thread running when it returns -- and that thread holds the
    # reload lock, so the NEXT test's signal is rejected as "already in
    # progress". That is not hypothetical: it happened, and the failure
    # depended on test ordering, which is the hardest kind to read.
    #
    # Injected rather than stored in module state, which would be
    # shared between tests and is the thing being fixed.

    def _handle(_signum, _frame):
        # Both arguments are required by signal.signal's contract and
        # neither is useful here: there is only one signal registered,
        # and the interrupted frame is not something a reload cares
        # about.
        thread_factory(target=_reload_from_signal, args=(app,), daemon=True).start()

    signal.signal(signal.SIGHUP, _handle)
    logger.info("SIGHUP will reload configuration")


def _reload_from_signal(app) -> None:
    try:
        reload_generation(app, requested_by="SIGHUP")
    except ReloadInProgress:
        logger.warning("SIGHUP ignored: a configuration reload is already in progress")
    except Exception as e:
        # Logged and swallowed. The audit entry recording the rejection
        # is written by reload_generation() before it raises, so the
        # failure is on the record either way.
        logger.error(f"SIGHUP reload failed, configuration unchanged: {e}")
