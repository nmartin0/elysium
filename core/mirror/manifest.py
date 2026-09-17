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

from pyarrow.fs import FileSelector

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

# NO PROBE CONSTANTS ANY MORE. A gap size and an upper bound existed
# only to make a guessing loop terminate; listing the directory needs
# neither.

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
    # INSIDE THE TRY, ALL OF IT. Resolving the warehouse sat outside
    # and raised KeyError straight past a docstring promising this
    # never fails the caller -- found by an audit narrowing the catch,
    # which made an escape visible that `except Exception` had been
    # hiding by accident rather than by design.
    location = None
    try:
        manifest = build_manifest(generation, loaded_at, source_digest, files, tables)
        location = f"{_warehouse_root(catalog)}/{MANIFEST_PREFIX}/manifest-{generation}.json"

        output = _file_io(catalog).new_output(location)
        with output.create(overwrite=True) as stream:
            stream.write(json.dumps(manifest, indent=2, sort_keys=True).encode())
    except (OSError, ValueError, KeyError) as e:
        # NAMED, NOT `except Exception`, and this file was inconsistent
        # with the project's own recorded position until an audit
        # caught it. iceberg_sync.py carries the lesson: a bare catch
        # there "swallowed every real failure too (a permissions
        # problem, a full disk, a corrupt catalog)".
        #
        # It had already happened here. A bare catch turned a
        # misremembered method name -- catalog._fs_io(), which does not
        # exist -- into a warning about the manifest rather than the
        # AttributeError it was. The bug surfaced anyway, but as the
        # wrong diagnosis.
        #
        # THESE THREE, verified by making each happen rather than
        # guessed: an unwritable path raises FileNotFoundError (an
        # OSError), a bad scheme raises ValueError, and a catalog with
        # no warehouse property raises KeyError.
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

        # LISTED, NOT PROBED. An earlier version asked for
        # manifest-1.json, manifest-2.json and so on until several in a
        # row were absent, because I concluded FileIO had no list
        # operation. It does not -- but it exposes the FILESYSTEM, and
        # that does.
        #
        # parse_location splits the URI the way pyiceberg itself does,
        # and fs_by_scheme returns the pyarrow filesystem for it, so
        # this works against a local warehouse and an S3 bucket alike
        # without this module knowing which.
        #
        # The probe worked. It also guessed, needed a gap constant and
        # an upper bound to terminate, and would have silently missed a
        # manifest after a long enough run of unchanged configuration.
        scheme, netloc, path = io.parse_location(root)
        filesystem = io.fs_by_scheme(scheme, netloc)

        for entry in filesystem.get_file_info(FileSelector(path, allow_not_found=True)):
            if not entry.path.endswith(".json"):
                continue
            try:
                with io.new_input(f"{root}/{entry.path.rsplit('/', 1)[-1]}").open() as stream:
                    raw = stream.read()
            except (OSError, ValueError, KeyError):
                # LISTED BUT UNREADABLE, which is a fault rather than
                # an absence: the directory listing just said this file
                # is there. Under the old probe loop a failed read WAS
                # ordinary -- most generations do not exist -- and this
                # `continue` carried that meaning over unchanged. It no
                # longer applies, and a manifest vanishing in silence is
                # the opposite of what this module is for.
                logger.warning(
                    f"manifest at {entry.path} is listed but could not be read; "
                    f"the lake describes itself less completely than it appears to."
                )
                continue

            try:
                found.append(json.loads(raw))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # PRESENT BUT UNREADABLE is not the same as absent. A
                # corrupt manifest is the file someone reaches for
                # during an incident, so skipping it silently would
                # make a damaged lake look like an undescribed one.
                logger.warning(
                    f"manifest at {entry.path} could not be parsed and was skipped; "
                    f"the lake describes itself less completely than it appears to."
                )
    except (OSError, ValueError, KeyError) as e:
        # The same three, for the same reasons. A lake with no
        # manifests at all is normal -- every one written before this
        # existed has none -- but "normal" is the EMPTY LIST below,
        # reached without an exception. This is the failure path.
        logger.debug(f"no manifests read ({e})")
        return []

    return sorted(found, key=lambda m: m.get("generation", 0), reverse=True)


def _file_io(catalog):
    """The catalog's own FileIO, built from its own properties.

    `load_file_io` is pyiceberg's own documented entry point, not a
    reach into its internals.

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

    PUBLIC API, and an earlier version of this comment said otherwise.
    `catalog.properties` is a documented instance attribute, not a
    private one -- checked on a real catalog rather than inferred from
    the class, which is where the mistake came from: `properties` is
    set in __init__ and so does not appear on the class.

    Reading it from the catalog rather than accepting it as an
    argument is deliberate: the two could otherwise diverge, and a
    manifest written beside the wrong warehouse is worse than none.
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
            for namespace in sync.catalog.list_namespaces()
            for identifier in sync.catalog.list_tables(namespace)
        ]
        publish(
            sync.catalog,
            config.generation,
            config.loaded_at.isoformat(),
            config.source_digest,
            dict(config.source_text),
            tables,
        )
    except (OSError, ValueError, KeyError, AttributeError) as e:
        # AttributeError as well, here only: this reaches into the sync
        # for its catalog, so a shape change upstream is a real and
        # likely failure. Naming it keeps the warning honest about what
        # went wrong instead of reporting every fault as "the manifest
        # failed".
        logging.getLogger(__name__).warning(
            f"could not publish manifest for generation {config.generation}: {e}"
        )
