"""
manifest.py  (what the lake says about itself)

WHY. A lake in object storage already survives its installation being
deleted -- proved by deleting one and reading its data from elsewhere.
What it cannot do is SAY WHAT THE DATA MEANS. A fresh Elysium on a
preserved bucket finds tables, rows and provenance, and no ontology to
interpret any of it.

Microsoft's Common Data Model states the goal exactly: self-describing
data in a lake, where "the format of a shared folder helps each
consumer avoid having to 'relearn' the meaning of the data in the
lake."

A COPY, NOT A HOME. The configuration is AUTHORED in version control
and LOADED from /etc/elysium; this is a third thing, published beside
the data as a record of what was true when those tables were written.
Nothing reads it in normal operation, so it cannot drift into being a
second source of truth -- which is the failure two owners would
produce.

The parallel with bronze is exact: bronze does not replace the silo,
it records what the silo said at a moment. This does not replace
/etc/elysium.

IN STORAGE RATHER THAN IN THE CATALOG, and pyiceberg supports both --
create_namespace takes arbitrary properties, so this was a choice.
Storage wins because it SURVIVES CATALOG LOSS, which is precisely when
someone most needs to know what the tables were; because it is
readable with `aws s3 cp` and no library; and because configuration
describes the whole deployment rather than one table, so it belongs at
the deployment's level.

ONE PER GENERATION, never overwritten. "What was the ontology when this
snapshot was written" is the question this exists to answer, and a
single current file cannot answer it.

AN ALLOW-LIST, NOT AN EXCLUSION LIST. An exclusion list fails open the
day someone adds a file to the config directory, and the file they add
will be the one with the credentials in it.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# WHERE MANIFESTS LIVE, under a name no ontology could collide with:
# a namespace is a silo name, and a leading underscore is not legal in
# one.
MANIFEST_PREFIX = "_elysium"

# WHAT MAY BE PUBLISHED, named one by one.
#
# NOT "everything except secrets". An exclusion list is correct only
# until someone adds a file, and the failure is silent and total: the
# credentials end up in a bucket many things can read. This list has to
# be edited deliberately to grow, which is the point.
PUBLISHABLE = ("ontology_schema.yaml", "data_silos.yaml", "policy.yaml")

# HOW MANY CONSECUTIVE ABSENT GENERATIONS END THE SEARCH.
#
# Manifests are written only when configuration CHANGES, so gaps are
# normal: generations 1, 2 and 5 may exist while 3 and 4 do not. A gap
# of ten is far larger than any run of unchanged-configuration reloads
# a real deployment produces, and the cost of being wrong is a manifest
# nobody sees rather than data nobody can read.
_PROBE_GAP = 10

# THE MOST GENERATIONS EVER PROBED FOR. A deployment reloading its
# configuration ten thousand times has other problems; this guards
# against never terminating rather than imposing a real limit.
_MAX_GENERATIONS = 10_000

# DELIBERATELY ABSENT, recorded so the omission reads as a decision
# rather than an oversight:
#
#   config.yaml  -- the LLM block describes the APPLICATION, not the
#                   data. A second Elysium on the same lake might
#                   reasonably use a different model.
#   credentials.db, secrets/
#                -- a lake reader must never become a credential
#                   reader, and the whole point of a lake is that many
#                   things read it.


def build_manifest(generation: int, loaded_at: str, source_digest: str,
                    files: dict[str, str], tables: list[str]) -> dict[str, Any]:
    """The manifest for one configuration generation.

    THE TABLES IT DESCRIBES ARE INCLUDED, so a reader can tell whether
    the manifest still matches what the catalog holds. A manifest
    naming types that no longer exist is exactly the mismatch someone
    needs told about, and it cannot be detected from the configuration
    alone.
    """
    return {
        # A version on the manifest itself, because the first thing a
        # future reader needs is to know whether it understands the
        # shape it is holding.
        "manifest_version": 1,
        "generation": generation,
        "loaded_at": loaded_at,
        # The digest of the WHOLE configuration, including the parts
        # not published -- so a reader can tell that two manifests came
        # from different configurations even when their published
        # files match.
        "source_digest": source_digest,
        "tables": sorted(tables),
        "files": {
            name: content for name, content in sorted(files.items())
            if name in PUBLISHABLE
        },
        # NAMED RATHER THAN SILENTLY DROPPED. A reader finding four
        # files where the deployment had five should be told that was
        # deliberate.
        "withheld": sorted(name for name in files if name not in PUBLISHABLE),
    }


def publish(catalog, generation: int, loaded_at: str, source_digest: str,
             files: dict[str, str], tables: list[str]) -> "str | None":
    """Writes a manifest beside the data, returning where it went.

    THROUGH THE CATALOG'S OWN FileIO, so it lands wherever the
    warehouse is -- a local directory or an S3 bucket -- without this
    module knowing which. Writing with `open()` would work locally and
    silently do nothing useful for the deployment that most needs it.

    FAILURE DOES NOT FAIL THE CALLER. A missing manifest costs a future
    reader an explanation; a failed sync costs the deployment its data.
    The same trade bronze makes, and it is warned for the same reason.
    """
    manifest = build_manifest(generation, loaded_at, source_digest, files, tables)
    location = f"{_warehouse_root(catalog)}/{MANIFEST_PREFIX}/manifest-{generation}.json"

    try:
        output = _file_io(catalog).new_output(location)
        with output.create(overwrite=True) as stream:
            stream.write(json.dumps(manifest, indent=2, sort_keys=True).encode())
    except Exception as e:  # noqa: BLE001 - see the docstring
        logger.warning(
            f"manifest for generation {generation} not published ({e}); the lake "
            f"holds its data but cannot explain it to a fresh install."
        )
        return None

    return location


def read_manifests(catalog) -> list[dict[str, Any]]:
    """Every manifest in the lake, newest generation first.

    RETURNS WHAT IT CAN RATHER THAN RAISING. A manifest that cannot be
    parsed is a finding to report, not a reason to hide the ones that
    can.
    """
    root = f"{_warehouse_root(catalog)}/{MANIFEST_PREFIX}"
    found: list[dict[str, Any]] = []

    try:
        io = _file_io(catalog)
        # BY ASKING FOR EACH GENERATION rather than listing a
        # directory. FileIO has no list operation -- it is an interface
        # for reading and writing named objects, and object stores have
        # no directories to list anyway. Generations are consecutive
        # integers from 1, so probing upward from 1 until several in a
        # row are absent finds them all without a listing API.
        missing_run = 0
        generation = 1
        # AN UPPER BOUND AS WELL AS A GAP, because the gap alone
        # terminates only while each probe names a DIFFERENT file. A
        # control that made publish() write one fixed name turned this
        # into an infinite loop that exhausted memory -- the probe kept
        # finding the same manifest and never counted a miss.
        #
        # That mutation is contrived; the fragility is not. A loop
        # whose termination depends on a filename template matching a
        # writer's is one refactor away from not terminating, and a
        # bound costs nothing.
        while missing_run < _PROBE_GAP and generation <= _MAX_GENERATIONS:
            location = f"{root}/manifest-{generation}.json"
            try:
                with io.new_input(location).open() as stream:
                    found.append(json.loads(stream.read()))
                missing_run = 0
            except Exception:  # noqa: BLE001 - absence is the normal case
                missing_run += 1
            generation += 1
    except Exception as e:  # noqa: BLE001 - a lake with no manifests is normal
        logger.debug(f"no manifests read ({e})")
        return []

    return sorted(found, key=lambda m: m.get("generation", 0), reverse=True)


def _file_io(catalog):
    """The catalog's own FileIO, built from its own properties.

    SO S3 CREDENTIALS AND ENDPOINTS APPLY HERE TOO, without this module
    knowing what they are. Building a filesystem independently would
    work against a local warehouse and fail against the object storage
    that makes a lake portable in the first place -- which is exactly
    the deployment this feature exists for.
    """
    from pyiceberg.io import load_file_io

    return load_file_io(properties=catalog.properties)


def _warehouse_root(catalog) -> str:
    """The warehouse URI, however the catalog was configured.

    PRIVATE ACCESS, DELIBERATELY. pyiceberg exposes no public accessor
    for a catalog's warehouse or its FileIO, and the alternative --
    passing them in alongside the catalog everywhere -- would let the
    two diverge, which is the failure this whole note is about.
    """
    return str(catalog.properties["warehouse"]).rstrip("/")


def publish_manifest(sync, config) -> None:
    """Publishes this generation's configuration beside the data.

    AT SYNC TIME, because that is where both halves are in hand: the
    configuration that was loaded, and the catalog it wrote to. The
    alternative -- publishing when a generation is recorded -- is the
    same moment logically, but api/app.py holds no catalog and would
    have to build one.

    ONE PER GENERATION AND NEVER OVERWRITTEN, so a resync that changed
    nothing rewrites the same file harmlessly and a resync after a
    configuration change writes a new one.

    A COPY, NOT A HOME. The configuration is authored in version
    control and loaded from /etc/elysium; this records what was true
    when the lake's tables were written, so a fresh Elysium on a
    preserved bucket can say what it found rather than only that it
    found something. Nothing reads it in normal operation.

    NEVER FAILS THE CALLER, for the same reason record_generation does
    not: losing a manifest costs a future reader an explanation, and
    refusing to start costs the deployment its availability.
    """
    if sync is None:
        return
    try:
        tables = [
            ".".join(identifier)
            for namespace in sync._catalog.list_namespaces()  # noqa: SLF001
            for identifier in sync._catalog.list_tables(namespace)  # noqa: SLF001
        ]
        publish(
            sync._catalog,  # noqa: SLF001 - the sync owns its catalog
            config.generation,
            config.loaded_at.isoformat(),
            config.source_digest,
            dict(config.source_text),
            tables,
        )
    except Exception as e:  # noqa: BLE001 - see the docstring
        logging.getLogger(__name__).warning(
            f"could not publish manifest for generation {config.generation}: {e}"
        )
