# elysium-sim

A simulator that operates **real PostgreSQL databases** for a simulated
organization, changing both their contents and their structure over
time.

It exists so that a system which reads databases can be tested against
data that actually moves: new rows arriving on a believable rhythm,
entities walking their lifecycles, and — the part no static fixture
reaches — columns being added, dropped, renamed, retyped and rescaled
underneath a running consumer.

## The one rule

**The databases are the only interface.** A consumer connects to a
PostgreSQL port and sees a business. There is no API into the
simulator, no shared file, no coordination channel. This repository
contains no consumer-specific code and must never acquire any.

That constraint is what makes the tool worth having. A fixture
generator shaped around one consumer structurally cannot simulate a
schema that consumer has not been told about — which is precisely the
case worth testing.

## Status

Early. The engine core is being built; see `AGENTS.md` for how work
lands here, and the design documents for where it is going.

## Shape

Four layers, and the boundary between the middle two is the point:

| Layer | What it is |
| --- | --- |
| **Pack files** | YAML. A whole organization: its databases, entities, rhythms, and how its schema evolves. |
| **Engine** | Python. Knows nothing about retail or aviation — only how to read a pack and run it. |
| **SQL layer** | Real PostgreSQL instances, one per silo, each on its own fixed localhost port. |
| **Consumer** | Not here. Connects over the socket like any other client. |

Adding a domain means writing a pack file. It never means writing a
subclass.

## Planned packs

Retail point-of-sale, field service, aviation, and local city
government. Four deliberately different shapes — the vocabulary has to
express all of them, or the engine is not really domain-agnostic.

The aviation pack is modelled on the example data Palantir uses in its
own Foundry tutorials, which traces back to the US Bureau of
Transportation Statistics On-Time Performance schema — including the
OOOI milestone model, where one flight row is updated four to six times
as it passes Gate Out, Wheels Off, Wheels On and Gate In.

## Requirements

- Python 3.12
- PostgreSQL 16 (`initdb` and `pg_ctl` on `PATH`; no system service and
  no root — the simulator starts its own instances)

```sh
pip install -r requirements-dev.lock
./lint.sh
python -m pytest tests/ -q
```

## Operating a running world

The consumer's rule above is unchanged: a consumer has only the
databases. The *operator* has more. A running world answers its own
control channel (`simulator/control.py`, loopback only, with a token in
an owner-only `control.json`), and the command line sends to it:

```sh
python -m simulator run packs/probe.yaml --dir var --follow --compression 3600
python -m simulator status --dir var
python -m simulator speed 7200 --dir var      # while following
python -m simulator outage ops --dir var      # and `restore ops`
python -m simulator stop --dir var            # tidily, as Ctrl-C would
```

A run tidies up -- outages restored, the clock saved for `--resume`,
every database server stopped -- on Ctrl-C, on `stop`, and on SIGTERM,
which is how systemd and Elysium stop a process. It holds `run.lock` in
its directory for its whole life, so another run cannot start there
while it is building or tidying up.

### The control panel

`panel/` is the same, as a page: a module for Elysium's shell, offered
to holders of `module:simulator:operate`, its server (`panel/server.py`)
started by Elysium. List `sim/panel` in Elysium's `modules.yaml`, and
say where the world lives in its `addons.yaml`:

```yaml
simulator:
  options:
    directory: /srv/sim/world
```

The world the panel starts **runs on its own**: Elysium stopping, or
crashing, leaves it running and changing, as a customer's database would
-- which is the point, since "what does Elysium do after an hour
offline?" is one of the questions the simulator exists to ask. The panel
finds the world again when Elysium is back.

The panel's page is built by Elysium's UI build into `panel/dist`; the
simulator carries no Node packages, and imports nothing of Elysium's
(`panel/elysium_addon.py` is a copy of Elysium's add-on SDK, kept
identical by Elysium's tests).
