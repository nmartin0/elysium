"""A reporting copy that is always slightly behind.

A reporting tool is usually pointed at one of these rather than at the
system of record, so "the number was right five minutes ago" is a real
support call -- and it was the last common deployment shape this
simulator could not produce.
"""

import textwrap

import pytest
from simulator import runner
from simulator.relational import fetch_all
from simulator.spec import load_spec
from simulator.spec.values import PackError
from worlds import write_pack

LAGGING = textwrap.dedent("""
    pack: lagging
    silos:
      live:      {kind: postgresql, database: live}
      reporting: {kind: postgresql, database: reporting,
                  replicates: live, refresh: 6h}
    schemas:
      live:
        tables:
          orders:
            columns:
              order_id: {type: text, length: 64, primary_key: true, nullable: false}
              total:    {type: decimal, precision: 19, scale: 4, nullable: false}
    seed:
      - table: live.orders
        count: 5
        columns:
          order_id: {generator: id, prefix: o}
          total:    {generator: constant, value: "10.0000"}
    events:
      ordered:
        every: 1h
        emits:
          - table: live.orders
            columns:
              order_id: {generator: id, prefix: o}
              total:    {generator: constant, value: "10.0000"}
    """)


def counts(world):
    return (fetch_all(world.silo("live"), "live",
                      "SELECT count(*) FROM orders")[0][0],
            fetch_all(world.silo("reporting"), "reporting",
                      "SELECT count(*) FROM orders")[0][0])


@pytest.mark.postgres
def test_a_replica_falls_behind_and_catches_up(tmp_path, postgres_binaries):
    # The sawtooth a refreshed copy really has: it drifts further
    # behind every tick, then comes level when the interval comes
    # round. Between refreshes it is behind by up to that interval,
    # and that IS the lag -- a materialised copy is exactly as stale as
    # the time since it was last rebuilt.
    world = runner.build(write_pack(tmp_path, LAGGING, "lagging"),
                         tmp_path / "var", seed=1)
    try:
        runner.seed(world)
        gaps = []
        for _ in range(15):
            runner.run(world, total_seconds=3600, tick_seconds=3600)
            live, replica = counts(world)
            gaps.append(live - replica)

        assert max(gaps) > 0, "the replica never fell behind"
        assert gaps.count(0) >= 2, "it never caught up"
        assert all(gap >= 0 for gap in gaps), "the copy was ahead of its source"
    finally:
        runner.stop(world)


@pytest.mark.postgres
def test_a_replica_is_a_real_database_a_consumer_can_read(tmp_path,
                                                          postgres_binaries):
    # It gets its own database, its own tables and its own grants --
    # it is not a view or a trick, which is what makes a consumer
    # pointed at it behave exactly as one pointed at a real replica.
    world = runner.build(write_pack(tmp_path, LAGGING, "lagging"),
                         tmp_path / "var", seed=1)
    try:
        runner.seed(world)
        runner.run(world, total_seconds=7 * 3600, tick_seconds=3600)

        details = world.connections()["reporting"].details
        assert details["database"] == "reporting"

        import psycopg

        with psycopg.connect(host=details["host"], port=details["port"],
                             dbname=details["database"], user=details["user"],
                             password=details["password"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM orders")
                assert cursor.fetchone()[0] > 0
    finally:
        runner.stop(world)


@pytest.mark.postgres
def test_a_replica_reflects_changes_and_not_just_additions(tmp_path,
                                                           postgres_binaries):
    # A FULL REBUILD, which is what a materialised copy is. One that
    # copied only recent rows would diverge permanently on anything
    # that changed, and never say so.
    world = runner.build(write_pack(tmp_path, LAGGING, "lagging"),
                         tmp_path / "var", seed=1)
    try:
        runner.seed(world)
        runner.run(world, total_seconds=7 * 3600, tick_seconds=3600)

        with world.silo("live").connect("live", autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE orders SET total = 99 WHERE order_id = 'o_000001'")

        runner.run(world, total_seconds=7 * 3600, tick_seconds=3600)
        copied = fetch_all(world.silo("reporting"), "reporting",
                           "SELECT total FROM orders WHERE order_id = 'o_000001'")[0][0]
        assert int(copied) == 99, "the copy kept a value its source had changed"
    finally:
        runner.stop(world)


# -- what a pack may not say -------------------------------------------

def test_a_replica_needs_a_refresh_interval():
    # Without one the copy would be rebuilt every tick, which is a
    # replica with no lag -- an expensive way of having a second copy
    # of the same answers.
    with pytest.raises(PackError, match="needs a `refresh` interval"):
        load_spec({
            "pack": "x",
            "silos": {"live": {"kind": "postgresql", "database": "live"},
                      "reporting": {"kind": "postgresql", "database": "reporting",
                                    "replicates": "live"}},
            "schemas": {"live": {"tables": {"orders": {"columns": {
                "order_id": {"type": "text", "length": 64, "primary_key": True,
                             "nullable": False}}}}}},
        })


def test_a_refresh_without_a_replica_means_nothing():
    with pytest.raises(PackError, match="only means something with"):
        load_spec({
            "pack": "x",
            "silos": {"live": {"kind": "postgresql", "database": "live",
                               "refresh": "6h"}},
            "schemas": {"live": {"tables": {"orders": {"columns": {
                "order_id": {"type": "text", "length": 64, "primary_key": True,
                             "nullable": False}}}}}},
        })


def test_a_replica_declares_no_schema_of_its_own():
    # Its shape is whatever it copies. Letting a pack declare one too
    # would be letting it declare a copy that differs from its source,
    # which is not a replica but a second database with a confusing
    # name.
    with pytest.raises(PackError, match="remove its schema"):
        load_spec({
            "pack": "x",
            "silos": {"live": {"kind": "postgresql", "database": "live"},
                      "reporting": {"kind": "postgresql", "database": "reporting",
                                    "replicates": "live", "refresh": "6h"}},
            "schemas": {
                "live": {"tables": {"orders": {"columns": {
                    "order_id": {"type": "text", "length": 64, "primary_key": True,
                                 "nullable": False}}}}},
                "reporting": {"tables": {"orders": {"columns": {
                    "order_id": {"type": "text", "length": 64, "primary_key": True,
                                 "nullable": False}}}}},
            },
        })


def test_a_replica_names_a_silo_that_exists():
    with pytest.raises(PackError, match="does not declare"):
        load_spec({
            "pack": "x",
            "silos": {"reporting": {"kind": "postgresql", "database": "reporting",
                                    "replicates": "nowhere", "refresh": "6h"}},
            "schemas": {},
        })


def test_a_replica_of_a_replica_is_refused():
    # A chain's lag is the sum of its links, and nothing here tracks
    # that.
    with pytest.raises(PackError, match="itself a replica"):
        load_spec({
            "pack": "x",
            "silos": {
                "live": {"kind": "postgresql", "database": "live"},
                "first": {"kind": "postgresql", "database": "first",
                          "replicates": "live", "refresh": "6h"},
                "second": {"kind": "postgresql", "database": "second",
                           "replicates": "first", "refresh": "6h"},
            },
            "schemas": {"live": {"tables": {"orders": {"columns": {
                "order_id": {"type": "text", "length": 64, "primary_key": True,
                             "nullable": False}}}}}},
        })


def test_a_silo_cannot_replicate_itself():
    with pytest.raises(PackError, match="replica of itself"):
        load_spec({
            "pack": "x",
            "silos": {"live": {"kind": "postgresql", "database": "live",
                               "replicates": "live", "refresh": "6h"}},
            "schemas": {"live": {"tables": {"orders": {"columns": {
                "order_id": {"type": "text", "length": 64, "primary_key": True,
                             "nullable": False}}}}}},
        })


@pytest.mark.postgres
def test_two_worlds_do_not_share_a_refresh_clock(tmp_path, postgres_binaries):
    # A LATENT BUG, found by audit rather than by failure. The last
    # refresh was kept in a module-level dict keyed by id(world), and
    # CPython reuses an id the moment an object is collected --
    # measured, 1,998 reuses in 2,000 short-lived objects.
    #
    # A second world inheriting the first's refresh times would find
    # its replica already "refreshed" at a moment in its own future,
    # and skip refreshing until its clock caught up. The copy would sit
    # empty and nothing would say why.
    first = runner.build(write_pack(tmp_path, LAGGING, "lagging"),
                         tmp_path / "one", seed=1)
    try:
        runner.seed(first)
        runner.run(first, total_seconds=30 * 3600, tick_seconds=3600)
        assert counts(first)[1] > 0
    finally:
        runner.stop(first)

    second = runner.build(write_pack(tmp_path, LAGGING, "lagging"),
                          tmp_path / "two", seed=1)
    try:
        runner.seed(second)
        runner.run(second, total_seconds=3600, tick_seconds=3600)
        live, copied = counts(second)
        assert copied > 0, (
            "the second world's replica never refreshed, which is what "
            "sharing a refresh clock does")
        assert second.replica_refreshed, "nothing recorded the refresh"
    finally:
        runner.stop(second)


@pytest.mark.postgres
def test_a_world_with_a_replica_resumes_after_a_live_change(tmp_path, postgres_binaries):
    # Two faults, found in review on 20 October. A fresh world left its
    # replicas out of its record of schemas while a resumed one read them
    # in, so the shape saved at the first stop never matched and every
    # resume of a world with a replica was refused. And a change to the
    # source reached the replica's database but not that record.
    from simulator.control import apply_drift
    from simulator.resume import resume, save

    pack = write_pack(tmp_path, LAGGING, "lagging")
    directory = tmp_path / "var"
    world = runner.build(pack, directory, seed=1)
    try:
        runner.seed(world)
        runner.run(world, total_seconds=2 * 3600, tick_seconds=3600)
        apply_drift(world, "rename_column",
                    {"table": "live.orders", "column": "total", "to": "amount"})
        save(world, directory)
    finally:
        runner.stop(world)

    world = runner.attach(pack, directory, seed=1)
    try:
        resume(world, directory)
        runner.run(world, total_seconds=7 * 3600, tick_seconds=3600)
        copied = fetch_all(world.silo("reporting"), "reporting",
                           "SELECT count(amount) FROM orders")[0][0]
    finally:
        runner.stop(world)

    assert copied > 0


@pytest.mark.postgres
def test_a_world_with_a_replica_resumes(tmp_path, postgres_binaries):
    # The first of the two faults above on its own: nothing drifted, and
    # the resume was still refused, because the shape saved by a freshly
    # built world left its replica out.
    from simulator.resume import resume, save

    pack = write_pack(tmp_path, LAGGING, "lagging")
    directory = tmp_path / "var"
    world = runner.build(pack, directory, seed=1)
    try:
        runner.seed(world)
        save(world, directory)
    finally:
        runner.stop(world)

    world = runner.attach(pack, directory, seed=1)
    try:
        resume(world, directory)
    finally:
        runner.stop(world)


def test_a_replica_runs_its_sources_engine():
    # Found in review: a MariaDB source's zero dates, copied into a
    # PostgreSQL "replica", would fail every refresh. No real replica
    # crosses engines.
    with pytest.raises(PackError, match="runs its source's engine"):
        load_spec({
            "pack": "x",
            "silos": {"shop": {"kind": "mariadb", "database": "shop"},
                      "copy": {"kind": "postgresql", "database": "copy",
                               "replicates": "shop", "refresh": "6h"}},
            "schemas": {"shop": {"tables": {"t": {"columns": {
                "id": {"type": "text", "length": 8, "primary_key": True,
                       "nullable": False}}}}}},
        })


@pytest.mark.postgres
def test_a_replica_withholds_what_its_source_withholds(tmp_path, postgres_binaries):
    # Found 20 October by the first run of Elysium over field_service:
    # pay_lines, withheld on dispatch, were readable in full through the
    # `office` replica. A streamed replica copies the catalog, grants and
    # all, so the reader is refused there too.
    import psycopg

    withheld = LAGGING.replace("live:      {kind: postgresql, database: live}",
                               "live:      {kind: postgresql, database: live, "
                               "withheld: [orders]}")
    assert withheld != LAGGING
    world = runner.build(write_pack(tmp_path, withheld, "lagging"), tmp_path / "var", seed=1)
    try:
        runner.seed(world)
        runner.run(world, total_seconds=7 * 3600, tick_seconds=3600)
        details = world.connections()["reporting"].details
        with psycopg.connect(host=details["host"], port=details["port"],
                             dbname=details["database"], user=details["user"],
                             password=details["password"]) as connection, \
                pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT count(*) FROM orders")
        assert counts(world)[1] > 0, "the copy is still made; only the reader is refused"
    finally:
        runner.stop(world)


# ---- a streaming standby (21 October) ---------------------------------------

STREAMING = textwrap.dedent("""
    pack: streaming
    silos:
      live:      {kind: postgresql, database: live, withheld: [secrets]}
      reporting: {kind: postgresql, database: live, replicates: live,
                  replication: streaming}
    schemas:
      live:
        tables:
          orders:
            columns:
              order_id: {type: text, length: 64, primary_key: true, nullable: false}
              total:    {type: decimal, precision: 19, scale: 4, nullable: false}
          secrets:
            columns:
              secret_id: {type: text, length: 64, primary_key: true, nullable: false}
    seed:
      - table: live.orders
        count: 5
        columns:
          order_id: {generator: id, prefix: o}
          total:    {generator: constant, value: "10.0000"}
    events:
      ordered:
        every: 1h
        emits:
          - table: live.orders
            columns:
              order_id: {generator: id, prefix: o}
              total:    {generator: constant, value: "10.0000"}
    """)


def _standby_count(world, timeout=10.0):
    """The standby's count once replay has had a moment: streaming is
    asynchronous, so a read straight after a commit may be just behind."""
    import time

    deadline = time.monotonic() + timeout
    while True:
        live = fetch_all(world.silo("live"), "live", "SELECT count(*) FROM orders")[0][0]
        standby = fetch_all(world.silo("reporting"), "live", "SELECT count(*) FROM orders")[0][0]
        if standby == live or time.monotonic() > deadline:
            return live, standby
        time.sleep(0.1)


@pytest.mark.postgres
def test_a_streaming_replica_is_a_standby_fed_by_the_wal(tmp_path, postgres_binaries):
    world = runner.build(write_pack(tmp_path, STREAMING, "streaming"), tmp_path / "var", seed=1)
    try:
        runner.seed(world)
        runner.run(world, total_seconds=3 * 3600, tick_seconds=3600)

        live, standby = _standby_count(world)
        assert live == standby == 8
        in_recovery = fetch_all(world.silo("reporting"), "live", "SELECT pg_is_in_recovery()")
        assert in_recovery[0][0] is True
    finally:
        runner.stop(world)


@pytest.mark.postgres
def test_paused_replay_is_lag_and_resumed_replay_catches_up(tmp_path, postgres_binaries):
    world = runner.build(write_pack(tmp_path, STREAMING, "streaming"), tmp_path / "var", seed=1)
    try:
        runner.seed(world)
        _standby_count(world)
        world.silo("reporting").pause_replay(True)
        runner.run(world, total_seconds=3 * 3600, tick_seconds=3600)

        live, standby = _standby_count(world, timeout=1.0)
        assert (live, standby) == (8, 5), "paused, the standby stays where it was"

        world.silo("reporting").pause_replay(False)
        assert _standby_count(world) == (8, 8)
    finally:
        runner.stop(world)


@pytest.mark.postgres
def test_a_standby_carries_the_sources_grants_and_drift(tmp_path, postgres_binaries):
    import psycopg

    world = runner.build(write_pack(tmp_path, STREAMING, "streaming"), tmp_path / "var", seed=1)
    try:
        runner.seed(world)
        world.apply_change("live", load_spec_change(world, "add_column", {
            "table": "live.orders", "column": "note", "type": "text", "length": 20}))
        _standby_count(world)
        details = world.connections()["reporting"].details
        with psycopg.connect(host=details["host"], port=details["port"],
                             dbname=details["database"], user=details["user"],
                             password=details["password"]) as connection:
            columns = {row[0] for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'orders'").fetchall()}
            assert "note" in columns, "the source's DDL reaches the standby"
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT count(*) FROM secrets")
    finally:
        runner.stop(world)


def load_spec_change(world, operation, fields):
    from simulator.spec.migrations import build_change

    return build_change(operation, fields, world.schema("live"))


@pytest.mark.parametrize(("change", "says"), [
    ("replication: streaming}", "only means something with `replicates`"),
    ("replicates: live, replication: streaming, refresh: 6h}", "no refresh"),
    ("replicates: live, replication: carrier-pigeon}", "copy or streaming"),
], ids=["no_source", "refresh", "unknown"])
def test_what_a_streaming_replica_may_say(tmp_path, change, says):
    import yaml

    raw = yaml.safe_load(STREAMING)
    line = "reporting: {kind: postgresql, database: live, " + change
    raw["silos"]["reporting"] = yaml.safe_load("{" + line.split("{", 1)[1])
    with pytest.raises(PackError, match=says):
        load_spec(raw)


def test_a_standby_holds_its_sources_databases_by_name():
    import yaml

    raw = yaml.safe_load(STREAMING)
    raw["silos"]["reporting"]["database"] = "reporting"
    with pytest.raises(PackError, match="set `database: live`"):
        load_spec(raw)


@pytest.mark.postgres
def test_a_standby_is_left_alone_by_outages_and_drift(tmp_path, postgres_binaries):
    """Found in review, 21 October: restoring leftover outages wrote to the
    standby, crashing the resume of any world with one; an outage on it was
    marked out though nothing happened; a drift on it failed inside
    PostgreSQL rather than being refused."""
    from simulator import outages
    from simulator.control import ControlError, Controller, apply_drift

    world = runner.build(write_pack(tmp_path, STREAMING, "streaming"), tmp_path / "var", seed=1)
    try:
        done = outages.restore_leftovers(world)
        assert "standby" in done["reporting"], "a resumed world's restore passes it by"

        controller = Controller(world)
        with pytest.raises(ControlError, match="standby"):
            controller._cmd_outage({"silo": "reporting"})
        assert "reporting" not in controller.out
        with pytest.raises(ControlError, match="drift its source"):
            apply_drift(world, "add_column", {"table": "reporting.orders", "column": "x",
                                              "type": "text", "length": 5})
    finally:
        runner.stop(world)


@pytest.mark.parametrize("extra", [{"withheld": ["orders"]},
                                   {"options": {"row_security": ["orders"]}}],
                         ids=["withheld", "row_security"])
def test_a_standbys_grants_are_its_sources(extra):
    import yaml

    raw = yaml.safe_load(STREAMING)
    raw["silos"]["reporting"].update(extra)
    with pytest.raises(PackError, match="grants are its source's"):
        load_spec(raw)
