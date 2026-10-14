"""Whether Elysium's data directory sits on an encrypted volume.

DECIDED 14 OCT: encryption at rest is the VOLUME's job -- LUKS, or a
cloud provider's disk encryption -- and Elysium's job is to check, and
to say so when it cannot tell. NIST SP 800-111 is plain about what this
layer buys: protection while the machine is off, and none once it is
running ("once the OS is loaded ... FDE provides no protection"). That
is the stolen-disk case. The running case is file modes
(core/mirror/lake_permissions.py) and the ontology's own access
control; a backup leaving the machine is core/encrypted_archive.py.

WHAT CAN BE SEEN FROM INSIDE. Linux dm-crypt (LUKS, plain dm-crypt)
is visible: the device under the mount is a device-mapper target whose
uuid begins "CRYPT-", possibly beneath LVM, so the device's slaves are
walked too. A cloud provider's disk encryption is NOT visible -- the
guest sees an ordinary block device -- so an operator can DECLARE it:

    ELYSIUM_STORAGE_ENCRYPTION=aws-ebs-kms     (any description)

An environment variable beside ELYSIUM_DATA_DIR, because both are facts
about the machine rather than about the deployment's ontology.

REPORTED, NEVER ENFORCED. A development machine on an unencrypted disk
is ordinary; refusing to start would teach people to set the variable
to anything. The warning names the gap and the remedy instead.
"""

import os
from dataclasses import dataclass
from pathlib import Path

DECLARED_VARIABLE = "ELYSIUM_STORAGE_ENCRYPTION"


@dataclass(frozen=True)
class StorageEncryption:
    #: "detected", "declared" or "unknown"
    state: str
    detail: str


def _mount_device(path: Path, mountinfo: str) -> "str | None":
    """The major:minor of the filesystem `path` lives on: the mount with
    the longest mount point that contains it."""
    best, device = -1, None
    target = str(path.resolve())
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        mount_point = fields[4].replace("\\040", " ")
        inside = target == mount_point or target.startswith(mount_point.rstrip("/") + "/")
        if inside and len(mount_point) > best:
            best, device = len(mount_point), fields[2]
    return device


def _is_dm_crypt(device_dir: Path, seen: "set[Path] | None" = None) -> bool:
    seen = seen or set()
    device_dir = device_dir.resolve()
    if device_dir in seen:
        return False
    seen.add(device_dir)
    uuid = device_dir / "dm" / "uuid"
    if uuid.is_file() and uuid.read_text().startswith("CRYPT-"):
        return True
    slaves = device_dir / "slaves"
    if slaves.is_dir():
        return any(_is_dm_crypt(slave, seen) for slave in slaves.iterdir())
    # A partition's own directory has no slaves; its parent disk may.
    return False


def check(data_dir: Path, *, environ=None, proc: Path = Path("/proc"),
          sys_root: Path = Path("/sys")) -> StorageEncryption:
    environ = os.environ if environ is None else environ
    declared = (environ.get(DECLARED_VARIABLE) or "").strip()
    try:
        device = _mount_device(Path(data_dir), (proc / "self" / "mountinfo").read_text())
    except OSError:
        device = None
    if device is not None and _is_dm_crypt(sys_root / "dev" / "block" / device):
        return StorageEncryption("detected", f"dm-crypt (LUKS) under {data_dir}")
    if declared:
        return StorageEncryption("declared", f"declared by {DECLARED_VARIABLE}: {declared}")
    return StorageEncryption("unknown", f"no encrypted volume found under {data_dir}")


def report(data_dir: Path, logger, **probe) -> StorageEncryption:
    """Says so, once, at startup."""
    found = check(data_dir, **probe)
    if found.state == "unknown":
        logger.warning(
            f"{data_dir} is not on a volume Elysium can see is encrypted. The mirror holds every "
            f"object, every region and every classification, and a disk that is not encrypted "
            f"gives them to whoever has the disk. Put the data directory on LUKS or on an "
            f"encrypted cloud volume; if it already is one Elysium cannot see (a cloud "
            f"provider's disk encryption), set {DECLARED_VARIABLE} to say which. INSTALL.md, "
            f"'Encryption at rest'.")
    else:
        logger.info(f"storage encryption: {found.detail}")
    return found
