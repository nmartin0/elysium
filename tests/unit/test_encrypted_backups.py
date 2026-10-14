"""
Encrypted backups and the storage-encryption check (decided 14 Oct:
volume encryption for the running deployment, encrypted backups for
what leaves it).

WHAT THE ARCHIVE MUST DO, each a test below:
  - round-trip a directory exactly;
  - hold none of it in the clear;
  - refuse the wrong key, a changed byte, and a truncation -- the last
    being what the last-segment flag in the nonce is for;
  - refuse a key file kept with what it protects, or readable by others.

AND THE CLI: a backup is encrypted unless --unencrypted is said, and
restore opens one with the key and puts the deployment back.
"""

import base64
import logging
import os
import sqlite3
import subprocess
import sys

import pytest

from core import encrypted_archive as archive
from core.encrypted_archive import ArchiveKeyError, CorruptArchive
from core.notifications import NotificationStore
from core.storage_encryption import check

SECRET = "ada.okafor@example.com"


@pytest.fixture
def tree(tmp_path):
    source = tmp_path / "source"
    (source / "mirror").mkdir(parents=True)
    (source / "notes.txt").write_text(f"customer {SECRET}\n" * 50)
    # Bigger than one segment, and not a multiple of it.
    (source / "mirror" / "big.bin").write_bytes(os.urandom(archive.SEGMENT_SIZE * 2 + 1234))
    return source


@pytest.fixture
def key(tmp_path):
    path = tmp_path / "keys" / "backup.key"
    path.parent.mkdir()
    archive.write_key_file(path)
    return path


def _seal(tree, key, tmp_path):
    sealed = tmp_path / "out" / "b.elysium-backup"
    sealed.parent.mkdir(exist_ok=True)
    archive.encrypt_directory(tree, sealed, archive.read_key_file(key))
    return sealed


class TestTheArchive:
    def test_it_round_trips_exactly(self, tree, key, tmp_path):
        sealed = _seal(tree, key, tmp_path)

        archive.decrypt_to_directory(sealed, tmp_path / "back", archive.read_key_file(key))

        for name in ("notes.txt", "mirror/big.bin"):
            assert (tmp_path / "back" / name).read_bytes() == (tree / name).read_bytes()

    def test_nothing_is_in_the_clear(self, tree, key, tmp_path):
        raw = _seal(tree, key, tmp_path).read_bytes()

        assert SECRET.encode() not in raw
        assert b"notes.txt" not in raw            # names too, unlike file-level encryption

    def test_the_wrong_key_is_named_as_the_wrong_key(self, tree, key, tmp_path):
        sealed = _seal(tree, key, tmp_path)
        other = tmp_path / "keys" / "other.key"
        archive.write_key_file(other)

        with pytest.raises(ArchiveKeyError, match="needs key"):
            archive.decrypt_to_directory(sealed, tmp_path / "back", archive.read_key_file(other))

    def test_a_changed_byte_is_refused(self, tree, key, tmp_path):
        sealed = _seal(tree, key, tmp_path)
        data = bytearray(sealed.read_bytes())
        data[-5000] ^= 0x01
        sealed.write_bytes(bytes(data))

        with pytest.raises(CorruptArchive):
            archive.decrypt_to_directory(sealed, tmp_path / "back", archive.read_key_file(key))

    def test_a_truncation_at_a_segment_boundary_is_refused(self, tree, key, tmp_path):
        """THE LAST-SEGMENT FLAG. Cut the final segment off and every
        remaining segment still decrypts on its own; only the flag says
        the stream ended early."""
        sealed = _seal(tree, key, tmp_path)
        header = archive.read_header(sealed)
        data = sealed.read_bytes()
        body_start = len(archive.MAGIC) + 4 + len(
            __import__("json").dumps(header, sort_keys=True).encode())
        segment = header["segment_size"] + 16
        whole_segments = (len(data) - body_start) // segment
        sealed.write_bytes(data[:body_start + whole_segments * segment])

        with pytest.raises(CorruptArchive):
            archive.decrypt_to_directory(sealed, tmp_path / "back", archive.read_key_file(key))
        assert not (tmp_path / "back" / "notes.txt").exists()

    def test_a_changed_header_is_refused(self, tree, key, tmp_path):
        """The header is every segment's associated data. The field
        changed here is one decryption never reads, so only that binding
        can notice."""
        sealed = _seal(tree, key, tmp_path)
        data = sealed.read_bytes().replace(b'"AES-KW (RFC 3394)"', b'"AES-KW (RFC 3395)"')
        sealed.write_bytes(data)

        with pytest.raises(CorruptArchive):
            archive.decrypt_to_directory(sealed, tmp_path / "back", archive.read_key_file(key))


class TestTheKeyFile:
    def test_a_key_inside_what_it_protects_is_refused(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        archive.write_key_file(data / "backup.key")

        with pytest.raises(ArchiveKeyError, match="protects nothing"):
            archive.read_key_file(data / "backup.key", must_not_be_under=(data,))

    def test_a_key_others_can_read_is_refused(self, key):
        key.chmod(0o644)

        with pytest.raises(ArchiveKeyError, match="chmod 600"):
            archive.read_key_file(key)

    def test_a_new_key_is_owner_only_and_never_overwritten(self, key):
        assert key.stat().st_mode & 0o777 == 0o600
        assert len(base64.b64decode(key.read_bytes().strip())) == 32
        with pytest.raises(FileExistsError):
            archive.write_key_file(key)


def _cli(module, *args, env):
    return subprocess.run([sys.executable, "-m", module, *args], capture_output=True,
                          text=True, env={**os.environ, **env}, timeout=120)


class TestTheCommands:
    @pytest.fixture
    def deployment(self, tmp_path, key):
        data = tmp_path / "data"
        data.mkdir()
        NotificationStore(data / "notifications.db").notify("alice", "k", f"about {SECRET}")
        env = {"ELYSIUM_DATA_DIR": str(data), "ELYSIUM_BACKUP_KEY_FILE": str(key)}
        return data, env

    def test_a_backup_is_encrypted_and_restores(self, deployment, tmp_path):
        data, env = deployment
        sealed = tmp_path / "backups" / "out.elysium-backup"
        sealed.parent.mkdir()

        made = _cli("scripts.backup_deployment", str(sealed), env=env)
        assert made.returncode == 0, made.stderr
        assert SECRET.encode() not in sealed.read_bytes()

        target = tmp_path / "restored"
        target.mkdir()
        # --force: this tiny deployment lacks credentials.db, which a
        # restore rightly calls a problem; the point here is the archive.
        back = _cli("scripts.restore_deployment", str(sealed), "--into", str(target), "--force",
                    env=env)
        assert back.returncode == 0, back.stdout + back.stderr
        rows = sqlite3.connect(target / "notifications.db").execute(
            "SELECT summary FROM notifications").fetchall()
        assert rows == [(f"about {SECRET}",)]

    def test_without_a_key_it_refuses_rather_than_writing_plain(self, deployment, tmp_path):
        data, env = deployment
        made = _cli("scripts.backup_deployment", str(tmp_path / "x"),
                    env={**env, "ELYSIUM_BACKUP_KEY_FILE": ""})

        assert made.returncode == 1
        assert "--new-key" in made.stderr
        assert not (tmp_path / "x").exists()

    def test_plain_only_when_asked(self, deployment, tmp_path):
        data, env = deployment
        made = _cli("scripts.backup_deployment", "--unencrypted", str(tmp_path / "plain"),
                    env={**env, "ELYSIUM_BACKUP_KEY_FILE": ""})

        assert made.returncode == 0, made.stderr
        assert (tmp_path / "plain" / "notifications.db").exists()
        assert "UNENCRYPTED" in made.stdout

    def test_a_restore_with_the_wrong_key_touches_nothing(self, deployment, tmp_path):
        data, env = deployment
        sealed = tmp_path / "backups" / "out.elysium-backup"
        sealed.parent.mkdir()
        _cli("scripts.backup_deployment", str(sealed), env=env)
        other = tmp_path / "keys" / "other.key"
        archive.write_key_file(other)
        target = tmp_path / "restored"
        target.mkdir()

        back = _cli("scripts.restore_deployment", str(sealed), "--into", str(target),
                    env={**env, "ELYSIUM_BACKUP_KEY_FILE": str(other)})

        assert back.returncode == 1
        assert "Nothing was restored" in back.stderr
        assert list(target.iterdir()) == []


class TestTheVolumeCheck:
    """Against a fake /proc and /sys, since this machine's real ones say
    nothing either way."""

    def _machine(self, tmp_path, uuid: "str | None", via_lvm=False):
        proc, sys_root = tmp_path / "proc", tmp_path / "sys"
        (proc / "self").mkdir(parents=True)
        (proc / "self" / "mountinfo").write_text(
            "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
            f"40 22 253:1 / {tmp_path}/srv rw - ext4 /dev/mapper/x rw\n")
        mapped = sys_root / "dev" / "block" / "253:1"
        crypt = sys_root / "dev" / "block" / "253:0"
        (mapped / "dm").mkdir(parents=True)
        (crypt / "dm").mkdir(parents=True)
        if via_lvm:
            (mapped / "dm" / "uuid").write_text("LVM-abc\n")
            (mapped / "slaves").mkdir()
            (mapped / "slaves" / "dm-0").symlink_to(crypt)
            (crypt / "dm" / "uuid").write_text(uuid or "")
        elif uuid is not None:
            (mapped / "dm" / "uuid").write_text(uuid)
        (tmp_path / "srv" / "data").mkdir(parents=True)
        return {"proc": proc, "sys_root": sys_root}

    def test_luks_is_detected(self, tmp_path):
        probe = self._machine(tmp_path, "CRYPT-LUKS2-0123-x\n")

        assert check(tmp_path / "srv" / "data", environ={}, **probe).state == "detected"

    def test_luks_under_lvm_is_detected(self, tmp_path):
        probe = self._machine(tmp_path, "CRYPT-LUKS2-0123-x\n", via_lvm=True)

        assert check(tmp_path / "srv" / "data", environ={}, **probe).state == "detected"

    def test_a_plain_device_is_unknown_and_warned(self, tmp_path, caplog):
        """THE CONTROL: a device-mapper target is not encryption by itself."""
        from core.storage_encryption import report

        probe = self._machine(tmp_path, "LVM-abc\n")
        with caplog.at_level(logging.WARNING):
            found = report(tmp_path / "srv" / "data", logging.getLogger("t"), environ={}, **probe)

        assert found.state == "unknown"
        assert "ELYSIUM_STORAGE_ENCRYPTION" in caplog.text

    def test_a_cloud_volume_can_be_declared(self, tmp_path):
        probe = self._machine(tmp_path, None)

        found = check(tmp_path / "srv" / "data",
                      environ={"ELYSIUM_STORAGE_ENCRYPTION": "aws-ebs-kms"}, **probe)

        assert (found.state, "aws-ebs-kms" in found.detail) == ("declared", True)
