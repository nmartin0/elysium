"""Who can read the lake, as a decision rather than a default
(OPEN_RISKS item 2).

WHAT THE LAKE IS NOW. Gold holds one table per object type, keyed by
object id, conformed, deduplicated, joined across sources, with
lineage attached. The ontology applies MAC on read -- but that is a
property of the READ PATH, not of the files. A process that can open
the Parquet reads every row and every column, because that is how
Iceberg is designed: it "does not control which users can read which
rows, and it cannot mask column values based on user identity".

AND THAT CHANGED WITHOUT ANYBODY DECIDING IT SHOULD. The mirror used
to be a scattered copy of source tables under source column names.
Gold is the business picture, and the same bytes became far more worth
stealing.

SO: THE WAREHOUSE DIRECTORY IS PART OF THE SECURITY PERIMETER, not a
cache. Read access to it IS read access to everything the ontology
describes, for every region and every classification, with no audit
entry.

WHAT THIS MODULE DOES ABOUT IT, which is the cheapest honest thing:

  A LAKE ELYSIUM CREATES IS PRIVATE -- 0o700, owner only. It was 0o755
  by default, which on a shared host means every account on the box.

  A LAKE THAT ALREADY EXISTS IS REPORTED, NOT CHANGED. An operator may
  have widened it deliberately -- a backup user, a read-only analytics
  mount -- and silently revoking that at startup would break a working
  deployment to enforce a preference. So it says what it found, names
  the mode, and gives the command.

WHAT IT DOES NOT DO: encryption at rest. That is a volume or bucket
concern, it protects the stolen-disk case rather than the
logged-in-process case, and pretending a file mode is encryption would
be worse than saying neither.
"""

import stat
from pathlib import Path

# Owner only. Iceberg writes both the catalog database and the Parquet
# under here, so one mode covers the lot.
PRIVATE_MODE = 0o700


def make_private(directory: Path) -> None:
    """Create a directory owner-only, or leave an existing one alone.

    THE ASYMMETRY IS DELIBERATE: creating is ours, and an existing
    directory is the operator's.
    """
    if directory.exists():
        return
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(PRIVATE_MODE)


def readable_by_others(directory: Path) -> str | None:
    """The mode, if anyone but the owner can read this. Else None."""
    if not directory.exists():
        return None
    mode = stat.S_IMODE(directory.stat().st_mode)
    if mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IXGRP | stat.S_IXOTH):
        return oct(mode)
    return None


def warn_if_world_readable(directory: Path, logger) -> bool:
    """Say so, once, at startup. Returns whether it warned.

    NAMED AND ACTIONABLE, because a warning an operator cannot act on
    is noise: it gives the mode it found and the command that fixes
    it.
    """
    mode = readable_by_others(directory)
    if mode is None:
        return False
    logger.warning(
        f"{directory} is {mode}: anyone with an account on this host can read "
        f"the whole gold layer -- every object type, every region, every "
        f"classification, with no audit entry. The ontology's security is "
        f"applied when data is READ THROUGH IT, not to these files. "
        f"If that is not deliberate: chmod 700 {directory}"
    )
    return True
