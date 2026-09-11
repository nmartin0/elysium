"""
Reloading configuration without a restart -- step 3 of
HOT_RELOAD_PLAN.md.

Until now the only way to load edited configuration was to restart,
which drops every session, every in-flight query and every pending
write. And a restart with a BROKEN file does not come back.

THE THREE PROPERTIES, in order of how much damage their absence does:

  - a failed reload changes nothing
  - a successful reload swaps atomically, so no request sees a
    half-built configuration
  - two reloads cannot interleave
"""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from api.reload import ReloadInProgress, reload_generation
from core.deployment_loader import build_generation

DEPLOYMENT = Path(__file__).resolve().parent.parent.parent / "deployment" / "etc"


@pytest.fixture(autouse=True)
def _restore_sighup():
    """signal.signal is PROCESS-GLOBAL.

    A handler installed by one test stays live for every test after it,
    pointing at that test's app. A later test raising SIGHUP then
    reloads somebody else's deployment -- which is how one of these
    tests failed under full-suite load while passing alone.
    """
    import signal

    previous = signal.getsignal(signal.SIGHUP)
    yield
    signal.signal(signal.SIGHUP, previous)


def _app(tmp_path):
    generation = build_generation(DEPLOYMENT, data_dir=tmp_path, log_dir=tmp_path / "log")
    return SimpleNamespace(state=SimpleNamespace(
        generation=generation,
        runtime_paths=SimpleNamespace(
            config_dir=DEPLOYMENT, data_dir=tmp_path, log_dir=tmp_path / "log",
        ),
    ))


def test_a_reload_replaces_the_generation(tmp_path):
    app = _app(tmp_path)
    before = app.state.generation

    after = reload_generation(app, requested_by="alice")

    assert after is not before
    assert after.generation > before.generation
    assert app.state.generation is after


def test_reloading_unchanged_files_keeps_the_same_digest(tmp_path):
    # A new GENERATION of the same CONFIGURATION. The digest says what
    # was read; the generation says which read it was. Conflating them
    # would make "did anything change?" unanswerable.
    app = _app(tmp_path)
    before = app.state.generation

    after = reload_generation(app)

    assert after.source_digest == before.source_digest
    assert after.generation != before.generation


def test_a_failed_reload_changes_nothing(tmp_path):
    # THE PROPERTY THAT MATTERS MOST. Today a broken edit plus a
    # restart is an outage that does not come back; here it is a no-op
    # with an error.
    app = _app(tmp_path)
    before = app.state.generation
    # yaml.YAMLError is in the expected set because load_deployment()
    # lets a parse error through unwrapped -- worth knowing rather than
    # catching blind Exception, which hides exactly this kind of
    # detail.
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "config.yaml").write_text(": : not valid yaml\n")
    app.state.runtime_paths.config_dir = broken

    with pytest.raises((ValueError, KeyError, yaml.YAMLError)):
        reload_generation(app)

    assert app.state.generation is before, "the running generation was replaced by a failure"


def test_a_second_reload_is_rejected_rather_than_queued(tmp_path):
    # Rejected, because queueing lets a burst of signals stack up
    # rebuilds nobody asked for, and the caller learns nothing from
    # waiting behind one.
    app = _app(tmp_path)
    started = threading.Event()
    release = threading.Event()
    rejected = []

    def slow_build(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        return app.state.generation

    import api.reload as reload_module
    original = reload_module.build_generation
    reload_module.build_generation = slow_build
    try:
        first = threading.Thread(target=lambda: reload_generation(app))
        first.start()
        started.wait(timeout=5)
        try:
            reload_generation(app)
        except ReloadInProgress:
            rejected.append(True)
        release.set()
        first.join(timeout=5)
    finally:
        reload_module.build_generation = original

    assert rejected == [True], "a concurrent reload was not rejected"


def test_the_lock_is_released_after_a_failure(tmp_path):
    # A failed reload must not wedge the lock, or one bad edit makes
    # every later reload impossible until a restart -- which is the
    # thing this feature exists to avoid.
    app = _app(tmp_path)
    broken = tmp_path / "broken2"
    broken.mkdir()
    (broken / "config.yaml").write_text(": : bad\n")
    good = app.state.runtime_paths.config_dir
    app.state.runtime_paths.config_dir = broken

    with pytest.raises((ValueError, KeyError, yaml.YAMLError)):
        reload_generation(app)

    app.state.runtime_paths.config_dir = good
    assert reload_generation(app) is app.state.generation


def test_a_reload_is_audited_whether_it_succeeds_or_fails(tmp_path):
    # A configuration change is security-relevant and was previously
    # unrecordable, because configuration could only change by
    # restarting. A rejected reload is as interesting as an accepted
    # one, and more so if someone is probing.
    import json

    app = _app(tmp_path)
    reload_generation(app, requested_by="alice")
    broken = tmp_path / "broken3"
    broken.mkdir()
    (broken / "config.yaml").write_text(": : bad\n")
    app.state.runtime_paths.config_dir = broken
    with pytest.raises((ValueError, KeyError, yaml.YAMLError)):
        reload_generation(app, requested_by="mallory")

    entries = [json.loads(line) for line in
               (tmp_path / "log" / "audit.log").read_text().splitlines()]
    reloads = [e for e in entries if e.get("stage") == "config_reload"]

    assert [e["outcome"] for e in reloads] == ["applied", "rejected"]
    assert reloads[0]["user_id"] == "alice"
    assert reloads[1]["user_id"] == "mallory"
    assert reloads[1]["to_generation"] is None, "a failure has no new generation to name"


def test_runtime_state_is_not_touched_by_a_reload(tmp_path):
    # Sessions, credentials, lockout counters and pending writes must
    # SURVIVE. Rebuilding them would log out every user and reset every
    # lockout counter -- letting an attacker clear their own rate limit
    # by triggering a reload.
    app = _app(tmp_path)
    app.state.session_store = sentinel = object()
    app.state.pending_writes = pending = object()

    reload_generation(app)

    assert app.state.session_store is sentinel
    assert app.state.pending_writes is pending


# --- runtime state that carries a slice of configuration ---

def test_a_role_added_by_a_reload_is_usable_without_a_restart(tmp_path):
    # THE BUG THIS CLOSES, found by a test while building the reload
    # endpoint: after a reload added a role, creating a user with it
    # failed "Unknown role" until the process restarted.
    #
    # UserDirectory is RUNTIME state -- it owns credentials.db and must
    # survive a reload -- but it carries a slice of CONFIGURATION. A
    # surviving object holding a snapshot of replaced config is stale
    # by construction. It now reads through a callable.
    import dataclasses

    from core.immutable import deep_freeze
    from core.user_directory import UserDirectory

    app = _app(tmp_path)
    directory = UserDirectory(tmp_path / "credentials.db",
                              lambda: app.state.generation.config.roles)

    with pytest.raises(ValueError, match="Unknown role"):
        directory.create_user("someone", "pw", None, "auditor")

    # The reload: a new generation whose config declares the role.
    config = app.state.generation.config
    app.state.generation = dataclasses.replace(
        app.state.generation,
        config=dataclasses.replace(
            config,
            roles=deep_freeze({**config.roles, "auditor": {"allowed_actions": frozenset()}}),
        ),
    )

    directory.create_user("someone", "pw", None, "auditor")


def test_the_mapping_form_still_works_for_scripts(tmp_path):
    # scripts/bootstrap_root.py and friends pass a plain dict. A
    # one-shot script has no reload to be stale across, and requiring
    # it to wrap a dict in a lambda would be ceremony without a reason.
    from core.user_directory import UserDirectory

    directory = UserDirectory(tmp_path / "c.db", {"admin": {"allowed_actions": frozenset()}})

    assert "admin" in directory.roles


def test_pending_writes_audit_against_the_current_generation(tmp_path):
    # PendingWriteStore SURVIVES a reload; each generation builds its
    # own AuditLog, stamped with its own generation number. Holding an
    # instance would record a write expiring after a reload against the
    # STARTUP log -- naming the wrong generation, which is a
    # wrong-but-plausible value in an audit trail and worse than an
    # obviously missing one.
    from core.pending_write_store import PendingWriteStore

    app = _app(tmp_path)
    store = PendingWriteStore(audit_log=lambda: app.state.generation.mediator.audit_log)
    before = store.audit_log

    reload_generation(app)

    assert store.audit_log is not before
    assert store.audit_log is app.state.generation.mediator.audit_log


def test_the_instance_form_still_works(tmp_path):
    # Tests and scripts construct a store with a plain AuditLog, and a
    # one-shot caller has no reload to be stale across.
    from core.intermediate_layer.audit import AuditLog
    from core.pending_write_store import PendingWriteStore

    log = AuditLog(tmp_path / "audit.log")

    assert PendingWriteStore(audit_log=log).audit_log is log


# --- SIGHUP ---

def test_sighup_returns_immediately_rather_than_reloading_inline(tmp_path):
    # THE POINT of running the work on a thread, and this asserts the
    # timing rather than the outcome. A signal handler runs on the MAIN
    # thread, interrupting the event loop; building a generation opens
    # databases and parses four files. Inline, that stalls every
    # request in flight for the duration.
    #
    # An earlier version of this test only checked that the generation
    # advanced, which passes whether or not a thread is used -- a
    # control doing the work inline did not fail it.
    import signal
    import time

    import api.reload as reload_module
    from api.reload import install_sighup_handler

    app = _app(tmp_path)
    building = threading.Event()
    release = threading.Event()
    original = reload_module.build_generation

    def slow_build(*args, **kwargs):
        building.set()
        release.wait(timeout=5)
        return original(*args, **kwargs)

    reload_module.build_generation = slow_build
    try:
        install_sighup_handler(app)
        started = time.monotonic()
        signal.raise_signal(signal.SIGHUP)
        handler_returned = time.monotonic() - started

        assert building.wait(timeout=5), "the reload never started"
        assert handler_returned < 1.0, (
            f"the signal handler blocked for {handler_returned:.2f}s -- it is doing "
            f"the reload inline rather than handing it to a thread"
        )
        release.set()
    finally:
        reload_module.build_generation = original


def test_sighup_actually_reloads(tmp_path):
    # The outcome, separately from the timing above.
    import signal
    import time

    from api.reload import install_sighup_handler

    app = _app(tmp_path)
    before = app.state.generation.generation
    install_sighup_handler(app)

    signal.raise_signal(signal.SIGHUP)

    deadline = time.time() + 5
    while app.state.generation.generation == before and time.time() < deadline:
        time.sleep(0.02)

    assert app.state.generation.generation > before


def test_a_failing_sighup_reload_raises_nothing_out_of_its_thread(tmp_path):
    # There is no caller to return an error to, so the thread must
    # catch everything. A signal that cannot be answered must not take
    # the service down -- especially when the likely cause is a
    # half-saved YAML file.
    #
    # Asserted via threading.excepthook, because an exception escaping
    # a daemon thread does NOT fail a test on its own: an earlier
    # version of this test passed with the catch removed.
    import signal
    import time

    from api.reload import install_sighup_handler

    app = _app(tmp_path)
    before = app.state.generation
    broken = tmp_path / "sighup_broken"
    broken.mkdir()
    (broken / "config.yaml").write_text(": : bad\n")
    app.state.runtime_paths.config_dir = broken

    escaped = []
    original_hook = threading.excepthook
    threading.excepthook = lambda args: escaped.append(args.exc_type)
    try:
        install_sighup_handler(app)
        signal.raise_signal(signal.SIGHUP)
        time.sleep(0.5)
    finally:
        threading.excepthook = original_hook

    assert escaped == [], f"an exception escaped the SIGHUP thread: {escaped}"
    assert app.state.generation is before, "a failed SIGHUP reload replaced the generation"


# --- steps 4b and 4c: an in-flight query and a reload ---

def test_a_running_loop_keeps_its_own_generations_mediator(tmp_path):
    # STEP 4c, ANSWERED BY CONSTRUCTION rather than by new code. The
    # route takes its loop from the PINNED generation, and the loop
    # holds that generation's mediator. A reload builds a whole new
    # generation with its own loop; the running one is untouched.
    #
    # That is the "finish under the pinned generation" option the plan
    # listed -- consistent, possibly stale -- and step 2 already made
    # it the only reachable behaviour.
    app = _app(tmp_path)
    running_loop = app.state.generation.loop
    pinned_mediator = running_loop.mediator

    reload_generation(app)

    assert running_loop.mediator is pinned_mediator
    assert app.state.generation.loop is not running_loop
    assert app.state.generation.mediator is not pinned_mediator


def test_visible_schema_cannot_change_under_a_running_loop(tmp_path):
    # STEP 4b, and the reason it needs no code. visible_schema has
    # exactly two inputs: the mediator's schema and roles -- both from
    # the pinned, deep-frozen generation -- and the acting UserRecord,
    # which step 4a already stops the loop on if it changes.
    #
    # So there is no path by which it can differ mid-query, and
    # "recompute when the generation moves" would recompute the same
    # answer.
    from core.intermediate_layer.auth import resolve_user_record

    app = _app(tmp_path)
    running_loop = app.state.generation.loop
    record = resolve_user_record(
        app.state.generation.config.users, "user_alice",
        app.state.generation.config.security_attribute,
    )
    before = running_loop.mediator.visible_schema(record)

    reload_generation(app)

    assert running_loop.mediator.visible_schema(record) == before
