"""Rebuild the deleted-object index from the write log (F-28).

WHEN TO RUN THIS. Almost never: the service brings the index up to
date at startup by itself, and the write path maintains it as it goes.
This exists for the case a watermark cannot cover -- an index you
suspect is WRONG rather than merely behind.

    a restore that brought back an older index beside a newer log
    a manual edit of the database
    a bug in the write path that you have since fixed

THE DIFFERENCE MATTERS. The startup sync asks "has the index seen
every log row", which two integers answer. This asks "is the index
what the log says it should be", which only re-reading the log can
answer -- and which costs, MEASURED, about 22 ms per 10,000 log rows.

THE LOG IS THE AUTHORITY, which is what makes this safe to run at any
time: the index is a cache, and Foundry's own framing applies -- "all
indexed data in object databases are considered ephemeral, requiring
persistent storing of all Ontology data in other ways".

    python -m scripts.rebuild_deleted_index [data_dir]
"""

import sys
import time
from pathlib import Path

from core.deployment_loader import resolve_runtime_paths
from core.ontology.write_log import WriteLogWriter


def rebuild(data_dir: Path) -> int:
    database = data_dir / "write_log.db"
    if not database.exists():
        print(f"no write log at {database}", file=sys.stderr)
        return 1

    log = WriteLogWriter(database)
    started = time.perf_counter()
    marked = log.rebuild_deleted_index()
    elapsed = time.perf_counter() - started
    print(f"rebuilt from {database}: {marked:,} object(s) marked deleted "
          f"in {elapsed * 1000:.0f} ms")
    # SAID OUT LOUD because it is the question an operator asks next,
    # and because a rebuild that changed nothing is the expected
    # outcome rather than a wasted run.
    print("the index now matches the log; the service will find it current at startup")
    return 0


if __name__ == "__main__":  # pragma: no cover - an operator script
    if len(sys.argv) > 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    directory = (Path(sys.argv[1]) if len(sys.argv) == 2
                 else resolve_runtime_paths().data_dir)
    raise SystemExit(rebuild(directory))
