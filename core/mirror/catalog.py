"""Opening the mirror's Iceberg catalog, in one place (PA001-F5).

WHY THIS EXISTS. The same four lines were written out at SIX call
sites: the sync, two in deployment_loader (serving, and the gold
binding), two in api/routes.py, and scripts/check_mirror.py. FIVE of
them hard-coded a local `file://` warehouse and ignored
`mirror.storage` entirely. Only the sync -- the WRITER -- passed it.

WHAT THAT COST, measured against a moto S3 server: a deployment
configured for object storage syncs perfectly, writes
`s3://lake/w/...`, and then the server cannot build a generation at
all. The catalog stores ABSOLUTE metadata locations, so loading a
table without the endpoint and credentials raises OSError, and that
escapes build_generation(). The deployment works until its first sync
and then cannot start, restart or reload.

It is not a subtle failure once you look for it. It went unseen
because the one test that covers S3 reads back through the SYNC's own
catalog, which has the credentials.

THE RULE: nothing constructs SqlCatalog directly. Every reader gets
the same storage options the writer used, because a reader that cannot
read what the writer wrote is not a reader.
"""

from collections.abc import Mapping
from pathlib import Path

from pyiceberg.catalog.sql import SqlCatalog

from core.mirror.lake_permissions import make_private

CATALOG_NAME = "elysium_mirror"


def open_mirror_catalog(mirror_dir: Path, storage: Mapping | None = None) -> SqlCatalog:
    """The mirror catalog, honouring the deployment's storage options.

    `warehouse` in storage wins; otherwise the local directory, which
    is what a deployment with no `mirror.storage` has always used.
    Everything else (s3.endpoint, credentials, region) is passed
    through untouched, because pyiceberg -- not Elysium -- owns that
    vocabulary and enumerating it here would mean revisiting this
    function every time it gains a key.
    """
    # CREATED IF ABSENT, AND OWNER-ONLY, through the one function that
    # already decides that (OPEN_RISKS item 2, patch 395). Callers used
    # to mkdir before constructing a catalog and each could have
    # chosen a different mode; the factory that opens the lake is the
    # right place for the rule about who may read it.
    make_private(mirror_dir)
    options = dict(storage or {})
    # RESOLVED FIRST, because `as_uri()` REFUSES A RELATIVE PATH --
    # and data_dir defaults to the relative `deployment/var/lib`, so
    # this raised ValueError on every default deployment.
    #
    # A REGRESSION I INTRODUCED IN PATCH 408 and did not catch: the
    # code this replaced built the URI by hand as f"file://{path}",
    # which produced a technically malformed URI for a relative path
    # and worked anyway. Every test passes an absolute tmp_path, so
    # both tiers were blind to it; it surfaced the moment a real
    # deployment ran `python -m scripts.run_sync` from its own
    # directory.
    warehouse = (options.pop("warehouse", None)
                 or (mirror_dir / "warehouse").resolve().as_uri())
    return SqlCatalog(
        CATALOG_NAME,
        uri=f"sqlite:///{mirror_dir / 'catalog.db'}",
        warehouse=warehouse,
        **options,
    )
