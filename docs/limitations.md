# Known limitations

Stated honestly, and checked against the code by `tests/unit/test_the_readme_matches_the_code.py`.

## Known limitations, honestly

- **Agent memory is written by hand, from an object's page.** Query
  is given what people asked it to remember about an object it reads,
  and never writes a memory itself -- unless a deployment turns on
  `agent.remember_from_query`, off by default, which lets it record
  one only when the question itself asks it to. A memory goes stale, and stops
  being given, when ANY field it was written from changes -- so on an
  object whose fields change daily, memories go stale daily.
- **One machine.** Several workers on one machine are supported and
  checked (`python -m elysium.scripts.check_workers`): they coordinate through
  SQLite and file locks on a shared data directory. Several machines
  sharing one data directory is not supported -- those locks are not
  reliable over a network filesystem.
- **`install.sh` is a fresh-install script, not an upgrade
  mechanism.**
- **TLS termination is a deployment responsibility**, not this
  application's own.
- **Encryption at rest is the volume's job.** Elysium checks for an
  encrypted volume at startup and encrypts its own backups (AES-256-GCM,
  key kept apart), but adds no field-level layer of its own.
- **Pre-customer.** No production deployments, no SOC 2, no
  third-party penetration test, no certifications.

Each is a deliberate, documented scope decision rather than a silent
gap.

### What this list used to say, and no longer does

**"Cross-silo links aren't supported."** They are. `src/elysium/core/mirror/
fusion.py` assembles one object type from several storages — a
`Customer` built from `primary_sql.customers` and
`risk_db.risk_scores` is a declared join, because every property has
exactly one authoritative home and no two storages offer a competing
value for the same property. The deterministic path came first and is
the primary one; the gold layer works with zero inference.

This line survived in the README long after the code contradicted it,
which is the ordinary fate of a limitations section nobody rereads. If
you find another, it is a bug in this file.
