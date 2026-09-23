"""
The sync must read the SOURCE, never the mirror it is filling.

FOUND ON A REAL DEPLOYMENT within an hour of read_from_mirror becoming
the default. Dropping silver and re-syncing reported:

    source column 'transaction_id' backing no declared field is gone

The column had not gone anywhere. run_sync took its adapters from the
mediator, and with mirror reads on those are MirrorReadAdapters -- so
the sync was reading the empty silver table it was trying to rebuild.

NOT A SUBTLE FAILURE, and not one any test caught: every test either
ran with mirror reads off, or exercised the sync with adapters passed
in directly.
"""

import pathlib

from core.deployment_loader import (
    build_live_read_adapters,
    load_deployment_bundle,
)


def test_the_sync_and_the_mediator_read_different_things(private_deployment):
    """THE WHOLE POINT, stated as one assertion.

    The mediator serves reads and obeys the deployment's choice. The
    sync FILLS what those reads come from and has no choice to obey.
    """
    paths = private_deployment  # E-08: never the developer's deployment
    _, mediator, _ = load_deployment_bundle(
        paths.config_dir, paths.data_dir, paths.log_dir,
    )

    serving = {type(a).__name__ for a in mediator.adapters.values()}
    filling = {type(a).__name__ for a in build_live_read_adapters(paths).values()}

    # SINCE GOLD-8 the serving mediator holds ONE reader, the gold
    # connector: reads come from published gold and from nothing else,
    # so there is no source adapter in there to read by accident. The
    # property this file exists for is unchanged and stronger -- what
    # the SYNC holds must not be what SERVING holds.
    assert serving == {"GoldConnector"}
    assert filling == {"SQLiteReadAdapter"}


def test_live_adapters_never_include_a_mirror_adapter(private_deployment):
    # The property that matters, independent of which adapter a
    # deployment happens to configure.
    for adapter in build_live_read_adapters(private_deployment).values():
        assert "Mirror" not in type(adapter).__name__


def test_a_relative_silo_path_is_resolved_against_the_data_directory(private_deployment):
    """build_generation() does this inline rather than in a function,
    so the live builder has to repeat it. An adapter built without the
    resolution opens a file that is not there -- which reads as an
    empty silo rather than as a missing one.
    """
    # THE CALLER'S data directory -- the question build_live_read_adapters()
    # used to get wrong, given anything but the default (E-08).
    paths = private_deployment

    for adapter in build_live_read_adapters(paths).values():
        db_path = getattr(adapter, "db_path", None)
        if db_path is None:
            continue
        # UNDER THE DATA DIRECTORY, not absolute. A first version of
        # this test asserted the path started with "/" and failed --
        # because data_dir is itself relative in this deployment, so a
        # correctly resolved path is relative too. The property is the
        # JOIN, not the shape of the result.
        assert str(db_path).startswith(str(paths.data_dir)), (
            f"{db_path} is not under {paths.data_dir}"
        )


def test_run_sync_does_not_take_its_adapters_from_the_mediator():
    """A SOURCE-LEVEL TRIPWIRE, because the bug self-conceals.

    Restoring the broken wiring and running a real sync SUCCEEDS --
    2/2 tables -- because reading a populated mirror to rebuild that
    same mirror copies it onto itself. Every row is already there, so
    nothing appears wrong.

    It only surfaced because silver had been DROPPED, leaving nothing
    to read. A behavioural control therefore cannot catch this: the
    failure needs an empty layer to become visible, and by then the
    deployment is already serving the wrong thing.

    So the wiring is asserted directly.
    """
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "scripts" / "run_sync.py"
    ).read_text()

    # WITH run_sync's OWN PATHS: called bare, it read the default
    # deployment's silos while writing this one's mirror (E-08).
    assert "build_live_read_adapters(runtime_paths)" in source
    assert "mediator.adapters" not in source
