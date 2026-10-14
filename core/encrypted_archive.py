"""An encrypted archive of a directory: what a backup becomes before it
leaves the machine (decided 14 Oct).

WHY BACKUPS, AND WHY ONLY BACKUPS. The owner chose volume encryption
for the running deployment plus encrypted backups. Volume encryption
covers a stolen disk and a discarded drive; it stops covering a file
the moment that file is copied off the volume, and a backup exists to
be copied off the volume. That is the one gap left, so it is the one
this closes.

THE CONSTRUCTION, all standard and none invented here:

  ENVELOPE ENCRYPTION. Each archive gets a fresh random 256-bit data
  key. The data key is wrapped with the operator's key-encryption key
  using AES Key Wrap (RFC 3394, NIST SP 800-38F) and the wrapped copy
  is stored in the header. The key-encryption key is never stored with
  the archive -- OWASP: "the KEK must be stored separately from the
  DEK" -- and HIPAA's breach safe harbor holds only if the keys were
  not compromised along with the data.

  AES-256-GCM IN SEGMENTS. An archive can be larger than memory, and
  GCM is one-shot, so the body is cut into 1 MiB segments, each sealed
  on its own. The nonce is Google Tink's streaming-AEAD layout: a
  7-byte random prefix, a 4-byte big-endian segment index, and a
  1-byte flag that is 1 only on the LAST segment. That layout is what
  makes a truncated archive fail rather than restore short: dropping
  the final segment leaves a segment that was not sealed as the last.
  Tink calls its scheme "loosely based on HRRV15" (Hoang, Reyhanitabar,
  Rogaway, Vizar, CRYPTO 2015), the STREAM construction.

  THE HEADER IS AUTHENTICATED. Every segment's associated data is the
  header's bytes, so changing the header -- the key id, the segment
  size, the nonce prefix -- breaks every segment.

WHAT IT DOES NOT DO: key management. The key-encryption key comes from
a file the operator controls; a KMS is the natural next step and needs
a provider this deployment does not yet name.
"""

import base64
import hashlib
import io
import json
import os
import struct
import tarfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap, aes_key_wrap

MAGIC = b"ELYSIUM-BACKUP\x01"
FORMAT_VERSION = 1
SEGMENT_SIZE = 1024 * 1024
KEY_BYTES = 32
_TAG_BYTES = 16
_NONCE_PREFIX_BYTES = 7
_MAX_HEADER = 64 * 1024


class ArchiveKeyError(ValueError):
    """The key-encryption key is missing, malformed, or kept somewhere
    that defeats it."""


class CorruptArchive(ValueError):
    """The archive cannot be decrypted: the wrong key, a changed byte,
    or a truncation. Deliberately one type -- which of those it was is
    not something the cipher can tell, and guessing would mislead."""


def generate_key() -> bytes:
    return os.urandom(KEY_BYTES)


def key_id(kek: bytes) -> str:
    """Names a key without revealing it, so an archive can say which key
    it needs and a wrong one is reported as wrong rather than as damage."""
    return hashlib.sha256(b"elysium-backup-kek\x00" + kek).hexdigest()[:16]


def read_key_file(path: Path, *, must_not_be_under: tuple[Path, ...] = ()) -> bytes:
    """The key-encryption key from a file: 32 bytes, raw or base64.

    REFUSED WHEN IT DEFEATS ITSELF. A key file inside the data directory
    or the backup's destination is a key stored with what it protects --
    copy the directory and both go together. A key readable by other
    accounts on the machine is a key shared with them.
    """
    path = Path(path)
    if not path.is_file():
        raise ArchiveKeyError(f"No key file at {path}.")
    resolved = path.resolve()
    for place in must_not_be_under:
        place = Path(place).resolve()
        if resolved == place or place in resolved.parents:
            raise ArchiveKeyError(
                f"The key file {path} is inside {place}. A key kept with what it protects "
                f"protects nothing: keep it somewhere a copy of {place} does not reach.")
    if path.stat().st_mode & 0o077:
        raise ArchiveKeyError(
            f"The key file {path} can be read by other accounts on this machine. "
            f"chmod 600 {path}")
    raw = path.read_bytes().strip()
    if len(raw) != KEY_BYTES:
        try:
            raw = base64.b64decode(raw, validate=True)
        except ValueError as exc:
            raise ArchiveKeyError(f"{path} does not hold a {KEY_BYTES}-byte key.") from exc
    if len(raw) != KEY_BYTES:
        raise ArchiveKeyError(f"{path} does not hold a {KEY_BYTES}-byte key.")
    return raw


def write_key_file(path: Path) -> None:
    """A new random key, base64, owner-only. Refuses to overwrite."""
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(base64.b64encode(generate_key()) + b"\n")


def _nonce(prefix: bytes, index: int, last: bool) -> bytes:
    return prefix + struct.pack(">I", index) + (b"\x01" if last else b"\x00")


class _SegmentWriter(io.RawIOBase):
    """A write-only stream that seals every SEGMENT_SIZE bytes."""

    def __init__(self, out, aead: AESGCM, prefix: bytes, header: bytes):
        self._out, self._aead, self._prefix, self._header = out, aead, prefix, header
        self._buffer = bytearray()
        self._index = 0

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        self._buffer.extend(data)
        # Keep at least one byte back: the last segment must be sealed as
        # the last, and only close() knows which one that is.
        while len(self._buffer) > SEGMENT_SIZE:
            self._seal(bytes(self._buffer[:SEGMENT_SIZE]), last=False)
            del self._buffer[:SEGMENT_SIZE]
        return len(data)

    def _seal(self, plaintext: bytes, last: bool) -> None:
        if self._index >= 2**32 - 1:
            raise ValueError("archive too large for one key")
        self._out.write(self._aead.encrypt(_nonce(self._prefix, self._index, last),
                                           plaintext, self._header))
        self._index += 1

    def finish(self) -> None:
        self._seal(bytes(self._buffer), last=True)
        self._buffer.clear()


def encrypt_directory(source: Path, destination: Path, kek: bytes) -> dict:
    """Seals `source` (a directory) into the file `destination`.

    Written to a temporary name and renamed, so a failure part-way never
    leaves a file that looks like a finished backup.
    """
    data_key = generate_key()
    prefix = os.urandom(_NONCE_PREFIX_BYTES)
    header = json.dumps({
        "version": FORMAT_VERSION,
        "cipher": "AES-256-GCM, segmented (Tink streaming layout)",
        "key_wrap": "AES-KW (RFC 3394)",
        "key_id": key_id(kek),
        "wrapped_key": base64.b64encode(aes_key_wrap(kek, data_key)).decode(),
        "nonce_prefix": base64.b64encode(prefix).decode(),
        "segment_size": SEGMENT_SIZE,
    }, sort_keys=True).encode()
    partial = destination.with_name(destination.name + ".partial")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(MAGIC + struct.pack(">I", len(header)) + header)
            writer = _SegmentWriter(out, AESGCM(data_key), prefix, header)
            with tarfile.open(fileobj=writer, mode="w|gz") as archive:
                archive.add(source, arcname=".")
            writer.finish()
        os.replace(partial, destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return {"key_id": key_id(kek), "bytes": destination.stat().st_size}


def read_header(path: Path) -> dict:
    with open(path, "rb") as source:
        return _read_header(source)[0]


def _read_header(source) -> tuple[dict, bytes]:
    if source.read(len(MAGIC)) != MAGIC:
        raise CorruptArchive("Not an encrypted Elysium backup.")
    (length,) = struct.unpack(">I", source.read(4))
    if length > _MAX_HEADER:
        raise CorruptArchive("The archive header is implausibly large.")
    raw = source.read(length)
    try:
        header = json.loads(raw)
    except ValueError as exc:
        raise CorruptArchive("The archive header is unreadable.") from exc
    if header.get("version") != FORMAT_VERSION:
        raise CorruptArchive(f"Archive format {header.get('version')!r}; this build reads "
                             f"{FORMAT_VERSION}.")
    return header, raw


def is_encrypted_archive(path: Path) -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    with open(path, "rb") as source:
        return source.read(len(MAGIC)) == MAGIC


def decrypt_to_directory(path: Path, destination: Path, kek: bytes) -> None:
    """Opens an archive into `destination`, or refuses having written
    nothing usable.

    EVERY SEGMENT IS AUTHENTICATED BEFORE THE ARCHIVE IS UNPACKED. The
    plaintext goes to a temporary file first; only a stream whose last
    segment was sealed as the last is handed to tarfile. Unpacking as
    segments arrived would put an attacker's prefix on disk before the
    tampering was noticed.
    """
    with open(path, "rb") as source:
        header, raw_header = _read_header(source)
        if header.get("key_id") != key_id(kek):
            raise ArchiveKeyError(
                f"This archive needs key {header.get('key_id')}; the key given is "
                f"{key_id(kek)}.")
        try:
            data_key = aes_key_unwrap(kek, base64.b64decode(header["wrapped_key"]))
        except (InvalidUnwrap, KeyError, ValueError) as exc:
            raise CorruptArchive("The archive's data key cannot be unwrapped.") from exc
        aead = AESGCM(data_key)
        prefix = base64.b64decode(header["nonce_prefix"])
        sealed = int(header["segment_size"]) + _TAG_BYTES
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        plain = destination / ".archive.tar.gz"
        index, finished = 0, False
        with open(plain, "wb") as out:
            chunk = source.read(sealed)
            while chunk:
                following = source.read(sealed)
                last = not following
                try:
                    out.write(aead.decrypt(_nonce(prefix, index, last), chunk, raw_header))
                except Exception as exc:
                    raise CorruptArchive(
                        "The archive does not decrypt: a changed byte, a truncated file, "
                        "or segments out of order.") from exc
                index += 1
                finished = last
                chunk = following
        if not finished:
            plain.unlink(missing_ok=True)
            raise CorruptArchive("The archive is empty or truncated.")
    try:
        with tarfile.open(plain, mode="r:gz") as archive:
            archive.extractall(destination, filter="data")
    finally:
        plain.unlink(missing_ok=True)
